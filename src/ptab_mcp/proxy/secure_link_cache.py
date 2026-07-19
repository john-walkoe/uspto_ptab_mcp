"""
Secure SQLite persistent link cache for PTAB document downloads.

Provides encrypted persistent download links that remain valid for a
configurable duration (default 7 days) while keeping all sensitive data
encrypted. The opaque link hash in the URL is the sole credential —
browser navigation needs no headers (Lesson 43).

Adapted from the PFW reference implementation with two PTAB differences:
- Payload carries identifier_type/identifier/document_id (PFW: app_number/doc_id)
  plus the resolved fileDownloadURI and enhanced filename, so persistent
  downloads can stream directly without re-searching the PTAB document
  index (which caps at ~25 documents on the GET endpoint and misses
  unindexed papers like Petitions).
- Own database file and encryption key, never shared with PFW's cache.

TODO(architectural): the Fernet key falls back to a plain file on Linux.
DPAPI is Windows-only; any user with filesystem read access can recover
the key there. Same accepted limitation as PFW.
"""

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet

from ..util.database import create_secure_connection
from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

_KEY_FILE_NAME = ".ptab_proxy_encryption_key"
_DB_FILE_NAME = "ptab_proxy_link_cache.db"


class SecureLinkCache:
    """
    Secure persistent link cache with encryption.

    Features:
    - Encrypted storage of proceeding identifiers, document IDs and download URIs
    - Opaque URLs that don't reveal business data
    - Configurable link expiration (default 7 days)
    - Automatic cleanup of expired links
    - Windows DPAPI protection for the encryption key, file fallback elsewhere
    """

    def __init__(self, cache_duration_days: int = 7, db_path: Optional[str] = None):
        self.cache_duration = timedelta(days=cache_duration_days)

        if db_path:
            self.db_path = db_path
        else:
            # Dedicated data dir (M-7): $PTAB_DATA_DIR or ~/.uspto_ptab_mcp/
            # data — a stable, mountable location instead of the repo/image
            # root. Legacy project-root files are migrated on first use.
            from ..config.storage_paths import migrate_data_file
            legacy_root = Path(__file__).parent.parent.parent.parent
            self.db_path = str(migrate_data_file(_DB_FILE_NAME, legacy_root))

        self.encryption_key = self._get_or_create_encryption_key()
        self.cipher = Fernet(self.encryption_key)
        self._init_database()

    def _get_or_create_encryption_key(self) -> bytes:
        """
        Get the Fernet key from DPAPI-protected storage or create a new one.

        On Windows the key file content is DPAPI-encrypted (per-user,
        per-machine). On non-Windows the raw key is stored with restrictive
        file permissions (0o600).
        """
        from ..config.storage_paths import migrate_data_file
        legacy_root = Path(__file__).parent.parent.parent.parent
        key_file = migrate_data_file(_KEY_FILE_NAME, legacy_root)

        try:
            from ..shared.dpapi_crypto import (
                encrypt_with_dpapi,
                decrypt_with_dpapi,
                is_dpapi_available,
            )
            from ..config.api_constants import DPAPI_ENTROPY_BYTES

            if is_dpapi_available():
                if key_file.exists():
                    encrypted = key_file.read_bytes()
                    return decrypt_with_dpapi(encrypted, DPAPI_ENTROPY_BYTES)

                key = Fernet.generate_key()
                encrypted = encrypt_with_dpapi(
                    key, DPAPI_ENTROPY_BYTES, description="PTAB Proxy Link Encryption Key"
                )
                key_file.write_bytes(encrypted)
                logger.info("Generated new DPAPI-protected proxy encryption key")
                return key
        except Exception as e:
            logger.warning(f"DPAPI key storage unavailable ({e}), using file-based key")

        return self._get_file_based_key(key_file)

    def _get_file_based_key(self, key_file: Path) -> bytes:
        """Fallback plain-file key storage for non-Windows systems."""
        if key_file.exists():
            try:
                return key_file.read_bytes()
            except Exception as e:
                logger.warning(f"Error reading encryption key file: {e}, generating new key")

        # SECURITY NOTE: on Linux/macOS the Fernet key is protected only by
        # filesystem permissions (0o600) — same accepted limitation as PFW.
        key = Fernet.generate_key()
        try:
            key_file.write_bytes(key)
            os.chmod(key_file, 0o600)
            logger.info("Generated new file-based proxy encryption key")
        except Exception as e:
            logger.warning(f"Could not save encryption key to file: {e}")

        return key

    def _init_database(self):
        """Initialize SQLite database with encrypted storage design."""
        try:
            conn = create_secure_connection(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS download_links (
                    link_hash TEXT PRIMARY KEY,           -- Irreversible hash for lookup
                    encrypted_token TEXT,                 -- Fernet-encrypted data
                    created_at TIMESTAMP,                 -- When link was created
                    last_accessed TIMESTAMP,              -- Last access time
                    access_count INTEGER DEFAULT 0,       -- Number of times accessed
                    expires_at TIMESTAMP                  -- When link expires
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_expires_at ON download_links(expires_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON download_links(created_at)")
            conn.commit()
            conn.close()
            logger.info(f"Initialized secure link cache database: {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize link cache database: {e}")
            raise

    def generate_persistent_link(
        self,
        identifier_type: str,
        identifier: str,
        document_id: str,
        file_download_uri: str,
        enhanced_filename: str,
        base_url: str = "http://localhost:8083",
    ) -> str:
        """
        Generate a secure persistent link with encrypted storage.

        Args:
            identifier_type: One of trial / appeal / interference
            identifier: Proceeding number (e.g. IPR2024-01353)
            document_id: PTAB document identifier
            file_download_uri: Resolved USPTO fileDownloadURI to stream from
            enhanced_filename: Human-readable download filename
            base_url: Externally reachable base URL of the PTAB proxy

        Returns:
            Opaque persistent download URL
        """
        try:
            token_data = json.dumps({
                'identifier_type': identifier_type,
                'identifier': identifier,
                'document_id': document_id,
                'file_download_uri': file_download_uri,
                'enhanced_filename': enhanced_filename,
                'timestamp': datetime.now().isoformat(),
                # Random component prevents pattern analysis of equal payloads
                'random': secrets.token_hex(16),
            })

            encrypted_token = self.cipher.encrypt(token_data.encode('utf-8')).decode('utf-8')

            # Irreversible hash for database lookup — 24 hex chars (~96 bits)
            link_hash = hashlib.sha256(encrypted_token.encode('utf-8')).hexdigest()[:24]

            expires_at = datetime.now() + self.cache_duration

            conn = create_secure_connection(self.db_path)
            conn.execute("""
                INSERT OR REPLACE INTO download_links
                (link_hash, encrypted_token, created_at, last_accessed, access_count, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (link_hash, encrypted_token, datetime.now(), datetime.now(), 0, expires_at))
            conn.commit()
            conn.close()

            persistent_url = f"{base_url.rstrip('/')}/download/persistent/{link_hash}"
            # Truncated hash only — the full hash is the credential (Lesson 43)
            logger.info(
                f"Generated persistent link {link_hash[:8]}... for {identifier_type} "
                f"{identifier}, expires {expires_at}"
            )
            return persistent_url

        except Exception as e:
            logger.error(f"Failed to generate persistent link: {e}")
            raise

    def resolve_persistent_link(self, link_hash: str) -> Optional[Dict[str, Any]]:
        """
        Resolve a persistent link by decrypting the stored token.

        Returns:
            Dict with identifier_type, identifier, document_id,
            file_download_uri, enhanced_filename and access metadata,
            or None if invalid/expired.
        """
        try:
            conn = create_secure_connection(self.db_path)
            cursor = conn.execute("""
                SELECT encrypted_token, created_at, access_count, expires_at
                FROM download_links
                WHERE link_hash = ? AND expires_at > ?
            """, (link_hash, datetime.now()))
            result = cursor.fetchone()
            conn.close()

            if not result:
                logger.warning(f"Persistent link {link_hash[:8]}... not found or expired")
                return None

            encrypted_token, created_at, access_count, expires_at = result

            try:
                decrypted = self.cipher.decrypt(encrypted_token.encode('utf-8')).decode('utf-8')
                token_data = json.loads(decrypted)

                self._update_access(link_hash)

                return {
                    'identifier_type': token_data['identifier_type'],
                    'identifier': token_data['identifier'],
                    'document_id': token_data['document_id'],
                    'file_download_uri': token_data.get('file_download_uri'),
                    'enhanced_filename': token_data.get('enhanced_filename'),
                    'created_at': created_at,
                    'access_count': access_count + 1,
                    'expires_at': expires_at,
                }
            except Exception as decrypt_error:
                logger.error(f"Failed to decrypt token for link {link_hash[:8]}...: {type(decrypt_error).__name__}")
                self._remove_link(link_hash)
                return None

        except Exception as e:
            logger.error(f"Error resolving persistent link {link_hash[:8]}...: {e}")
            return None

    def _update_access(self, link_hash: str):
        """Update access tracking for a link."""
        try:
            conn = create_secure_connection(self.db_path)
            conn.execute("""
                UPDATE download_links
                SET last_accessed = ?, access_count = access_count + 1
                WHERE link_hash = ?
            """, (datetime.now(), link_hash))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to update access tracking for {link_hash[:8]}...: {e}")

    def _remove_link(self, link_hash: str):
        """Remove a corrupted or invalid link."""
        try:
            conn = create_secure_connection(self.db_path)
            conn.execute("DELETE FROM download_links WHERE link_hash = ?", (link_hash,))
            conn.commit()
            conn.close()
            logger.info(f"Removed corrupted link {link_hash[:8]}...")
        except Exception as e:
            logger.warning(f"Failed to remove link {link_hash[:8]}...: {e}")

    def cleanup_expired_links(self) -> int:
        """Delete expired links. Returns the number removed."""
        try:
            conn = create_secure_connection(self.db_path)
            cursor = conn.execute(
                "DELETE FROM download_links WHERE expires_at < ?", (datetime.now(),)
            )
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} expired persistent links")
            return deleted_count
        except Exception as e:
            logger.error(f"Error during link cleanup: {e}")
            return 0


# Global cache instance
_link_cache = None


def get_link_cache() -> SecureLinkCache:
    """Get the global secure link cache instance."""
    global _link_cache
    if _link_cache is None:
        _link_cache = SecureLinkCache()
    return _link_cache
