"""Shared execution skeleton for the nine proceeding search tools (dup §2.1).

Every search_{trials,appeals,interferences}_{minimal,balanced,complete} tool
follows the same control flow after its per-tool validation and
FilterBuilder step: resolve the field selection -> call the client's search
endpoint -> pass API errors through -> field-filter the response -> format.
That skeleton lives here once; each tool body keeps only its own signature,
docstring, validation, and filter construction.
"""

import functools
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..config.api_constants import USPTO_NO_MATCH_MARKER
from ..shared.circuit_breaker import CircuitBreakerOpenError
from ..shared.error_utils import sanitize_error_message
from ..shared.safe_logger import get_safe_logger
from ..validation.validators import validate_custom_fields
from .response_formatter import (
    create_query_info,
    format_error_response,
    format_proceeding_response,
    from_api_envelope,
)

logger = get_safe_logger(__name__)

# proceeding -> (results bag key, PTABClient search method name)
SEARCH_TOOL_CONFIG: Dict[str, Tuple[str, str]] = {
    "trials": ("patentTrialProceedingDataBag", "search_trials"),
    "appeals": ("patentAppealDataBag", "search_appeals"),
    "interferences": ("patentInterferenceDataBag", "search_interferences"),
}

# The USPTO PTAB API signals "zero matching records" with HTTP 404 rather
# than an empty result set, so every no-results search surfaced as a raw
# error envelope instead of a normal (empty) success response (verified
# live 2026-08-16, e.g. PTAB_search_trials_minimal(patent_owner_name="Broadcom")).
# Applied to the search tools only — a 404 on a document/proceeding lookup
# by a specific ID (PTAB_get_documents, PTAB_get_document_content, etc.) is
# a real error and is deliberately NOT touched by this helper.
# Single source: config/api_constants. The API layer tags the envelope with
# no_matching_records; this string stays as the fallback for an envelope that
# did not go through that path.
_NO_MATCH_MARKER = USPTO_NO_MATCH_MARKER

_NO_MATCH_NOTE = (
    "No matching records for this query (the USPTO PTAB API reports an "
    "empty result set as HTTP 404). Try broadening the search: for party "
    "names, exact form matters (e.g. 'Broadcom' vs 'Broadcom Inc.', "
    "'Samsung' vs 'Samsung Electronics Co., Ltd.') — try a shorter or "
    "partial name, or drop other filters (trial_status, date ranges)."
)


def is_no_matches_error(response: Dict[str, Any]) -> bool:
    """True when a raw API response is the USPTO no-matching-records 404."""
    if not isinstance(response, dict):
        return False
    # Prefer the tag the API layer set; fall back to matching USPTO's prose so
    # an envelope built on another path still resolves correctly.
    if response.get("no_matching_records") is True:
        return True
    return (
        response.get("status_code") == 404
        and _NO_MATCH_MARKER in str(response.get("error", ""))
    )


#: A RuntimeError carrying either of these is the interpreter tearing down
#: under us, not a fault in the request. Matched by message because the
#: framework raises a bare RuntimeError with no distinguishing type.
_ASYNC_LIFECYCLE_MARKERS = ("cannot schedule new futures", "interpreter shutdown")


def async_lifecycle_envelope(exc: RuntimeError, tool_name: str) -> str:
    """Envelope for an interpreter-shutdown RuntimeError, or re-raise.

    The three document tools each carried a verbatim copy of this 17-line
    branch with the tool name maintained by hand, and the copies emitted a
    bare {"error", "message", "technical_details"} dict that no other tool
    path produced. One implementation, and the same shape the decorator uses,
    so a search tool and a document tool answer an interpreter shutdown
    identically.
    """
    if not any(m in str(exc) for m in _ASYNC_LIFECYCLE_MARKERS):
        raise exc
    logger.error(f"Async lifecycle error in {tool_name}: {exc}")
    return format_error_response(
        "Operation failed due to async runtime issue. "
        "Try restarting the MCP server.",
        "INTERNAL_ERROR",
        details={"technical_details": sanitize_error_message(str(exc))},
    )


def mcp_tool_error_envelope(fn):
    """Standard tool error envelope (dup §3.1).

    Replaces the hand-rolled two-clause try/except that every search tool
    carried (with the tool name maintained by hand in each copy). The
    async-lifecycle clause was a fourth hand-rolled copy in each of the three
    document tools; it lives here now so all fifteen tools answer an
    interpreter shutdown the same way.

    Categories are real rather than all-API_ERROR: a timeout, an open circuit
    and an internal bug got the model no way to tell "retry this" from "your
    parameters are wrong" from "the server has a bug".
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ValueError as e:
            return format_error_response(str(e), "VALIDATION_ERROR")
        except RuntimeError as e:
            if not any(m in str(e) for m in _ASYNC_LIFECYCLE_MARKERS):
                raise
            logger.error(f"Async lifecycle error in {fn.__name__}: {e}")
            return format_error_response(
                "Operation failed due to async runtime issue. "
                "Try restarting the MCP server.",
                "INTERNAL_ERROR",
                details={"technical_details": sanitize_error_message(str(e))},
            )
        except httpx.TimeoutException as e:
            logger.error(f"Timeout in {fn.__name__}: {type(e).__name__}")
            return format_error_response(str(e), "TIMEOUT_ERROR")
        except CircuitBreakerOpenError as e:
            logger.warning(f"Circuit open in {fn.__name__}: {e}")
            return format_error_response(str(e), "RATE_LIMIT_ERROR")
        except (KeyError, TypeError, AttributeError) as e:
            logger.exception("Internal error in %s", fn.__name__)
            return format_error_response(str(e), "INTERNAL_ERROR")
        except Exception as e:
            logger.error(f"Error in {fn.__name__}: {str(e)}")
            return format_error_response(str(e), "API_ERROR")

    return wrapper


def resolve_field_selection(
    field_manager, proceeding: str, tier: str, fields: Optional[List[str]]
) -> Tuple[Optional[List[str]], List[str], str]:
    """(validated_custom_fields, field_list, field_set_name) for a search call."""
    if fields:
        fields = validate_custom_fields(fields)
        return fields, fields, "custom"
    field_set_name = f"{proceeding}_{tier}"
    return None, field_manager.get_fields(field_set_name), field_set_name


def build_paging_block(
    *,
    limit_requested: int,
    limit_applied: int,
    offset: int,
    returned: int,
    total: Optional[int],
) -> Dict[str, Any]:
    """The `paging` block every search envelope carries.

    Reports the limit that was ACTUALLY applied next to what was requested,
    so any divergence (the bulk trial-number path forces limit=100 per chunk)
    is visible instead of silent. `total` is the API's TOTAL match count — it
    used to sit beside a single page of rows with no has_more at all, so a
    50-row page next to `count: 4312` read as if 4312 records had arrived.
    """
    has_more = isinstance(total, int) and (offset + returned) < total
    return {
        "limit_requested": limit_requested,
        "limit_applied": limit_applied,
        "offset": offset,
        "returned": returned,
        "total": total if isinstance(total, int) else None,
        "has_more": has_more,
        "next_offset": offset + returned if has_more else None,
    }


async def run_search(
    *,
    proceeding: str,
    tier: str,
    client,
    field_manager,
    filters: List[Dict[str, Any]],
    range_filters: List[Dict[str, Any]],
    fields: Optional[List[str]],
    limit: int,
    offset: int = 0,
    extra_query_info: Optional[Dict[str, Any]] = None,
    raw_response: Optional[Dict[str, Any]] = None,
    no_matches: bool = False,
    limit_applied: Optional[int] = None,
    paging_note: Optional[str] = None,
    q: Optional[str] = None,
    upstream_filters: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Execute the shared search pipeline and return the formatted JSON.

    Args:
        proceeding: "trials" | "appeals" | "interferences"
        tier: "minimal" | "balanced" | "complete"
        client: PTABClient instance
        field_manager: FieldManager instance
        filters / range_filters: FilterBuilder output
        fields: Optional custom field list (else the {proceeding}_{tier} set)
        limit: Validated result limit
        offset: Zero-based starting record index. This was previously pinned
            to 0 in the request body, so results 101+ were unreachable through
            any search tool no matter what the caller asked for; the USPTO
            POST search endpoints accept pagination.offset (already exercised
            by the document search) and it is now plumbed through.
        extra_query_info: Extra keys merged into query_info (bulk lookups)
        raw_response: Pre-fetched API response (bulk auto-chunking) — skips
            the API call when provided.
        no_matches: True when the caller already resolved a pre-fetched
            raw_response's HTTP 404 down to an empty bag (bulk trial-number
            lookup) — carries the same no-matches note as a 404 detected
            here would.
        limit_applied: The limit the upstream call really used, when it
            differs from `limit` (bulk chunking). Defaults to `limit`.
        paging_note: Extra explanation for the paging block.
        q: Field-scoped query string sent alongside the filters. Trials use
            it to restrict a party-name match to one side of the proceeding;
            a `filters` entry cannot express that (util/party_scope.py).
            Trials only — the appeals and interferences endpoints have not
            been probed for `q` support.
        upstream_filters: What to actually SEND, when it differs from
            `filters`. `filters` remains the response ledger, so
            `query_info.filters` still reports the field a caller's
            petitioner_name/patent_owner_name resolved to even though that
            entry moved into `q`.
    """
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("offset must be an integer >= 0")

    results_key, search_method = SEARCH_TOOL_CONFIG[proceeding]

    fields, field_list, field_set_name = resolve_field_selection(
        field_manager, proceeding, tier, fields
    )

    if raw_response is None:
        sent_filters = filters if upstream_filters is None else upstream_filters
        kwargs = {"q": q} if q else {}
        raw_response = await getattr(client, search_method)(
            filters=sent_filters if sent_filters else None,
            range_filters=range_filters if range_filters else None,
            pagination={"offset": offset, "limit": limit},
            fields=field_list,
            **kwargs,
        )

    if raw_response.get("error"):
        if is_no_matches_error(raw_response):
            no_matches = True
            raw_response = {results_key: [], "count": 0}
        else:
            # Translate once, here, rather than handing the API layer's own
            # envelope shape to the caller (EH-1).
            return from_api_envelope(raw_response)

    if fields:
        filtered_response = field_manager.filter_response_custom(raw_response, fields)
    else:
        filtered_response = field_manager.filter_response(raw_response, field_set_name)

    results = filtered_response.get(results_key, [])
    total = filtered_response.get("count", 0)
    paging = build_paging_block(
        limit_requested=limit,
        limit_applied=limit if limit_applied is None else limit_applied,
        offset=offset,
        returned=len(results),
        total=total if isinstance(total, int) else None,
    )
    if paging_note:
        paging["note"] = paging_note

    # A YAML load failure silently swaps the emergency field sets in behind an
    # unchanged `field_set` label — say so rather than let a 6-field response
    # pass for the configured one.
    fallback_note = getattr(field_manager, "fallback_note", lambda: None)()

    return format_proceeding_response(
        proceeding,
        results,
        query_info=create_query_info(
            filters=filters,
            range_filters=range_filters,
            pagination={"offset": offset, "limit": limit},
            **(extra_query_info or {}),
        ),
        field_set=field_set_name,
        context_info=filtered_response.get("context_info"),
        count=total,
        note=_NO_MATCH_NOTE if no_matches else None,
        paging=paging,
        field_set_fallback=bool(fallback_note),
        field_set_fallback_note=fallback_note,
    )
