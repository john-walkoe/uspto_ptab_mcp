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


def format_error_response(
    message: str,
    status_code: int = 500,
    request_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    include_details: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Format error response in consistent structure with sensitive data filtering

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
        if status_code == 401:
            safe_message = "Authentication required"
        elif status_code == 403:
            safe_message = "Access denied"
        elif status_code == 429:
            safe_message = "Rate limit exceeded"
        elif status_code >= 500:
            safe_message = "Internal server error occurred"
        elif "api" in message.lower() and "key" in message.lower():
            safe_message = "Configuration error"
        elif "timeout" in message.lower():
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
