"""
Shared error handling utilities for consistent error responses across the application
"""

import os
import logging
from typing import Dict, Any, Optional, Callable
from functools import wraps
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


class FPDException(Exception):
    """Base exception for FPD application"""
    def __init__(self, message: str, status_code: int = 500, request_id: Optional[str] = None):
        self.message = message
        self.status_code = status_code
        self.request_id = request_id
        super().__init__(self.message)


class ValidationError(FPDException):
    """Validation error (400)"""
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(message, 400, request_id)


class NotFoundError(FPDException):
    """Resource not found error (404)"""
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(message, 404, request_id)


class RateLimitError(FPDException):
    """Rate limit exceeded error (429)"""
    def __init__(self, message: str, retry_after: int, request_id: Optional[str] = None):
        super().__init__(message, 429, request_id)
        self.retry_after = retry_after


class APIError(FPDException):
    """External API error"""
    def __init__(self, message: str, status_code: int = 502, request_id: Optional[str] = None):
        super().__init__(message, status_code, request_id)


class AuthenticationError(FPDException):
    """Authentication error (401)"""
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(message, 401, request_id)


class AuthorizationError(FPDException):
    """Authorization error (403)"""
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(message, 403, request_id)


class BadRequestError(FPDException):
    """Bad request error (400)"""
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(message, 400, request_id)


def async_tool_error_handler(tool_name: str):
    """
    Decorator for consistent async tool error handling.

    Eliminates duplicated try/except blocks across MCP tools by providing
    centralized error handling for common exception types.

    Handles:
    - ValidationError (400) - Custom validation errors
    - ValueError (400) - Legacy validation errors (should migrate to ValidationError)
    - httpx.HTTPStatusError - API errors with original status code
    - httpx.TimeoutException (408) - Request timeouts
    - Exception (500) - Unexpected errors with full logging

    Usage:
        @mcp.tool(name="My_Tool")
        @async_tool_error_handler("my_tool")
        async def my_tool(...) -> Dict[str, Any]:
            # Tool logic - no try/except needed
            if invalid:
                raise ValidationError("Invalid input", generate_request_id())
            return await api_client.do_something()

    Args:
        tool_name: Tool name for logging (e.g., "minimal_search")

    Returns:
        Decorator function that wraps async tool functions
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Dict[str, Any]:
            try:
                return await func(*args, **kwargs)

            except ValidationError as e:
                logger.warning(f"Validation error in {tool_name}: {str(e)}")
                return format_error_response(str(e), 400, e.request_id)

            except ValueError as e:
                # Legacy ValueError for validation - should migrate to ValidationError
                logger.warning(f"Validation error in {tool_name}: {str(e)}")
                return format_error_response(str(e), 400)

            except Exception as e:
                # Check if httpx is available and handle HTTP errors
                error_type = type(e).__name__

                if error_type == "HTTPStatusError":
                    # httpx.HTTPStatusError - preserve original status code
                    status_code = getattr(e, "response", None)
                    if status_code:
                        status_code = getattr(status_code, "status_code", 502)
                        response_text = getattr(getattr(e, "response", None), "text", str(e))
                        logger.error(f"API error in {tool_name}: {status_code} - {response_text}")
                        return format_error_response(f"API error: {response_text}", status_code)
                    else:
                        logger.error(f"API error in {tool_name}: {str(e)}")
                        return format_error_response(f"API error: {str(e)}", 502)

                elif error_type == "TimeoutException":
                    # httpx.TimeoutException - request timeout
                    logger.error(f"API timeout in {tool_name}: {str(e)}")
                    return format_error_response("Request timeout - please try again", 408)

                else:
                    # Unexpected error - log with full traceback
                    logger.error(f"Unexpected error in {tool_name}: {str(e)}", exc_info=True)
                    return format_error_response(f"Internal error: {str(e)}", 500)

        return wrapper
    return decorator
