"""
Response Formatters for PTAB MCP

Formats API responses with metadata, query information, and context reduction metrics.
Provides professional JSON output for trials, appeals, and interferences.
"""

import json
from typing import Dict, List, Any, Literal, Optional
from datetime import datetime, timezone

# Compact serialization (indent=None, default separators) — the response guard
# in shared/response_bounds.py measures len(json.dumps(payload)) with no
# indent, so emitting indent=2 re-inflated a guarded payload by 25-40% of pure
# whitespace after it had been certified as fitting the client's cap. Every
# consumer parses these strings, so the indentation bought nothing.
JSON_INDENT = None

# Known error categories (EH-6). A Literal so a typo'd error_type at a call
# site is visible to type checkers instead of silently minting a new category.
ErrorType = Literal[
    "VALIDATION_ERROR",
    "API_ERROR",
    "RATE_LIMIT_ERROR",
    "TIMEOUT_ERROR",
    "INTERNAL_ERROR",
    "GUIDANCE_ERROR",
    "CONFIG_ERROR",
]


def format_proceeding_response(
    data_type: str,
    results: List[Dict],
    query_info: Dict[str, Any],
    field_set: str,
    context_info: Optional[Dict[str, Any]] = None,
    count: Optional[int] = None,
    note: Optional[str] = None,
    paging: Optional[Dict[str, Any]] = None,
    field_set_fallback: bool = False,
    field_set_fallback_note: Optional[str] = None,
) -> str:
    """
    Format a proceeding search response with metadata (dedup 1.3).

    One implementation behind format_trial/appeal/interference_response —
    the three were byte-identical apart from the data_type literal.

    Args:
        data_type: "trials" | "appeals" | "interferences"
        results: List of proceeding records
        query_info: Query parameters used for the search
        field_set: Field set name used (e.g., 'trials_minimal')
        context_info: Context reduction metadata from FieldManager
        count: Total count of results
        note: Optional advisory note (e.g. no-matches guidance) surfaced
            alongside an otherwise-normal empty result
        paging: The limit ACTUALLY applied plus the offset/returned/total/
            has_more/next_offset cursor. `count` is the API's TOTAL match
            count, not the size of this page — without this block a 50-row
            page beside `count: 4312` read as 4312 delivered records.
        field_set_fallback: True when FieldManager is serving the built-in
            emergency field sets because field_configs.yaml failed to load.
            The `field_set` label is identical either way, so the flag is the
            only thing distinguishing a 6-field response from the real one.
        field_set_fallback_note: Human-readable explanation of that fallback.

    Returns:
        Formatted JSON string
    """
    response = {
        "data_type": data_type,
        "query_info": query_info,
        "field_set": field_set,
        "count": count if count is not None else len(results),
        "results": results,
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    }

    if paging:
        response["paging"] = paging

    if field_set_fallback:
        response["field_set_fallback"] = True
        if field_set_fallback_note:
            response["field_set_fallback_note"] = field_set_fallback_note

    if note:
        response["note"] = note

    # Configured fields that no returned record carried. Reported rather than
    # left silent: the field filter can only return what the API sent, so a
    # configured-but-absent path used to vanish without a trace (that is how
    # appeals_minimal served 4 of its 9 configured fields unnoticed).
    if context_info and context_info.get("fields_absent"):
        from ..config.field_manager import FieldManager

        response["fields_absent"] = {
            "fields": context_info["fields_absent"],
            "note": FieldManager.FIELDS_ABSENT_NOTE,
        }

    # Add context reduction info if available
    if context_info:
        response["context_reduction"] = {
            "field_set": context_info.get("field_set", field_set),
            "fields_configured": context_info.get("fields_configured", 0),
            "fields_expanded": context_info.get("fields_expanded", 0),
            "original_field_count": context_info.get("original_field_count", 0),
            "filtered_field_count": context_info.get("filtered_field_count", 0),
            "reduction_percentage": context_info.get("context_reduction", "N/A")
        }

    return json.dumps(response, indent=JSON_INDENT, ensure_ascii=False)





def build_document_list(
    documents: List[Dict],
    identifier: str,
    identifier_type: str,
    count: Optional[int] = None
) -> Dict[str, Any]:
    """
    Build the document list envelope as a dict.

    The only caller of `format_document_list` serialized this and immediately
    parsed it back to keep annotating it, which mixed a serialization detail
    into the middle of the tool body (Q-2).

    Args:
        documents: List of document metadata records
        identifier: Trial/appeal/interference identifier
        identifier_type: Type of identifier (trial_number, appeal_number, etc.)
        count: Total count of documents

    Returns:
        Document list envelope
    """
    return {
        "data_type": "documents",
        "identifier": identifier,
        "identifier_type": identifier_type,
        "count": count if count is not None else len(documents),
        "documents": documents,
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    }


def format_document_list(
    documents: List[Dict],
    identifier: str,
    identifier_type: str,
    count: Optional[int] = None
) -> str:
    """Serialize build_document_list(). Kept for out-of-repo importers."""
    return json.dumps(
        build_document_list(documents, identifier, identifier_type, count),
        indent=JSON_INDENT, ensure_ascii=False,
    )


def format_error_response(
    error_message: str,
    error_type: ErrorType = "API_ERROR",
    details: Optional[Dict[str, Any]] = None
) -> str:
    """
    Format error response with details.

    The message passes through the log sanitizer (EH-1): raw exception
    strings can embed URLs with keys/tokens/link hashes, and this formatter
    is the last stop before the text reaches the MCP client.

    Args:
        error_message: Human-readable error message
        error_type: Error type/category
        details: Additional error details

    Returns:
        Formatted JSON string
    """
    from ..shared.error_utils import sanitize_error_message

    response = {
        "error": True,
        "error_type": error_type,
        "message": sanitize_error_message(error_message),
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    }

    if details:
        response["details"] = details

    return json.dumps(response, indent=JSON_INDENT, ensure_ascii=False)


#: The API layer's status -> the tool surface's error category. Without this
#: the API client's envelope (shape A: "error" is the MESSAGE, plus
#: status_code/success) reached the caller verbatim while every other tool exit
#: produced shape B ("error" is True, plus error_type/message/timestamp). A
#: consumer testing resp["error"] got a string on one path and True on the other.
_STATUS_TO_ERROR_TYPE = {
    400: "VALIDATION_ERROR",
    401: "API_ERROR",
    403: "API_ERROR",
    404: "API_ERROR",
    408: "TIMEOUT_ERROR",
    429: "RATE_LIMIT_ERROR",
    503: "API_ERROR",
}


def from_api_envelope(api_error: Dict[str, Any]) -> str:
    """Translate an api/ptab_client error dict into the tool error envelope."""
    status_code = api_error.get("status_code", 500)
    return format_error_response(
        str(api_error.get("error", "Upstream error")),
        _STATUS_TO_ERROR_TYPE.get(status_code, "API_ERROR"),
        details={
            "status_code": status_code,
            "request_id": api_error.get("request_id"),
        },
    )



def create_query_info(
    filters: Optional[List[Dict]] = None,
    range_filters: Optional[List[Dict]] = None,
    pagination: Optional[Dict] = None,
    sort: Optional[List[Dict]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Create query info object from search parameters.

    Args:
        filters: Filter criteria used
        range_filters: Range filter criteria used
        pagination: Pagination parameters
        sort: Sort parameters
        **kwargs: Additional query parameters

    Returns:
        Query info dictionary
    """
    query_info = {}

    if filters:
        query_info["filters"] = filters

    if range_filters:
        query_info["range_filters"] = range_filters

    if pagination:
        query_info["pagination"] = pagination

    if sort:
        query_info["sort"] = sort

    # Add any additional parameters
    for key, value in kwargs.items():
        if value is not None:
            query_info[key] = value

    return query_info
