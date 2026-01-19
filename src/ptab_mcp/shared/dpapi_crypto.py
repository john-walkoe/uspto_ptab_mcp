"""
Windows DPAPI Cryptographic Operations - DRY Implementation

This module provides centralized DPAPI encryption/decryption functionality,
eliminating duplication between secure_storage.py and shared_secure_storage.py.

Fixes Code Duplication:
- Consolidates ~200 lines of duplicated DPAPI code
- Single source of truth for Windows cryptographic operations
- CWE-330 compliant: Uses secrets.token_bytes(32) for entropy

Security Features:
- DPAPI encryption: Per-user, per-machine encryption on Windows
- Cryptographically secure entropy generation
- Proper memory cleanup with LocalFree

Usage:
    from fpd_mcp.shared.dpapi_crypto import encrypt_with_dpapi, decrypt_with_dpapi

    # Encrypt
    entropy = secrets.token_bytes(32)
    encrypted = encrypt_with_dpapi(b"sensitive data", entropy)

    # Decrypt
    decrypted = decrypt_with_dpapi(encrypted, entropy)
"""

import ctypes
import ctypes.wintypes
import sys
from typing import Optional


class DATA_BLOB(ctypes.Structure):
    """Windows DATA_BLOB structure for DPAPI operations."""
    _fields_ = [
        ('cbData', ctypes.wintypes.DWORD),
        ('pbData', ctypes.POINTER(ctypes.c_char))
    ]


def extract_data_from_blob(blob: DATA_BLOB) -> bytes:
    """
    Extract bytes from a DATA_BLOB structure and free memory.

    Args:
        blob: DATA_BLOB structure containing encrypted/decrypted data

    Returns:
        Extracted bytes from the blob
    """
    if not blob.cbData:
        return b''

    cbData = int(blob.cbData)
    pbData = blob.pbData
    buffer = ctypes.create_string_buffer(cbData)
    ctypes.memmove(buffer, pbData, cbData)

    # Free the memory allocated by DPAPI
    ctypes.windll.kernel32.LocalFree(pbData)

    return buffer.raw


def encrypt_with_dpapi(
    data: bytes,
    entropy: bytes,
    description: str = "USPTO MCP API Key"
) -> bytes:
    """
    Encrypt data using Windows DPAPI with custom entropy.

    Args:
        data: The data to encrypt (API key as bytes)
        entropy: Custom entropy for additional security (recommend 32 bytes)
        description: Description for the encrypted data

    Returns:
        Encrypted data as bytes

    Raises:
        OSError: If encryption fails
        RuntimeError: If not running on Windows

    Example:
        >>> import secrets
        >>> entropy = secrets.token_bytes(32)
        >>> encrypted = encrypt_with_dpapi(b"my_api_key", entropy)
    """
    if sys.platform != "win32":
        raise RuntimeError("DPAPI is only available on Windows")

    # Prepare input data blob
    data_in = DATA_BLOB()
    data_in.pbData = ctypes.cast(
        ctypes.create_string_buffer(data),
        ctypes.POINTER(ctypes.c_char)
    )
    data_in.cbData = len(data)

    # Prepare output data blob
    data_out = DATA_BLOB()

    # Prepare entropy blob
    entropy_blob = DATA_BLOB()
    entropy_blob.pbData = ctypes.cast(
        ctypes.create_string_buffer(entropy),
        ctypes.POINTER(ctypes.c_char)
    )
    entropy_blob.cbData = len(entropy)

    # Call CryptProtectData
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    result = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(data_in),          # pDataIn
        description,                     # szDataDescr
        ctypes.byref(entropy_blob),     # pOptionalEntropy
        None,                           # pvReserved
        None,                           # pPromptStruct
        CRYPTPROTECT_UI_FORBIDDEN,      # dwFlags
        ctypes.byref(data_out)          # pDataOut
    )

    if not result:
        error_code = ctypes.windll.kernel32.GetLastError()
        raise OSError(f"CryptProtectData failed with error code: {error_code}")

    # Extract encrypted data and free memory
    return extract_data_from_blob(data_out)


def decrypt_with_dpapi(encrypted_data: bytes, entropy: bytes) -> bytes:
    """
    Decrypt data using Windows DPAPI with custom entropy.

    Args:
        encrypted_data: The encrypted data to decrypt
        entropy: Custom entropy used during encryption (same as encrypt)

    Returns:
        Decrypted data as bytes

    Raises:
        OSError: If decryption fails
        RuntimeError: If not running on Windows

    Example:
        >>> decrypted = decrypt_with_dpapi(encrypted_data, entropy)
        >>> api_key = decrypted.decode('utf-8')
    """
    if sys.platform != "win32":
        raise RuntimeError("DPAPI is only available on Windows")

    # Prepare input data blob with encrypted data
    data_in = DATA_BLOB()
    data_in.pbData = ctypes.cast(
        ctypes.create_string_buffer(encrypted_data),
        ctypes.POINTER(ctypes.c_char)
    )
    data_in.cbData = len(encrypted_data)

    # Prepare output data blob
    data_out = DATA_BLOB()

    # Prepare entropy blob
    entropy_blob = DATA_BLOB()
    entropy_blob.pbData = ctypes.cast(
        ctypes.create_string_buffer(entropy),
        ctypes.POINTER(ctypes.c_char)
    )
    entropy_blob.cbData = len(entropy)

    # Prepare description pointer
    description_ptr = ctypes.wintypes.LPWSTR()

    # Call CryptUnprotectData
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    result = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(data_in),          # pDataIn
        ctypes.byref(description_ptr),  # ppszDataDescr
        ctypes.byref(entropy_blob),     # pOptionalEntropy
        None,                           # pvReserved
        None,                           # pPromptStruct
        CRYPTPROTECT_UI_FORBIDDEN,      # dwFlags
        ctypes.byref(data_out)          # pDataOut
    )

    if not result:
        error_code = ctypes.windll.kernel32.GetLastError()
        raise OSError(f"CryptUnprotectData failed with error code: {error_code}")

    # Clean up description string if allocated
    if description_ptr.value:
        ctypes.windll.kernel32.LocalFree(description_ptr)

    # Extract decrypted data and free memory
    return extract_data_from_blob(data_out)


# Utility function for testing
def is_dpapi_available() -> bool:
    """
    Check if DPAPI is available on the current platform.

    Returns:
        True if running on Windows, False otherwise
    """
    return sys.platform == "win32"
