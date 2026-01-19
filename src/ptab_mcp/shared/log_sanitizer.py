"""
Log Sanitization Module for Security

Provides sanitization functions to prevent log injection attacks and protect
sensitive data from being exposed in log outputs.
"""

import html
import json
import re
from typing import Any, Dict, List, Union


class LogSanitizer:
    """Sanitizer for log injection protection and sensitive data filtering."""

    # Sensitive HTTP header keys to remove
    SENSITIVE_HEADER_KEYS = [
        'X-API-KEY', 'x-api-key',
        'Authorization', 'authorization',
        'API-KEY', 'api-key',
        'Bearer', 'bearer',
        'Token', 'token',
        'X-Auth-Token', 'x-auth-token'
    ]

    # Patterns for detecting and masking sensitive data
    SENSITIVE_PATTERNS = [
        # USPTO API Keys (exactly 30 lowercase letters)
        (r'\b([a-z]{30})\b', r'[USPTO_API_KEY]'),

        # Mistral API Keys (exactly 32 alphanumeric characters)
        (r'\b([A-Za-z0-9]{32})\b', r'[MISTRAL_API_KEY]'),

        # Generic API keys with prefixes (sk_live_, pk_test_, etc.)
        (r'(?:sk|pk)_(?:live|test)_[a-zA-Z0-9]{10,}', r'[API_KEY]'),
        # Single prefix API keys (sk_, pk_, live_, test_)
        (r'(?:sk|pk|live|test)_[a-zA-Z0-9]{10,}', r'[API_KEY]'),

        # API keys and tokens in structured format
        (r'(api[_-]?key["\s:=]+)([a-zA-Z0-9]{20,})', r'\1[API_KEY]'),
        (r'(token["\s:=]+)([a-zA-Z0-9]{20,})', r'\1[TOKEN]'),
        (r'(bearer\s+)([a-zA-Z0-9]{20,})', r'\1[TOKEN]'),

        # Passwords and credentials
        (r'(password["\s:=]+)([^"\s]{8,})', r'\1[REDACTED]'),
        (r'(pwd["\s:=]+)([^"\s]{8,})', r'\1[REDACTED]'),
        (r'(secret["\s:=]+)([^"\s]{8,})', r'\1[REDACTED]'),

        # Email addresses (partial masking)
        (r'([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', r'\1[...]@\2'),

        # IP addresses (partial masking for privacy)
        (r'(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})', r'\1.\2.[XXX].[XXX]'),
    ]

    # Control characters to remove (except common ones like \n, \t)
    CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]')

    # Log injection patterns to neutralize
    LOG_INJECTION_PATTERNS = [
        # Newline-based injection attempts
        r'[\r\n]',
        # Tab injection attempts
        r'\t',
        # ANSI escape sequences
        r'\x1b\[[0-9;]*[a-zA-Z]',
        # Other terminal escape sequences
        r'\x1b[()[\]#;?]*[0-9]*[a-zA-Z@]'
    ]

    @classmethod
    def sanitize_for_json(cls, obj: Any) -> Any:
        """
        Recursively sanitize data for safe JSON logging.

        Args:
            obj: Object to sanitize (can be dict, list, string, etc.)

        Returns:
            Sanitized object safe for JSON logging
        """
        if isinstance(obj, dict):
            return {key: cls.sanitize_for_json(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [cls.sanitize_for_json(item) for item in obj]
        elif isinstance(obj, str):
            return cls.sanitize_string(obj)
        else:
            # For non-string types, convert to string and sanitize
            if obj is None:
                return obj
            return cls.sanitize_string(str(obj))

    @classmethod
    def sanitize_string(cls, text: str, max_length: int = 1000) -> str:
        """
        Sanitize a string for safe logging.

        Args:
            text: String to sanitize
            max_length: Maximum length for output (prevents log flooding)

        Returns:
            Sanitized string safe for logging
        """
        if not isinstance(text, str):
            text = str(text)

        # Truncate if too long
        if len(text) > max_length:
            text = text[:max_length] + "...[TRUNCATED]"

        # Remove control characters (except newlines and tabs in controlled way)
        text = cls.CONTROL_CHAR_PATTERN.sub('', text)

        # Neutralize log injection attempts
        for pattern in cls.LOG_INJECTION_PATTERNS:
            text = re.sub(pattern, '[FILTERED]', text)

        # Filter sensitive data
        for pattern, replacement in cls.SENSITIVE_PATTERNS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        # HTML encode any remaining problematic characters
        text = html.escape(text, quote=False)  # Don't escape quotes in logs

        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    @classmethod
    def sanitize_for_text_log(cls, text: str) -> str:
        """
        Sanitize text for plain text logging (non-JSON).

        Args:
            text: Text to sanitize

        Returns:
            Sanitized text safe for plain text logs
        """
        sanitized = cls.sanitize_string(text)

        # Additional protection for plain text logs - escape newlines
        sanitized = sanitized.replace('\n', '\\n').replace('\r', '\\r')

        return sanitized

    @classmethod
    def create_safe_log_entry(cls, message: str, **kwargs) -> Dict[str, Any]:
        """
        Create a safe log entry with sanitized data.

        Args:
            message: Log message
            **kwargs: Additional log data

        Returns:
            Sanitized log entry dictionary
        """
        # Sanitize the message
        safe_message = cls.sanitize_string(message)

        # Sanitize all kwargs
        safe_kwargs = cls.sanitize_for_json(kwargs)

        return {
            "message": safe_message,
            **safe_kwargs
        }

    @classmethod
    def validate_json_safe(cls, obj: Any) -> bool:
        """
        Validate that an object is safe for JSON serialization.

        Args:
            obj: Object to validate

        Returns:
            True if safe for JSON serialization
        """
        try:
            # Try to serialize - if it fails, it's not safe
            json.dumps(obj)
            return True
        except (TypeError, ValueError, OverflowError):
            return False

    @classmethod
    def sanitize_headers(cls, headers: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove sensitive headers from HTTP headers dictionary.

        This method creates a sanitized copy of the headers dict with
        sensitive authentication and API key headers removed.

        Args:
            headers: Dictionary of HTTP headers to sanitize

        Returns:
            Sanitized copy of headers with sensitive keys removed

        Example:
            >>> headers = {"Content-Type": "application/json", "X-API-KEY": "secret123"}
            >>> safe_headers = LogSanitizer.sanitize_headers(headers)
            >>> print(safe_headers)
            {'Content-Type': 'application/json'}
        """
        sanitized = headers.copy()
        for key in cls.SENSITIVE_HEADER_KEYS:
            sanitized.pop(key, None)
        return sanitized

    @classmethod
    def get_sanitization_stats(cls, original: str, sanitized: str) -> Dict[str, Any]:
        """
        Get statistics about what was sanitized (for debugging).

        Args:
            original: Original string
            sanitized: Sanitized string

        Returns:
            Dictionary with sanitization statistics
        """
        stats = {
            "original_length": len(original),
            "sanitized_length": len(sanitized),
            "characters_removed": len(original) - len(sanitized),
            "redacted_patterns": 0,
            "control_chars_removed": 0,
            "truncated": "[TRUNCATED]" in sanitized
        }

        # Count redacted patterns
        for pattern, replacement in cls.SENSITIVE_PATTERNS:
            if "[REDACTED]" in replacement:
                matches = len(re.findall(pattern, original, flags=re.IGNORECASE))
                stats["redacted_patterns"] += matches

        # Count control characters
        control_matches = cls.CONTROL_CHAR_PATTERN.findall(original)
        stats["control_chars_removed"] = len(control_matches)

        return stats


class SecureStructuredLogger:
    """
    Enhanced structured logger with automatic sanitization.

    This is a wrapper around the standard StructuredLogger that automatically
    sanitizes all log data to prevent injection attacks and sensitive data exposure.
    """

    def __init__(self, logger_instance):
        """
        Initialize secure logger wrapper.

        Args:
            logger_instance: Existing StructuredLogger instance to wrap
        """
        self.logger = logger_instance
        self.sanitizer = LogSanitizer()

    def _sanitize_log_args(self, message: str, **kwargs) -> tuple:
        """Sanitize message and kwargs for safe logging."""
        safe_message = self.sanitizer.sanitize_string(message)
        safe_kwargs = self.sanitizer.sanitize_for_json(kwargs)
        return safe_message, safe_kwargs

    def log_api_request(self, method: str, endpoint: str, request_id: str, **kwargs):
        """Log API request with sanitization."""
        safe_message = f"{method} {endpoint}"
        safe_message, safe_kwargs = self._sanitize_log_args(safe_message,
                                                           request_id=request_id,
                                                           method=method,
                                                           endpoint=endpoint,
                                                           **kwargs)
        self.logger.log_api_request(method, endpoint, request_id, **safe_kwargs)

    def log_security_event(self, event_description: str, **kwargs):
        """Log security event with sanitization."""
        safe_description, safe_kwargs = self._sanitize_log_args(event_description, **kwargs)
        self.logger.log_security_event(safe_description, **safe_kwargs)

    def log_error(self, error_message: str, **kwargs):
        """Log error with sanitization."""
        safe_message, safe_kwargs = self._sanitize_log_args(error_message, **kwargs)
        self.logger.log_error(safe_message, **safe_kwargs)

    def log_validation_error(self, field_name: str, field_value: Any, validation_rule: str, error_message: str):
        """Log validation error with sanitization."""
        safe_field_value = self.sanitizer.sanitize_string(str(field_value))
        safe_message, safe_kwargs = self._sanitize_log_args(error_message,
                                                           field_name=field_name,
                                                           field_value=safe_field_value,
                                                           validation_rule=validation_rule)
        self.logger.log_validation_error(field_name, safe_field_value, validation_rule, safe_message)

    def __getattr__(self, name):
        """Delegate other methods to the wrapped logger with basic sanitization."""
        if hasattr(self.logger, name):
            original_method = getattr(self.logger, name)
            if callable(original_method):
                def sanitized_wrapper(*args, **kwargs):
                    # Basic sanitization for other methods
                    safe_args = [self.sanitizer.sanitize_string(str(arg)) if isinstance(arg, str) else arg for arg in args]
                    safe_kwargs = self.sanitizer.sanitize_for_json(kwargs)
                    return original_method(*safe_args, **safe_kwargs)
                return sanitized_wrapper
            else:
                return original_method
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
