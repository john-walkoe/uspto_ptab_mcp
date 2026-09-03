"""
Shared error handling utilities for consistent error responses across the application
"""

import os
from typing import Dict, Any, Optional
import uuid
from .log_sanitizer import LogSanitizer
from .safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


def generate_request_id() -> str:
    """Generate a unique request ID for tracking"""
    return str(uuid.uuid4())[:8]


#: Generic replacements used in production so an upstream body is not echoed.
#: A dict rather than the if/elif ladder this used to be, which was the entire
#: reason format_error_response tripped the repo's C901 gate (F-8).
_GENERIC_BY_STATUS = {
    401: "Authentication required",
    403: "Access denied",
    429: "Rate limit exceeded",
}


def build_api_error(
    message: str,
    status_code: int = 500,
    request_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    include_details: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Build the API-layer error envelope, with sensitive data filtered.

    Renamed from `format_error_response` (R-1): `util/response_formatter` has a
    function of that name which returns a JSON STRING with `"error": True`,
    while this one returns a DICT whose `"error"` is the message string. A
    reader following the name from a tool body into the client layer landed on
    a function with the same name and incompatible semantics.

    Args:
        message: Error message
        status_code: HTTP status code
        request_id: Request identifier for tracing (optional)
        context: Additional context for debugging (optional)
        include_details: Whether to include detailed error info (auto-detected from env if None)

    Returns:
        Dict containing structured error response
    """
    # Determine if we should include detailed error information
    if include_details is None:
        environment = os.getenv("ENVIRONMENT", "production").lower()
        include_details = environment in ["development", "dev", "test"]

    # Always sanitize the message to remove sensitive data
    sanitizer = LogSanitizer()
    safe_message = sanitizer.sanitize_string(message)

    # In production, provide generic messages for certain error types
    if not include_details:
        lowered = message.lower()
        if status_code in _GENERIC_BY_STATUS:
            safe_message = _GENERIC_BY_STATUS[status_code]
        elif status_code >= 500:
            safe_message = "Internal server error occurred"
        elif "api" in lowered and "key" in lowered:
            safe_message = "Configuration error"
        elif "timeout" in lowered:
            safe_message = "Service temporarily unavailable"

    response = {
        "error": safe_message,
        "status_code": status_code,
        "success": False
    }

    if request_id:
        response["request_id"] = request_id

    # Only include context in development/test environments
    if context and include_details:
        response["context"] = sanitizer.sanitize_for_json(context)

    return response


def sanitize_error_message(message: str) -> str:
    """
    Sanitize error message to remove potentially sensitive information.

    Args:
        message: Original error message

    Returns:
        Sanitized error message safe for external consumption
    """
    sanitizer = LogSanitizer()
    return sanitizer.sanitize_string(message)


#: Deprecated alias. `util/response_formatter.format_error_response` returns a
#: JSON string with `"error": True`; this one returns a dict whose `"error"` is
#: the message. Kept for one release so an out-of-repo importer does not break.
format_error_response = build_api_error
