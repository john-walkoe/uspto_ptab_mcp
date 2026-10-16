"""Tool registration package (SD-1/SOLID-1 god-module split).

Each module defines its tools as plain (envelope-wrapped) async functions and
exposes register(mcp); register_all preserves the historical registration
order: admin -> trials -> documents -> appeals -> interferences -> guidance.

register_all also wraps the FastMCP object in a thin registration proxy
(`_BoundedRegistrar`) so EVERY tool response passes through the shared
response-size guard (`shared/response_bounds.py`) on the way out — one attach
point instead of per-tool wiring. claude.ai replaces an oversized tool result
with a client-side truncation error the server never sees, so an unguarded
tool is an unrecoverable failure for the model; the guard trades some
records/fields for a usable response plus a recovery note.

This matters more here than the pre-existing local guard suggested:
tools/documents.py's `_bound_documents_response` early-returns when the
`documents` list is empty or missing, so oversized bulk anywhere else (a
`*_complete` search over records carrying documentBag / documentOCRText, a
1500-record bulk trial lookup, an OCR text dump) passed through unbounded.
The proxy closes that. PTAB tools return JSON STRINGS, so the proxy parses,
guards, and re-serializes; responses that already fit come back byte-identical
(same string object, no `_bounds` key at all).
"""

import functools
import inspect
import json
from typing import Any, Dict

from ..shared import response_bounds

from . import admin, appeals, documents, guidance, interferences, trials


# ---------------------------------------------------------------------------
# Per-tool guard configuration
# ---------------------------------------------------------------------------
# Everything repo-specific lives HERE; shared/response_bounds.py stays
# repo-agnostic and byte-identical across the USPTO MCPs.

#: Every search tool's records land under `results` (util/response_formatter
#: .format_proceeding_response). Stage 2 halves this list toward the floor.
#: The EMPTY keep_fields means stage 1 skips these records entirely (see
#: shared/response_bounds.py::_stage_slim), which is what keeps every row's
#: `cite_as` link alive under the guard. If a field whitelist is ever added
#: here, `cite_as` has to be on it: a slimmed page still has to be citable.
_SEARCH_RECORDS_SPEC = {
    "path": ["results"],
    "keep_fields": (),  # tier field-filtering already selected these
    "min_items": 5,
    "label": "results",
}

#: Heavy nested bags a `*_complete` search drags in. The complete tiers are
#: configured as `fields: ["*"]`, and config/field_manager.py:_filter_response_impl
#: short-circuits on the wildcard and returns the API payload AS-IS — so no
#: tier filtering runs at all and whatever the record carries ships whole.
#: These are the per-record bags that carry the bulk: `documentBag` (flagged
#: in field_configs.yaml as a 100x token increase), its OCR excerpt
#: `documentData.documentOCRText` (~500 chars per document), the appeal /
#: interference decision bags, and the interference extra-party bag.
#: NOT the same list as documents._DOC_SLIM_FIELDS, deliberately: that one
#: slims a flattened document ROW in a PTAB_get_documents envelope, this one
#: slims a raw nested bag inside a *_complete search result, where the
#: identifier and URI fields are carried by the parent record.
_DOC_KEEP_FIELDS = (
    "documentIdentifier",
    "documentTitleText",
    "documentTypeDescriptionText",
    "documentCategory",
    "documentName",
    "documentFilingDate",
    "documentSizeQuantity",
    "filingPartyCategory",
    "pageCount",
)

_COMPLETE_BAG_SPECS = tuple(
    {
        "path": ["results", "*", bag],
        "keep_fields": _DOC_KEEP_FIELDS,
        "min_items": 10,
        "label": bag,
    }
    for bag in (
        "documentBag",
        "patentTrialDocumentBag",
        "appealDecisionDataBag",
        "interferenceDecisionDataBag",
        "additionalPartyDataBag",
    )
)

#: The paging block every search tool publishes
#: (util/search_runner.build_paging_block) and the record list it counts. The
#: guard rewrites that block when it drops records, so a trimmed page reports
#: what it carries: `returned` is the rows kept, `next_offset` is offset + rows
#: kept, `has_more` is true. Before this a 100-row page cut to 50 still said
#: `returned: 100, next_offset: 100`, and a caller paging by next_offset
#: skipped rows 50-99 without being told (found on the FPD sibling, 2026-09-11).
_SEARCH_PAGING = {"key": "paging", "path": ["results"]}

#: A bulk trial-number lookup fetches every supplied identifier and does not
#: use `offset` (search_trials_minimal forces it to 0 and says so in
#: `paging.note`), so there is no cursor to move: a trimmed bulk page corrects
#: `returned` and `has_more` and leaves `next_offset` null, and the recovery
#: note names the lever that does work.
_BULK_PAGING = {"key": "paging", "path": ["results"], "cursor": False}

_BULK_NOTE_TEMPLATE = (
    "Response exceeded the client response-size limit, so fewer records were "
    "returned than requested. A bulk trial-number lookup does not page by "
    "offset: re-call {tool} with fewer trial numbers (those after the last "
    "record returned) to retrieve the rest."
)

_SEARCH_NOTE_TEMPLATE = (
    "Response exceeded the client response-size limit, so fewer records were "
    "returned than requested. Re-call {tool} with a smaller limit= and page "
    "with offset= (the response's `paging.next_offset`) to retrieve the rest."
)

_COMPLETE_NOTE_TEMPLATE = (
    "Response exceeded the client response-size limit. The complete tier applies "
    "no field filtering at all (fields=['*']), so per-record document bags were "
    "slimmed to essential fields first (see `_bounds.slimmed_fields` — "
    "documentOCRText excerpts go first) and records were dropped only if that was "
    "not enough. Prefer {minimal_tool} or a targeted fields=[...] list, use "
    "PTAB_get_documents for document lists, and page with offset=."
)

_CONTENT_NOTE = (
    "Extracted content exceeded the content-size limit. Re-call "
    "PTAB_get_document_content(identifier=..., document_id=..., "
    "char_offset=<_window.next_offset>) to continue from where this window ended."
)

#: The registrar-level backstop for PTAB_get_documents shares its note text,
#: alias map, field whitelist and floor with the tool's own attach point in
#: tools/documents.py — SAME tool, so a caller must not see different text
#: depending on which of the two guards fired. This module used to keep its
#: own `_DOCUMENTS_NOTE` (same name, different words) and its own copy of the
#: alias map, and they had already drifted (D-5, R-7).
_DOCUMENTS_NOTE = documents._DOCUMENTS_NOTE
_DOCUMENT_ALIASES = documents._DOCUMENTS_ALIASES

_TOOL_BOUNDS: Dict[str, Dict[str, Any]] = {
    # ---- searches: minimal / balanced (already field-filtered) ----
    "PTAB_search_trials_minimal": {
        "bags": (_SEARCH_RECORDS_SPEC,),
        "note": _SEARCH_NOTE_TEMPLATE.format(tool="PTAB_search_trials_minimal"),
        "paging": _SEARCH_PAGING,
    },
    "PTAB_search_trials_balanced": {
        "bags": (_SEARCH_RECORDS_SPEC,),
        "note": _SEARCH_NOTE_TEMPLATE.format(tool="PTAB_search_trials_balanced"),
        "paging": _SEARCH_PAGING,
    },
    "PTAB_search_appeals_minimal": {
        "bags": (_SEARCH_RECORDS_SPEC,),
        "note": _SEARCH_NOTE_TEMPLATE.format(tool="PTAB_search_appeals_minimal"),
        "paging": _SEARCH_PAGING,
    },
    "PTAB_search_appeals_balanced": {
        "bags": (_SEARCH_RECORDS_SPEC,),
        "note": _SEARCH_NOTE_TEMPLATE.format(tool="PTAB_search_appeals_balanced"),
        "paging": _SEARCH_PAGING,
    },
    "PTAB_search_interferences_minimal": {
        "bags": (_SEARCH_RECORDS_SPEC,),
        "note": _SEARCH_NOTE_TEMPLATE.format(tool="PTAB_search_interferences_minimal"),
        "paging": _SEARCH_PAGING,
    },
    "PTAB_search_interferences_balanced": {
        "bags": (_SEARCH_RECORDS_SPEC,),
        "note": _SEARCH_NOTE_TEMPLATE.format(tool="PTAB_search_interferences_balanced"),
        "paging": _SEARCH_PAGING,
    },
    # ---- searches: complete (NO tier filtering — slim the bags first) ----
    "PTAB_search_trials_complete": {
        "bags": _COMPLETE_BAG_SPECS + (_SEARCH_RECORDS_SPEC,),
        "note": _COMPLETE_NOTE_TEMPLATE.format(
            minimal_tool="PTAB_search_trials_minimal"
        ),
        "paging": _SEARCH_PAGING,
    },
    "PTAB_search_appeals_complete": {
        "bags": _COMPLETE_BAG_SPECS + (_SEARCH_RECORDS_SPEC,),
        "note": _COMPLETE_NOTE_TEMPLATE.format(
            minimal_tool="PTAB_search_appeals_minimal"
        ),
        "paging": _SEARCH_PAGING,
    },
    "PTAB_search_interferences_complete": {
        "bags": _COMPLETE_BAG_SPECS + (_SEARCH_RECORDS_SPEC,),
        "note": _COMPLETE_NOTE_TEMPLATE.format(
            minimal_tool="PTAB_search_interferences_minimal"
        ),
        "paging": _SEARCH_PAGING,
    },
    # ---- documents ----
    "PTAB_get_documents": {
        "bags": (
            {
                "path": ["documents"],
                "keep_fields": documents._DOC_SLIM_FIELDS,
                "min_items": documents._DOCUMENTS_MIN_DOCS,
                "label": "documents",
            },
        ),
        "note": _DOCUMENTS_NOTE,
        "aliases": _DOCUMENT_ALIASES,
        # This backstop runs AFTER the tool built `paging` (the tool's own
        # guard runs before), so a trim here has to rewrite it too. offset +
        # rows kept is the right cursor in every documents mode: server rows
        # without a client-side filter, the match list for page_all and the
        # appeal / interference GET. `_sync_document_counters` keeps the
        # legacy `count` and top-level `next_offset` in step.
        "paging": {"key": "paging", "path": ["documents"]},
    },
    # The caller explicitly asked for document text, so the ceiling is the
    # higher content budget and the tool's own cursor (`_window`) has already
    # bounded it; this is the backstop against a pathological payload.
    "PTAB_get_document_content": {
        "bags": (),
        "budget": "content",
        "note": _CONTENT_NOTE,
    },
}

#: Anything not listed above (downloads, guidance, field configs, admin) gets
#: the plain response budget with the largest-free-text-field fallback, so
#: coverage is 100% without per-tool wiring.
_DEFAULT_BOUNDS: Dict[str, Any] = {"bags": ()}


def _for_payload(config: Dict[str, Any], payload: Dict[str, Any], tool_name: str) -> Dict[str, Any]:
    """The guard config for this particular response.

    A bulk trial-number lookup (`query_info.bulk_lookup`) does not page by
    offset, so its paging spec carries no cursor and its recovery note names
    the lever that does work. Everything else uses the tool's config as is.
    """
    query_info = payload.get("query_info")
    if "paging" in config and isinstance(query_info, dict) and query_info.get("bulk_lookup") is True:
        config = dict(config, paging=_BULK_PAGING, note=_BULK_NOTE_TEMPLATE.format(tool=tool_name))
    return config


def _sync_document_counters(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Keep PTAB_get_documents' legacy counters in step after a trim.

    The guard rewrites `paging` (and mirrors `returned_count` through the
    alias map) but not the legacy `count` or the top-level `next_offset` the
    tool keeps in lockstep with `paging.next_offset` for trials.
    """
    if response_bounds.BOUNDS_KEY not in payload:
        return payload
    docs = payload.get("documents")
    if isinstance(docs, list) and "count" in payload:
        payload["count"] = len(docs)
    paging = payload.get("paging")
    if isinstance(paging, dict) and payload.get("identifier_type") == "trial" and paging.get("has_more"):
        payload["next_offset"] = paging.get("next_offset")
    return payload


def _bound_result(result: Any, tool_name: str) -> Any:
    """Apply the shared guard to one tool result (dict or JSON string)."""
    config = dict(_TOOL_BOUNDS.get(tool_name) or _DEFAULT_BOUNDS)
    budget = config.pop("budget", "response")
    config.setdefault("text_fallback", True)
    config["limit"] = (
        response_bounds.content_char_budget()
        if budget == "content"
        else response_bounds.response_char_budget()
    )
    post = _sync_document_counters if tool_name == "PTAB_get_documents" else None

    if isinstance(result, dict):
        bounded = response_bounds.bound_structured_response(
            result, **_for_payload(config, result, tool_name)
        )
        return post(bounded) if post else bounded

    if isinstance(result, str) and result.lstrip().startswith("{"):
        try:
            parsed = json.loads(result)
        except ValueError:
            return result
        if not isinstance(parsed, dict):
            return result
        bounded = response_bounds.bound_structured_response(
            parsed, **_for_payload(config, parsed, tool_name)
        )
        if response_bounds.BOUNDS_KEY not in bounded:
            return result  # no-op: hand back the original string byte-for-byte
        return json.dumps(post(bounded) if post else bounded, default=str)

    return result


def _guard(fn, tool_name: str):
    """Wrap a tool function so its response passes through the guard.

    The signature is preserved (both via functools.wraps' ``__wrapped__`` and
    an explicit ``__signature__``) so FastMCP derives the same input schema it
    would from the unwrapped function.
    """
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            return _bound_result(await fn(*args, **kwargs), tool_name)
    else:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return _bound_result(fn(*args, **kwargs), tool_name)

    try:
        wrapper.__signature__ = inspect.signature(fn)
    except (TypeError, ValueError):  # pragma: no cover - builtins only
        pass
    return wrapper


class _BoundedRegistrar:
    """Thin proxy over the FastMCP object that guards every registered tool.

    Only ``.tool(...)`` is intercepted; every other attribute (resources,
    templates, custom routes, run) passes straight through to the real object.
    Handles both the decorator form (``@mcp.tool(name=...)``) and PTAB's
    imperative form (``mcp.tool(name=...)(fn)``).
    """

    def __init__(self, mcp) -> None:
        self._mcp = mcp
        #: Every tool name this registrar actually saw, so register_all can
        #: prove each _TOOL_BOUNDS key matched one.
        self.seen_names: set = set()

    def __getattr__(self, name):
        return getattr(self._mcp, name)

    def tool(self, *args, **kwargs):
        if args and callable(args[0]):  # bare @mcp.tool usage
            fn = args[0]
            name = kwargs.get("name") or getattr(fn, "__name__", "")
            self.seen_names.add(name)
            return self._mcp.tool(_guard(fn, name), *args[1:], **kwargs)

        decorator = self._mcp.tool(*args, **kwargs)

        def register_guarded(fn):
            name = kwargs.get("name") or getattr(fn, "__name__", "")
            self.seen_names.add(name)
            return decorator(_guard(fn, name))

        return register_guarded


def register_all(mcp, auth_provider=None) -> None:
    bounded = _BoundedRegistrar(mcp)
    admin.register(bounded, auth_provider)
    trials.register(bounded)
    documents.register(bounded)
    appeals.register(bounded)
    interferences.register(bounded)
    guidance.register(bounded)

    # A _TOOL_BOUNDS key that matches no registered tool means that tool
    # silently fell back to _DEFAULT_BOUNDS: the *_complete tiers pass
    # fields: ["*"], which short-circuits tier filtering entirely, so losing
    # their bag-slimming spec makes the guard drop whole records instead of
    # slimming document bags. Nothing failed; the response just got worse.
    # Fail startup instead, the way main.py does for the admin scope gate.
    #
    # ptab_manage_users is registration-gated, so an absent admin tool is
    # expected rather than a mismatch.
    unknown = {
        name for name in _TOOL_BOUNDS
        if name not in bounded.seen_names and name != "ptab_manage_users"
    }
    if unknown:
        raise RuntimeError(
            "_TOOL_BOUNDS keys match no registered tool "
            f"(renamed at the registration site?): {sorted(unknown)}"
        )
