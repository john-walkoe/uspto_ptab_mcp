"""
Unified USPTO MCP API Key Storage - Single Key Per File
========================================================

✅ CURRENT STANDARD - Use this module for all new code ✅

This module provides secure storage and retrieval of USPTO and Mistral API keys,
plus the shared INTERNAL_AUTH_SECRET, using Windows Data Protection API (DPAPI)
with single-key-per-file architecture.

Key Features:
- CWE-330 compliant: Uses secrets.token_bytes(32) for cryptographically secure entropy
- DPAPI encryption: Per-user, per-machine encryption on Windows
- Single responsibility: One file per key type
- Cross-platform: on non-Windows there is NO encryption. The fallback is a
  PLAINTEXT file protected by filesystem permissions (0600) only, and the
  environment is consulted FIRST so a deployment that supplies its secrets
  through the environment never touches the file at all
- Simple API: get_uspto_key(), store_uspto_key(), get_mistral_key(), store_mistral_key()
- Shared secret: ensure_internal_auth_secret() for cross-MCP authentication

File Locations:
- Windows: C:\\Users\\{User}\\.uspto_api_key, C:\\Users\\{User}\\.mistral_api_key,
           C:\\Users\\{User}\\.uspto_internal_auth_secret
- Linux/macOS: ~/.uspto_api_key, ~/.mistral_api_key, ~/.uspto_internal_auth_secret

File Format:
- Windows: bytes 0-31 random entropy (32 bytes), bytes 32+ DPAPI encrypted key
- Linux/macOS: the key in plaintext, UTF-8. "Encrypted at rest" does not apply
  on this platform, and the production branch is this one

Code Duplication Fix:
- Uses shared dpapi_crypto module instead of duplicating DPAPI code
- Uses shared storage_paths module for centralized path configuration
- Eliminates ~200 lines of duplicated DPAPI encryption code
"""

import os
import secrets
import sys
from pathlib import Path
from typing import Optional

# Import centralized DPAPI crypto functions (eliminates ~130 lines of duplication)
from ptab_mcp.shared.dpapi_crypto import encrypt_with_dpapi, decrypt_with_dpapi

# Import centralized storage paths (eliminates path duplication)
from ptab_mcp.config.storage_paths import StoragePaths
from ptab_mcp.config.api_constants import DPAPI_ENTROPY_BYTES
from ptab_mcp.shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


class UnifiedSecureStorage:
    """
    Unified secure storage for USPTO MCP ecosystem.

    Provides simple, consistent API key storage across all USPTO MCPs:
    - Patent File Wrapper (PFW)
    - Final Petition Decisions (FPD)
    - PTAB Decisions
    - Enriched Citations

    Uses single-key-per-file architecture for maximum simplicity and security isolation.

    Code Duplication Fix:
    - Uses StoragePaths for centralized path configuration
    - Uses dpapi_crypto for encryption (no duplicated DPAPI code)
    """

    def __init__(self):
        """Initialize unified secure storage using centralized paths."""
        # Use centralized storage paths (eliminates path duplication)
        self.uspto_key_path = StoragePaths.USPTO_API_KEY
        self.mistral_key_path = StoragePaths.MISTRAL_API_KEY
        self.internal_auth_secret_path = StoragePaths.INTERNAL_AUTH_SECRET

        # Log storage paths for debugging
        logger.debug(f"USPTO key path: {self.uspto_key_path}")
        logger.debug(f"Mistral key path: {self.mistral_key_path}")
        logger.debug(f"Internal auth secret path: {self.internal_auth_secret_path}")

    @staticmethod
    def _verify_file_permissions(path: Path, expected_mode: int = 0o600) -> bool:
        """
        Verify file permissions are correctly set (Linux/macOS security).

        Security: Ensures API keys are only readable by owner (CWE-732).

        Args:
            path: File path to verify
            expected_mode: Expected permission mode (default: 0o600 = owner read/write only)

        Returns:
            True if permissions are correct, False otherwise

        Note:
            On Windows, returns True (DPAPI provides encryption, not file permissions)
        """
        # Windows uses DPAPI encryption instead of file permissions
        if sys.platform == 'win32':
            return True

        try:
            import stat
            file_stat = path.stat()
            actual_mode = stat.S_IMODE(file_stat.st_mode)

            if actual_mode != expected_mode:
                logger.warning(
                    f"File permissions mismatch on {path}: "
                    f"expected {oct(expected_mode)}, got {oct(actual_mode)}"
                )
                return False

            logger.debug(f"Verified file permissions on {path}: {oct(actual_mode)}")
            return True

        except Exception as e:
            logger.error(f"Failed to verify file permissions on {path}: {e}")
            return False

    def has_uspto_key(self) -> bool:
        """Check if USPTO API key exists in secure storage."""
        return self.uspto_key_path.exists()

    def has_mistral_key(self) -> bool:
        """Check if Mistral API key exists in secure storage."""
        return self.mistral_key_path.exists()

    def get_uspto_key(self) -> Optional[str]:
        """
        Retrieve USPTO API key from secure storage.

        Returns:
            USPTO API key string, or None if not found or decryption fails
        """
        return self._load_single_key(self.uspto_key_path, "USPTO_API_KEY")

    def store_uspto_key(self, key: str) -> bool:
        """
        Store USPTO API key in secure storage.

        Args:
            key: USPTO API key string

        Returns:
            True if successful, False otherwise
        """
        return self._store_single_key(key, self.uspto_key_path, "USPTO_API_KEY")

    def get_mistral_key(self) -> Optional[str]:
        """
        Retrieve Mistral API key from secure storage.

        Returns:
            Mistral API key string, or None if not found or decryption fails
        """
        return self._load_single_key(self.mistral_key_path, "MISTRAL_API_KEY")

    def store_mistral_key(self, key: str) -> bool:
        """
        Store Mistral API key in secure storage.

        Args:
            key: Mistral API key string

        Returns:
            True if successful, False otherwise
        """
        return self._store_single_key(key, self.mistral_key_path, "MISTRAL_API_KEY")

    def has_internal_auth_secret(self) -> bool:
        """Check if internal auth secret exists in secure storage."""
        return self.internal_auth_secret_path.exists()

    def get_internal_auth_secret(self) -> Optional[str]:
        """
        Retrieve internal auth secret from secure storage.

        This secret is SHARED across all 4 USPTO MCPs (FPD, PFW, PTAB, Citations)
        for inter-MCP authentication.

        Returns:
            Internal auth secret string, or None if not found or decryption fails
        """
        return self._load_single_key(self.internal_auth_secret_path, "INTERNAL_AUTH_SECRET")

    def store_internal_auth_secret(self, secret: str) -> bool:
        """
        Store internal auth secret in secure storage.

        This secret is SHARED across all 4 USPTO MCPs (FPD, PFW, PTAB, Citations)
        for inter-MCP authentication.

        Args:
            secret: Internal auth secret string (typically base64-encoded random bytes)

        Returns:
            True if successful, False otherwise
        """
        return self._store_single_key(secret, self.internal_auth_secret_path, "INTERNAL_AUTH_SECRET")

    def ensure_internal_auth_secret(self) -> str:
        """
        Ensure internal auth secret exists. Creates if missing.

        This implements the "first MCP wins" pattern - whoever installs first
        generates the secret, subsequent MCPs use the existing one.

        This ensures all 4 USPTO MCPs share the SAME secret for inter-MCP authentication.

        Returns:
            The internal auth secret (existing or newly generated)

        Raises:
            RuntimeError: If secret generation or storage fails
        """
        # Check if already exists
        existing = self.get_internal_auth_secret()
        if existing:
            logger.info("Using existing internal auth secret from unified storage")
            return existing

        # Generate new random secret (32 bytes, base64 encoded)
        import base64
        random_bytes = secrets.token_bytes(32)
        new_secret = base64.b64encode(random_bytes).decode('utf-8')

        logger.info("Generating new internal auth secret (first MCP installation)")

        # Store it
        if self.store_internal_auth_secret(new_secret):
            logger.info(f"Stored internal auth secret at: {self.internal_auth_secret_path}")
            return new_secret
        else:
            raise RuntimeError("Failed to store internal auth secret")

    def _store_single_key(self, key: str, path: Path, key_name: str) -> bool:
        """
        Store single key with CWE-330 compliant random entropy.

        Uses centralized dpapi_crypto module for encryption.

        Args:
            key: API key string to store
            path: File path for storage
            key_name: Key name for logging

        Returns:
            True if successful, False otherwise
        """
        try:
            if sys.platform == "win32":
                # Delete existing file if it exists (avoids permission issues on overwrite)
                if path.exists():
                    try:
                        path.unlink()
                        logger.debug(f"Deleted existing {key_name} file before writing new one")
                    except Exception as e:
                        logger.warning(f"Could not delete existing {key_name} file: {e}")
                        # Continue anyway - write_bytes might still work

                # Generate cryptographically secure random entropy (CWE-330 compliant)
                # Use constant from api_constants.py
                entropy = secrets.token_bytes(DPAPI_ENTROPY_BYTES)

                # Encrypt key data with DPAPI (using centralized function)
                key_data = key.encode('utf-8')
                encrypted_data = encrypt_with_dpapi(key_data, entropy)

                # Format: entropy (32 bytes) + encrypted_data
                file_data = entropy + encrypted_data

                # Write to file with restricted permissions
                path.write_bytes(file_data)

                # Set restrictive permissions (owner read/write only)
                if hasattr(os, 'chmod'):
                    os.chmod(path, 0o600)
                    # Verify permissions were set correctly (security best practice)
                    if not self._verify_file_permissions(path, 0o600):
                        logger.error(f"Failed to verify file permissions for {key_name}")
                        # Continue anyway - DPAPI encryption provides primary security

                logger.info(f"Stored {key_name} securely at: {path}")
                return True
            else:
                # Non-Windows: Store with basic file permissions (fallback)
                logger.warning("DPAPI not available - storing with file permissions only")
                # Create with the mode already set. write-then-chmod leaves the
                # key world-readable at 0666 & ~umask (typically 0644) for a
                # window, and the content in that window is the ODP key, the
                # Mistral key or the suite-wide shared secret.
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                try:
                    os.write(fd, key.encode("utf-8"))
                finally:
                    os.close(fd)

                if hasattr(os, 'chmod'):
                    os.chmod(path, 0o600)
                    # Verify permissions were set correctly (CRITICAL for non-Windows security)
                    if not self._verify_file_permissions(path, 0o600):
                        logger.error(f"SECURITY WARNING: Failed to set secure permissions for {key_name}")
                        # This is critical on non-Windows systems where permissions are the primary security

                logger.info(f"Stored {key_name} with file permissions at: {path}")
                return True

        except Exception as e:
            logger.error(f"Failed to store {key_name}: {e}")
            return False

    def _load_single_key(self, path: Path, key_name: str) -> Optional[str]:
        """
        Load single key with entropy extraction.

        Uses centralized dpapi_crypto module for decryption.

        Args:
            path: File path to load from
            key_name: Key name for logging

        Returns:
            Decrypted key string, or None if load fails
        """
        try:
            if not path.exists():
                logger.debug(f"{key_name} file not found: {path}")
                return None

            if sys.platform == "win32":
                # Read encrypted file data
                file_data = path.read_bytes()

                if len(file_data) < DPAPI_ENTROPY_BYTES:
                    logger.error(f"Invalid {key_name} file format: too short")
                    return None

                # Extract entropy and encrypted data
                entropy = file_data[:DPAPI_ENTROPY_BYTES]
                encrypted_data = file_data[DPAPI_ENTROPY_BYTES:]

                # Decrypt with DPAPI (using centralized function)
                decrypted_data = decrypt_with_dpapi(encrypted_data, entropy)
                key = decrypted_data.decode('utf-8')

                logger.debug(f"Loaded {key_name} from: {path}")
                return key
            else:
                # Non-Windows: the file is PLAINTEXT, so the environment wins.
                # It was consulted second, which meant a stale on-disk key
                # silently beat the value the operator actually deployed with,
                # and it made the plaintext file load-bearing where it need not
                # be.
                env_value = os.environ.get(key_name, "").strip()
                if env_value:
                    logger.debug(f"Loaded {key_name} from the environment")
                    return env_value
                key = path.read_text(encoding='utf-8').strip()
                logger.debug(f"Loaded {key_name} from: {path}")
                return key

        except Exception as e:
            logger.error(f"Failed to load {key_name}: {e}")
            return None

    def get_storage_stats(self) -> dict:
        """
        Get storage statistics for debugging.

        Returns:
            Dictionary with storage status information
        """
        return {
            "uspto_key_exists": self.has_uspto_key(),
            "mistral_key_exists": self.has_mistral_key(),
            "internal_auth_secret_exists": self.has_internal_auth_secret(),
            "uspto_key_path": str(self.uspto_key_path),
            "mistral_key_path": str(self.mistral_key_path),
            "internal_auth_secret_path": str(self.internal_auth_secret_path),
            "platform": sys.platform,
            "dpapi_available": sys.platform == "win32"
        }

    def list_available_keys(self) -> list:
        """
        List available keys for debugging.

        Returns:
            List of available key names
        """
        keys = []
        if self.has_uspto_key():
            keys.append("USPTO_API_KEY")
        if self.has_mistral_key():
            keys.append("MISTRAL_API_KEY")
        if self.has_internal_auth_secret():
            keys.append("INTERNAL_AUTH_SECRET")
        return keys


# Convenience functions for backward compatibility and ease of use

def get_uspto_api_key() -> Optional[str]:
    """Convenience function to get USPTO API key."""
    return UnifiedSecureStorage().get_uspto_key()


def store_uspto_api_key(key: str) -> bool:
    """Convenience function to store USPTO API key."""
    return UnifiedSecureStorage().store_uspto_key(key)


def get_mistral_api_key() -> Optional[str]:
    """Convenience function to get Mistral API key."""
    return UnifiedSecureStorage().get_mistral_key()


def store_mistral_api_key(key: str) -> bool:
    """Convenience function to store Mistral API key."""
    return UnifiedSecureStorage().store_mistral_key(key)


def get_internal_auth_secret() -> Optional[str]:
    """Convenience function to get internal auth secret."""
    return UnifiedSecureStorage().get_internal_auth_secret()


def store_internal_auth_secret(secret: str) -> bool:
    """Convenience function to store internal auth secret."""
    return UnifiedSecureStorage().store_internal_auth_secret(secret)


def ensure_internal_auth_secret() -> str:
    """
    Convenience function to ensure internal auth secret exists.

    First MCP installation generates the secret, subsequent MCPs use existing one.
    This ensures all 4 USPTO MCPs share the SAME secret for authentication.

    Returns:
        The internal auth secret (existing or newly generated)

    Raises:
        RuntimeError: If secret generation or storage fails
    """
    return UnifiedSecureStorage().ensure_internal_auth_secret()


def split_secret_candidates(secret: Optional[str]) -> list:
    """Split a resolved INTERNAL_AUTH_SECRET into ordered rotation candidates.

    The env var (and, since the rotation script writes it this way, the
    secure-store value too) may hold a comma-separated list: the CURRENT
    secret first, then any secret still being retired. Returns an
    order-preserving, deduplicated list of non-empty, stripped candidates —
    `[]` if `secret` is falsy. A single value with no comma round-trips as a
    one-element list, so every existing caller of `get_internal_auth_secret`
    keeps working unchanged.
    """
    if not secret:
        return []
    seen = set()
    candidates = []
    for part in secret.split(","):
        part = part.strip()
        if part and part not in seen:
            seen.add(part)
            candidates.append(part)
    return candidates


def has_secure_key(key_name: str) -> bool:
    """
    Check if a secure key exists (for backward compatibility).

    Args:
        key_name: "USPTO_API_KEY" or "MISTRAL_API_KEY"

    Returns:
        True if key exists, False otherwise
    """
    storage = UnifiedSecureStorage()
    if key_name == "USPTO_API_KEY":
        return storage.has_uspto_key()
    elif key_name == "MISTRAL_API_KEY":
        return storage.has_mistral_key()
    else:
        return False


def get_secure_api_key(key_name: str) -> Optional[str]:
    """
    Get a secure API key (for backward compatibility).

    Args:
        key_name: "USPTO_API_KEY" or "MISTRAL_API_KEY"

    Returns:
        API key string or None
    """
    storage = UnifiedSecureStorage()
    if key_name == "USPTO_API_KEY":
        return storage.get_uspto_key()
    elif key_name == "MISTRAL_API_KEY":
        return storage.get_mistral_key()
    else:
        return None


def store_secure_api_key(key: str, key_name: str) -> bool:
    """
    Store a secure API key (for backward compatibility).

    Args:
        key: API key string
        key_name: "USPTO_API_KEY" or "MISTRAL_API_KEY"

    Returns:
        True if successful, False otherwise
    """
    storage = UnifiedSecureStorage()
    if key_name == "USPTO_API_KEY":
        return storage.store_uspto_key(key)
    elif key_name == "MISTRAL_API_KEY":
        return storage.store_mistral_key(key)
    else:
        return False


# Test function with proper logging
if __name__ == "__main__":
    from ptab_mcp.shared.safe_logger import get_safe_logger
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = get_safe_logger(__name__)

    logger.info("Testing Unified Secure Storage...")

    storage = UnifiedSecureStorage()
    logger.info(f"Storage stats: {storage.get_storage_stats()}")
    logger.info(f"Available keys: {storage.list_available_keys()}")

    # Test encryption/decryption if on Windows
    if sys.platform == "win32":
        test_key = "test_api_key_12345"
        logger.info(f"Testing with key: {test_key}")

        success = storage.store_uspto_key(test_key)
        logger.info(f"Store success: {success}")

        retrieved_key = storage.get_uspto_key()
        logger.info(f"Retrieved key: {retrieved_key}")
        logger.info(f"Keys match: {test_key == retrieved_key}")

        # Clean up test
        if storage.uspto_key_path.exists():
            storage.uspto_key_path.unlink()
            logger.info("Test file cleaned up")
    else:
        logger.info("DPAPI testing skipped (not Windows)")
