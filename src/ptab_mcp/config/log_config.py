"""
Logging configuration for PTAB MCP with file-based audit trail.

Security Features:
- RotatingFileHandler with 10MB max size, 5 backups
- Separate security log file (10 backups for longer retention)
- File permissions set to 600 (owner read/write only)
- Persistent audit trail for forensic analysis
"""

import logging
import logging.handlers
import sys
import os
from pathlib import Path


def setup_logging(log_level: str = "INFO"):
    """
    Configure logging for PTAB MCP with file-based audit trail.

    Creates two log files in ~/.uspto_ptab_mcp/logs/:
    - ptab_mcp.log: General application logs (10MB max, 5 backups)
    - security.log: Security events only (10MB max, 10 backups for compliance)

    File permissions are set to 600 (owner read/write only) for security.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Create logs directory with secure permissions
    logs_dir = Path.home() / ".uspto_ptab_mcp" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Set directory permissions to 700 (owner only)
    if hasattr(os, 'chmod'):
        try:
            os.chmod(logs_dir, 0o700)
        except (OSError, PermissionError) as e:
            print(f"Warning: Could not set directory permissions: {e}", file=sys.stderr)

    # Application log file with rotation (10MB max, 5 backups)
    app_log_file = logs_dir / "ptab_mcp.log"
    file_handler = logging.handlers.RotatingFileHandler(
        app_log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))

    # Security log file with rotation (10MB max, 10 backups for compliance)
    security_log_file = logs_dir / "security.log"
    security_handler = logging.handlers.RotatingFileHandler(
        security_log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=10,  # Keep more security logs for compliance
        encoding='utf-8'
    )
    security_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))

    # Console handler for stderr
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))

    # Configure root logger with all handlers
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        handlers=[file_handler, console_handler]
    )

    # Configure security logger (separate file, WARNING and above)
    security_logger = logging.getLogger('security')
    security_logger.addHandler(security_handler)
    security_logger.setLevel(logging.WARNING)
    security_logger.propagate = False  # Don't duplicate to other handlers

    # Set file permissions to 600 (owner read/write only) - CRITICAL SECURITY
    if hasattr(os, 'chmod'):
        for log_file in [app_log_file, security_log_file]:
            try:
                log_file.touch(exist_ok=True)
                os.chmod(log_file, 0o600)
            except (OSError, PermissionError) as e:
                print(f"Warning: Could not set file permissions on {log_file}: {e}", file=sys.stderr)

    # Log initialization success
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized - Application log: {app_log_file}")
    logger.info(f"Security log: {security_log_file}")

    # Suppress noisy libraries (Safe: Only configuring log levels, not logging data)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
