"""Shared execution skeleton for the nine proceeding search tools (dup §2.1).

Every search_{trials,appeals,interferences}_{minimal,balanced,complete} tool
follows the same control flow after its per-tool validation and
FilterBuilder step: resolve the field selection -> call the client's search
endpoint -> pass API errors through -> field-filter the response -> format.
That skeleton lives here once; each tool body keeps only its own signature,
docstring, validation, and filter construction.
"""

import functools
import json
from typing import Any, Dict, List, Optional, Tuple

from ..shared.safe_logger import get_safe_logger
from ..validation.validators import validate_custom_fields
from .response_formatter import (
    create_query_info,
    format_error_response,
    format_proceeding_response,
)

logger = get_safe_logger(__name__)

# proceeding -> (results bag key, PTABClient search method name)
SEARCH_TOOL_CONFIG: Dict[str, Tuple[str, str]] = {
    "trials": ("patentTrialProceedingDataBag", "search_trials"),
    "appeals": ("patentAppealDataBag", "search_appeals"),
    "interferences": ("patentInterferenceDataBag", "search_interferences"),
}


def mcp_tool_error_envelope(fn):
    """Standard tool error envelope (dup §3.1).

    Replaces the hand-rolled two-clause try/except that every search tool
    carried (with the tool name maintained by hand in each copy).
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ValueError as e:
            return format_error_response(str(e), "VALIDATION_ERROR")
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
    extra_query_info: Optional[Dict[str, Any]] = None,
    raw_response: Optional[Dict[str, Any]] = None,
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
        extra_query_info: Extra keys merged into query_info (bulk lookups)
        raw_response: Pre-fetched API response (bulk auto-chunking) — skips
            the API call when provided.
    """
    results_key, search_method = SEARCH_TOOL_CONFIG[proceeding]

    fields, field_list, field_set_name = resolve_field_selection(
        field_manager, proceeding, tier, fields
    )

    if raw_response is None:
        raw_response = await getattr(client, search_method)(
            filters=filters if filters else None,
            range_filters=range_filters if range_filters else None,
            pagination={"offset": 0, "limit": limit},
            fields=field_list,
        )

    # Pass API errors through untouched
    if raw_response.get("error"):
        return json.dumps(raw_response, indent=2)

    if fields:
        filtered_response = field_manager.filter_response_custom(raw_response, fields)
    else:
        filtered_response = field_manager.filter_response(raw_response, field_set_name)

    return format_proceeding_response(
        proceeding,
        filtered_response.get(results_key, []),
        query_info=create_query_info(
            filters=filters,
            range_filters=range_filters,
            pagination={"offset": 0, "limit": limit},
            **(extra_query_info or {}),
        ),
        field_set=field_set_name,
        context_info=filtered_response.get("context_info"),
        count=filtered_response.get("count", 0),
    )
