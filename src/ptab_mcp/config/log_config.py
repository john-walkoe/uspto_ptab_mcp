"""
Logging configuration for PTAB MCP — single init path, content-minimization posture.

Policy: logs record operational flow (tool name, request id, duration, status,
result counts, error class, public PTAB identifiers) but never content — no
tool argument values, query/filter text, request/response bodies, OCR text,
headers/tokens, or signed download URLs.

Mechanics:
- stderr StreamHandler always (stdout is the MCP protocol channel)
- File logging is opt-in via PTAB_LOG_DIR (rotating, 600 perms); retention via
  PTAB_LOG_MAX_BYTES / PTAB_LOG_BACKUP_COUNT
- SanitizingFilter is attached to every handler so each record is scrubbed at
  the sink, regardless of which logger emitted it (library loggers included)
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional

from ..shared.log_sanitizer import SanitizingFilter

_LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
_configured = False


def setup_logging(
    log_level: Optional[str] = None,
    log_dir: Optional[str] = None,
    max_bytes: Optional[int] = None,
    backup_count: Optional[int] = None,
) -> None:
    """Configure root logging exactly once (idempotent).

    Args:
        log_level: Logging level name; falls back to the LOG_LEVEL env var,
            then INFO.
        log_dir: Directory for rotating file logs; falls back to PTAB_LOG_DIR,
            then the generic LOG_DIR the other USPTO MCPs read (cluster
            convention). Unset means stderr-only (the minimal default).
        max_bytes: Rotation size; falls back to PTAB_LOG_MAX_BYTES, then 10MB.
        backup_count: Rotated files kept; falls back to PTAB_LOG_BACKUP_COUNT,
            then 5.
    """
    global _configured
    if _configured:
        return
    _configured = True

    level_name = (log_level or os.getenv("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    formatter = logging.Formatter(_LOG_FORMAT)
    sanitizing_filter = SanitizingFilter()

    handlers: list = []

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(sanitizing_filter)
    handlers.append(console_handler)

    log_dir = log_dir or os.getenv("PTAB_LOG_DIR") or os.getenv("LOG_DIR")
    if log_dir:
        logs_dir = Path(log_dir)
        logs_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(logs_dir, 0o700)
        except (OSError, PermissionError) as e:
            logging.getLogger(__name__).warning(f"Could not set directory permissions: {e}")

        max_bytes = max_bytes or int(os.getenv("PTAB_LOG_MAX_BYTES", str(10 * 1024 * 1024)))
        backup_count = backup_count or int(os.getenv("PTAB_LOG_BACKUP_COUNT", "5"))

        app_log_file = logs_dir / "ptab_mcp.log"
        file_handler = logging.handlers.RotatingFileHandler(
            app_log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(sanitizing_filter)
        handlers.append(file_handler)

        try:
            app_log_file.touch(exist_ok=True)
            os.chmod(app_log_file, 0o600)
        except (OSError, PermissionError) as e:
            logging.getLogger(__name__).warning(f"Could not set file permissions on {app_log_file}: {e}")

    root = logging.getLogger()
    root.setLevel(level)
    for handler in handlers:
        root.addHandler(handler)

    # Suppress noisy libraries — httpx/httpcore log full request URLs at INFO,
    # and uvicorn access lines include request paths (persistent-link hashes).
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    if log_dir:
        logger.info("Logging initialized (stderr + rotating file in configured log dir)")
    else:
        logger.info("Logging initialized (stderr only; set PTAB_LOG_DIR to enable file logs)")
