"""Safe logging wrapper with automatic sanitization.

This module provides a logging wrapper that automatically sanitizes all log messages
using the LogSanitizer class to prevent sensitive data exposure and log injection attacks.

Security Features:
- Automatic sanitization of API keys, tokens, passwords
- Log injection prevention (ANSI escapes, control characters)
- Consistent application of security controls across all logging statements

Usage:
    from ptab_mcp.shared.safe_logger import get_safe_logger

    logger = get_safe_logger(__name__)
    logger.error(f"API error: {exception_message}")  # Automatically sanitized
"""

from typing import Any
import logging
from .log_sanitizer import LogSanitizer


class SafeLogger:
    """Logger wrapper that automatically sanitizes all output.

    This wrapper ensures that all log messages are passed through LogSanitizer
    before being written to logs, preventing sensitive data exposure.

    Attributes:
        logger: The underlying Python logger instance
        sanitizer: LogSanitizer instance for cleaning log messages
    """

    def __init__(self, logger: logging.Logger):
        """Initialize SafeLogger with an underlying logger.

        Args:
            logger: Python logger instance to wrap
        """
        self.logger = logger
        self.sanitizer = LogSanitizer()

    def _sanitize(self, message: Any) -> str:
        """Sanitize message before logging.

        Args:
            message: Message to sanitize (will be converted to string)

        Returns:
            Sanitized message string
        """
        return self.sanitizer.sanitize_string(str(message))

    def debug(self, message: Any, *args, **kwargs):
        """Log debug message with automatic sanitization.

        Args:
            message: Message to log (will be sanitized)
            *args: Additional positional arguments for logger
            **kwargs: Additional keyword arguments for logger
        """
        self.logger.debug(self._sanitize(message), *args, **kwargs)

    def info(self, message: Any, *args, **kwargs):
        """Log info message with automatic sanitization.

        Args:
            message: Message to log (will be sanitized)
            *args: Additional positional arguments for logger
            **kwargs: Additional keyword arguments for logger
        """
        self.logger.info(self._sanitize(message), *args, **kwargs)

    def warning(self, message: Any, *args, **kwargs):
        """Log warning message with automatic sanitization.

        Args:
            message: Message to log (will be sanitized)
            *args: Additional positional arguments for logger
            **kwargs: Additional keyword arguments for logger
        """
        self.logger.warning(self._sanitize(message), *args, **kwargs)

    def error(self, message: Any, *args, **kwargs):
        """Log error message with automatic sanitization.

        Args:
            message: Message to log (will be sanitized)
            *args: Additional positional arguments for logger
            **kwargs: Additional keyword arguments for logger
        """
        self.logger.error(self._sanitize(message), *args, **kwargs)

    def critical(self, message: Any, *args, **kwargs):
        """Log critical message with automatic sanitization.

        Args:
            message: Message to log (will be sanitized)
            *args: Additional positional arguments for logger
            **kwargs: Additional keyword arguments for logger
        """
        self.logger.critical(self._sanitize(message), *args, **kwargs)

    def exception(self, message: Any, *args, **kwargs):
        """Log exception message with automatic sanitization.

        This method logs at ERROR level with exception info included.

        Args:
            message: Message to log (will be sanitized)
            *args: Additional positional arguments for logger
            **kwargs: Additional keyword arguments for logger
        """
        # Ensure exc_info is set to True for exception logging
        kwargs.setdefault('exc_info', True)
        self.logger.error(self._sanitize(message), *args, **kwargs)


def get_safe_logger(name: str) -> SafeLogger:
    """Get a safe logger instance.

    Convenience function to create a SafeLogger wrapped around a standard
    Python logger. The logger name should typically be __name__ to match
    the module name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        SafeLogger instance

    Example:
        >>> logger = get_safe_logger(__name__)
        >>> logger.error("API key exposure: sk_live_12345...")  # Sanitized automatically
        [ERROR] API key exposure: sk_live_[API_KEY]
    """
    return SafeLogger(logging.getLogger(name))
