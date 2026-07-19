"""
Response Formatters for PTAB MCP

Formats API responses with metadata, query information, and context reduction metrics.
Provides professional JSON output for trials, appeals, and interferences.
"""

import json
from typing import Dict, List, Any, Literal, Optional
from datetime import datetime, timezone

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
    count: Optional[int] = None
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

    return json.dumps(response, indent=2, ensure_ascii=False)


def format_trial_response(
    trials: List[Dict],
    query_info: Dict[str, Any],
    field_set: str,
    context_info: Optional[Dict[str, Any]] = None,
    count: Optional[int] = None
) -> str:
    """Format trial proceeding response with metadata."""
    return format_proceeding_response(
        "trials", trials, query_info, field_set, context_info, count
    )


def format_appeal_response(
    appeals: List[Dict],
    query_info: Dict[str, Any],
    field_set: str,
    context_info: Optional[Dict[str, Any]] = None,
    count: Optional[int] = None
) -> str:
    """Format appeal decision response with metadata."""
    return format_proceeding_response(
        "appeals", appeals, query_info, field_set, context_info, count
    )


def format_interference_response(
    interferences: List[Dict],
    query_info: Dict[str, Any],
    field_set: str,
    context_info: Optional[Dict[str, Any]] = None,
    count: Optional[int] = None
) -> str:
    """Format interference proceeding response with metadata."""
    return format_proceeding_response(
        "interferences", interferences, query_info, field_set, context_info, count
    )


def format_document_list(
    documents: List[Dict],
    identifier: str,
    identifier_type: str,
    count: Optional[int] = None
) -> str:
    """
    Format document list response.

    Args:
        documents: List of document metadata records
        identifier: Trial/appeal/interference identifier
        identifier_type: Type of identifier (trial_number, appeal_number, etc.)
        count: Total count of documents

    Returns:
        Formatted JSON string
    """
    response = {
        "data_type": "documents",
        "identifier": identifier,
        "identifier_type": identifier_type,
        "count": count if count is not None else len(documents),
        "documents": documents,
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    }

    return json.dumps(response, indent=2, ensure_ascii=False)


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

    return json.dumps(response, indent=2, ensure_ascii=False)


def format_context_reduction_summary(
    field_set: str,
    original_size: int,
    filtered_size: int,
    field_count_original: int,
    field_count_filtered: int
) -> str:
    """
    Format context reduction summary for reporting.

    Args:
        field_set: Field set name
        original_size: Original data size in characters
        filtered_size: Filtered data size in characters
        field_count_original: Original field count
        field_count_filtered: Filtered field count

    Returns:
        Formatted summary string
    """
    if original_size == 0:
        reduction_pct = 0.0
    else:
        reduction_pct = ((original_size - filtered_size) / original_size) * 100

    summary = {
        "field_set": field_set,
        "context_reduction": {
            "percentage": f"{reduction_pct:.1f}%",
            "original_size_chars": original_size,
            "filtered_size_chars": filtered_size,
            "bytes_saved": original_size - filtered_size
        },
        "field_reduction": {
            "original_fields": field_count_original,
            "filtered_fields": field_count_filtered,
            "fields_removed": field_count_original - field_count_filtered,
            "percentage": f"{((field_count_original - field_count_filtered) / field_count_original * 100):.1f}%" if field_count_original > 0 else "0%"
        }
    }

    return json.dumps(summary, indent=2, ensure_ascii=False)


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
