"""
Centralized Storage Path Configuration

This module provides a single source of truth for all storage file paths used
across the USPTO MCP ecosystem, eliminating path duplication.

Fixes Code Duplication:
- Consolidates ~20 lines of duplicated path construction
- Eliminates path string duplication across:
  * secure_storage.py
  * shared_secure_storage.py
  * windows_setup.ps1
  * linux_setup.sh

Benefits:
- Single location to modify all storage paths
- Easy to relocate storage directory
- Consistent path construction across platforms
- Type-safe access to all storage locations

Usage:
    from ptab_mcp.config.storage_paths import StoragePaths

    # Check if key exists
    if StoragePaths.USPTO_API_KEY.exists():
        print(f"Key found at: {StoragePaths.USPTO_API_KEY}")

    # Get all paths
    paths = StoragePaths.get_all_paths()
"""

from pathlib import Path
from typing import Dict
import sys


class StoragePaths:
    """
    Centralized storage paths for USPTO MCP ecosystem.

    All paths are relative to the user's home directory for cross-platform
    compatibility and security (user-specific data).
    """

    # Base directory for all storage
    HOME_DIR = Path.home()

    # ===== Unified Storage (Current Standard) =====
    # Single-key-per-file architecture (recommended)

    USPTO_API_KEY = HOME_DIR / ".uspto_api_key"
    """
    USPTO API key storage file.
    Format: DPAPI encrypted on Windows, file permissions (600) on Linux/macOS
    """

    MISTRAL_API_KEY = HOME_DIR / ".mistral_api_key"
    """
    Mistral API key storage file (optional - for OCR).
    Format: DPAPI encrypted on Windows, file permissions (600) on Linux/macOS
    """

    INTERNAL_AUTH_SECRET = HOME_DIR / ".uspto_internal_auth_secret"
    """
    Internal authentication secret shared across all USPTO MCPs (FPD/PFW/PTAB/Citations).
    Format: DPAPI encrypted on Windows, file permissions (600) on Linux/macOS
    Pattern: "First MCP wins" - first installed MCP generates, others reuse
    """

    # ===== Legacy Storage (Backward Compatibility) =====
    # Multi-key JSON architecture (deprecated)

    PFW_SHARED_STORAGE = HOME_DIR / ".uspto_pfw_secure_keys"
    """
    Legacy: Patent File Wrapper (PFW) MCP shared storage.
    Format: DPAPI encrypted JSON with multiple keys
    Priority: Checked before FPD_LOCAL_STORAGE for backward compatibility
    """

    FPD_LOCAL_STORAGE = HOME_DIR / ".uspto_fpd_secure_keys"
    """
    Legacy: Final Petition Decisions (FPD) MCP local storage.
    Format: DPAPI encrypted JSON with multiple keys
    Deprecated: Use unified single-key-per-file storage instead
    """

    # ===== Audit & Logging =====

    AUDIT_LOG = HOME_DIR / ".uspto_mcp_audit.log"
    """
    Security audit log for USPTO MCP operations.
    Tracks: API key storage, configuration changes, security events
    """

    # ===== Class Methods =====

    @classmethod
    def get_all_paths(cls) -> Dict[str, Path]:
        """
        Get all storage paths as a dictionary.

        Returns:
            Dictionary mapping path names to Path objects

        Example:
            >>> paths = StoragePaths.get_all_paths()
            >>> print(paths['uspto_api_key'])
            /home/user/.uspto_api_key
        """
        return {
            'uspto_api_key': cls.USPTO_API_KEY,
            'mistral_api_key': cls.MISTRAL_API_KEY,
            'internal_auth_secret': cls.INTERNAL_AUTH_SECRET,
            'pfw_shared_storage': cls.PFW_SHARED_STORAGE,
            'fpd_local_storage': cls.FPD_LOCAL_STORAGE,
            'audit_log': cls.AUDIT_LOG
        }

    @classmethod
    def get_unified_paths(cls) -> Dict[str, Path]:
        """
        Get only unified storage paths (current standard).

        Returns:
            Dictionary of current unified storage paths

        Example:
            >>> paths = StoragePaths.get_unified_paths()
            >>> print(list(paths.keys()))
            ['uspto_api_key', 'mistral_api_key']
        """
        return {
            'uspto_api_key': cls.USPTO_API_KEY,
            'mistral_api_key': cls.MISTRAL_API_KEY,
            'internal_auth_secret': cls.INTERNAL_AUTH_SECRET
        }

    @classmethod
    def get_legacy_paths(cls) -> Dict[str, Path]:
        """
        Get legacy storage paths (for migration).

        Returns:
            Dictionary of legacy storage paths

        Example:
            >>> paths = StoragePaths.get_legacy_paths()
            >>> for name, path in paths.items():
            ...     if path.exists():
            ...         print(f"Legacy storage found: {name}")
        """
        return {
            'pfw_shared_storage': cls.PFW_SHARED_STORAGE,
            'fpd_local_storage': cls.FPD_LOCAL_STORAGE
        }

    @classmethod
    def exists(cls, path_name: str) -> bool:
        """
        Check if a storage path exists.

        Args:
            path_name: Name of the path to check (e.g., 'uspto_api_key')

        Returns:
            True if the file exists, False otherwise

        Example:
            >>> if StoragePaths.exists('uspto_api_key'):
            ...     print("API key found")
        """
        paths = cls.get_all_paths()
        if path_name in paths:
            return paths[path_name].exists()
        return False

    @classmethod
    def has_unified_storage(cls) -> bool:
        """
        Check if unified storage files exist.

        Returns:
            True if any unified storage file exists

        Example:
            >>> if StoragePaths.has_unified_storage():
            ...     print("Using unified storage")
        """
        return cls.USPTO_API_KEY.exists() or cls.MISTRAL_API_KEY.exists() or cls.INTERNAL_AUTH_SECRET.exists()

    @classmethod
    def has_legacy_storage(cls) -> bool:
        """
        Check if legacy storage files exist.

        Returns:
            True if any legacy storage file exists

        Example:
            >>> if StoragePaths.has_legacy_storage():
            ...     print("Migration from legacy storage recommended")
        """
        return cls.PFW_SHARED_STORAGE.exists() or cls.FPD_LOCAL_STORAGE.exists()

    @classmethod
    def get_storage_status(cls) -> Dict[str, bool]:
        """
        Get status of all storage locations.

        Returns:
            Dictionary mapping path names to existence status

        Example:
            >>> status = StoragePaths.get_storage_status()
            >>> print(f"USPTO key exists: {status['uspto_api_key']}")
            >>> print(f"Legacy storage: {status['has_legacy']}")
        """
        return {
            'uspto_api_key': cls.USPTO_API_KEY.exists(),
            'mistral_api_key': cls.MISTRAL_API_KEY.exists(),
            'internal_auth_secret': cls.INTERNAL_AUTH_SECRET.exists(),
            'pfw_shared_storage': cls.PFW_SHARED_STORAGE.exists(),
            'fpd_local_storage': cls.FPD_LOCAL_STORAGE.exists(),
            'audit_log': cls.AUDIT_LOG.exists(),
            'has_unified': cls.has_unified_storage(),
            'has_legacy': cls.has_legacy_storage(),
            'platform': sys.platform
        }

    @classmethod
    def get_storage_priority(cls) -> Path:
        """
        Get storage path with priority: PFW shared > FPD local > unified.

        This maintains backward compatibility by checking for shared PFW
        storage first (if PFW MCP is installed).

        Returns:
            Path to use for storage operations

        Example:
            >>> storage_path = StoragePaths.get_storage_priority()
            >>> print(f"Using storage at: {storage_path}")
        """
        # Priority 1: PFW shared storage (if exists)
        if cls.PFW_SHARED_STORAGE.exists():
            return cls.PFW_SHARED_STORAGE

        # Priority 2: FPD local storage (legacy)
        if cls.FPD_LOCAL_STORAGE.exists():
            return cls.FPD_LOCAL_STORAGE

        # Priority 3: Unified storage (default for new installations)
        return cls.USPTO_API_KEY


# Convenience constants for direct import
USPTO_API_KEY_PATH = StoragePaths.USPTO_API_KEY
MISTRAL_API_KEY_PATH = StoragePaths.MISTRAL_API_KEY
INTERNAL_AUTH_SECRET_PATH = StoragePaths.INTERNAL_AUTH_SECRET
AUDIT_LOG_PATH = StoragePaths.AUDIT_LOG
