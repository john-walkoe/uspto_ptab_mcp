"""
Database utilities with security enhancements for SQLite connections.

Provides secure connection management with proper timeouts and security PRAGMAs.
"""
import os
import sqlite3
from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


def restrict_db_file_permissions(db_path: str) -> None:
    """chmod 0600 a SQLite database file and its -wal/-shm sidecars.

    Best effort — a failed chmod (e.g. exotic filesystem) must never break
    the connection. No-op for files that don't exist yet.
    """
    for path in (db_path, f"{db_path}-wal", f"{db_path}-shm"):
        try:
            if os.path.exists(path):
                os.chmod(path, 0o600)
        except OSError as e:
            logger.warning(f"Could not restrict permissions on {path}: {e}")


def create_secure_connection(db_path: str, timeout: float = 30.0) -> sqlite3.Connection:
    """
    Create a secure SQLite connection with timeouts and security PRAGMAs.

    Args:
        db_path: Path to SQLite database file
        timeout: Connection timeout in seconds (default: 30.0)

    Returns:
        Configured SQLite connection

    Raises:
        sqlite3.OperationalError: If connection fails
    """
    try:
        # Create connection with timeout and thread safety
        conn = sqlite3.connect(
            db_path,
            timeout=timeout,
            check_same_thread=False
        )

        # Owner-only permissions on the DB and its WAL/SHM sidecars (M-1,
        # CWE-732) — sqlite creates them world-readable by default.
        restrict_db_file_permissions(db_path)

        # Configure security and performance PRAGMAs
        # NOTE: WAL mode (Write-Ahead Logging) is used for concurrency, but it is
        # NOT safe on network filesystems (NFS, CIFS/SMB, etc.) due to file locking
        # issues. SQLite's WAL mode requires proper filesystem-level locking support.
        # On network filesystems, set USPTO_DB_JOURNAL_MODE=DELETE to use rollback
        # journal mode instead. See: https://www.sqlite.org/wal.html#networks
        conn.execute("PRAGMA busy_timeout = 30000")  # 30 second busy timeout
        journal_mode = os.environ.get("USPTO_DB_JOURNAL_MODE", "WAL").upper()
        if journal_mode not in ("WAL", "DELETE", "TRUNCATE", "PERSIST", "MEMORY"):
            logger.warning(f"Invalid USPTO_DB_JOURNAL_MODE '{journal_mode}', using WAL")
            journal_mode = "WAL"
        conn.execute(f"PRAGMA journal_mode = {journal_mode}")
        conn.execute("PRAGMA synchronous = NORMAL")  # Balanced performance/safety
        conn.execute("PRAGMA foreign_keys = ON")     # Enable foreign key constraints
        conn.execute("PRAGMA temp_store = MEMORY")   # Keep temp tables in memory

        # Test connection
        conn.execute("SELECT 1").fetchone()

        logger.debug(f"Secure SQLite connection established: {db_path}")
        return conn

    except sqlite3.OperationalError as e:
        logger.error(f"Failed to create secure SQLite connection to {db_path}: {e}")
        raise
