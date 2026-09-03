"""
Internal Authentication System for MCP Inter-Service Communication.

Provides secure token-based authentication between MCPs instead of passing raw API keys.
"""

import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Dict, Optional, Tuple

from .safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

# Fixed HKDF info string for deriving the inter-MCP service-token signing
# key from the shared root (S-06, PT-14). A per-purpose derived key (rather
# than the raw root) means a service token can never be replayed as, or
# mistaken for, the x-api-key transport credential or the mode=none admin
# credential — the same root grants three different things, and only this
# one derives from it.
_SERVICE_TOKEN_HKDF_INFO = b"uspto-mcp-service-token-v1"


def _hkdf_sha256(ikm: bytes, info: bytes, length: int = 32) -> bytes:
    """RFC 5869 HKDF-SHA256 with the default (all-zero) salt.

    Stdlib-only (hashlib + hmac) rather than a `cryptography` dependency,
    matching this module's existing footprint.
    """
    zero_salt = b"\x00" * hashlib.sha256().digest_size
    prk = hmac.new(zero_salt, ikm, hashlib.sha256).digest()
    okm = b""
    block = b""
    counter = 1
    while len(okm) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        okm += block
        counter += 1
    return okm[:length]


def _derive_service_token_key(root: str) -> bytes:
    """The HKDF-derived signing key for one candidate root."""
    return _hkdf_sha256(root.encode("utf-8"), _SERVICE_TOKEN_HKDF_INFO)


def _service_token_key_id(root: str) -> str:
    """Short, non-secret identifier for a root, carried in the token so a
    verifier holding several roots (current + previous) can tell which one a
    token claims without trying every derived key blind. Never used as a
    security check by itself — the signature is."""
    return hashlib.sha256(root.encode("utf-8") + b"|key-id").hexdigest()[:8]


class InternalAuthToken:
    """Generate and validate time-limited tokens for internal MCP communication."""

    def __init__(self, shared_secret: Optional[str] = None):
        """
        Initialize with shared secret for HMAC operations.

        Args:
            shared_secret: Shared secret for HMAC. If None, uses environment
                variable. May itself be a comma-separated rotation list
                (current first) — a rotation overlap window instead of a
                synchronized four-service restart (S-06, PT-14).
        """
        if shared_secret is None:
            shared_secret = os.getenv("INTERNAL_AUTH_SECRET")
            if not shared_secret:
                # Fail loud, keep running (L-3): a random per-process secret
                # can never match the peer MCP's secret, so every cross-MCP
                # call (PTAB -> PFW centralized proxy) will be rejected until
                # INTERNAL_AUTH_SECRET is configured. Local-only setups that
                # never use the centralized proxy are unaffected.
                import logging
                logging.getLogger(__name__).error(
                    "INTERNAL_AUTH_SECRET is not set — generated a random "
                    "per-process secret. Cross-MCP authentication WILL fail; "
                    "set INTERNAL_AUTH_SECRET (shared with PFW) to fix."
                )
                shared_secret = secrets.token_hex(32)

        from ..shared_secure_storage import split_secret_candidates

        roots = split_secret_candidates(shared_secret)
        if not roots:
            # Preserves prior behavior for a caller-supplied empty/odd value
            # (split_secret_candidates drops empty entries).
            roots = [shared_secret]
        self._roots = roots
        self.default_ttl_minutes = 5  # 5 minute token lifetime

    def create_token(
        self,
        service_name: str,
        client_ip: str = "127.0.0.1",
        ttl_minutes: Optional[int] = None,
        metadata: Optional[Dict] = None
    ) -> str:
        """
        Create time-limited authorization token.

        Args:
            service_name: Name of the requesting service
            client_ip: Client IP address for binding
            ttl_minutes: Token lifetime in minutes
            metadata: Additional metadata to include in token

        Returns:
            Base64-encoded token string
        """
        if ttl_minutes is None:
            ttl_minutes = self.default_ttl_minutes

        # Create token payload
        current_time = int(time.time())
        expires_at = current_time + (ttl_minutes * 60)

        payload = {
            "service": service_name,
            "client_ip": client_ip,
            "issued_at": current_time,
            "expires_at": expires_at,
            "metadata": metadata or {}
        }

        # Serialize payload
        payload_json = json.dumps(payload, sort_keys=True)
        payload_bytes = payload_json.encode('utf-8')

        # Sign with the HKDF-derived per-purpose key for the CURRENT root
        # (self._roots[0]), never a previous one — rotation is a verify-only
        # overlap window, not a second signer.
        current_root = self._roots[0]
        signature = hmac.new(
            _derive_service_token_key(current_root),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()

        # Combine payload, signature and the key id a verifier holding
        # several roots can use to identify which one this claims (not a
        # security check by itself).
        token_data = {
            "payload": payload,
            "signature": signature,
            "key_id": _service_token_key_id(current_root),
        }

        # Encode as base64 for transmission
        token_json = json.dumps(token_data)
        import base64
        return base64.b64encode(token_json.encode('utf-8')).decode('utf-8')

    def _signature_matches_any_root(
        self, provided_signature: str, payload_bytes: bytes, key_id: Optional[str]
    ) -> bool:
        """True when `provided_signature` validates under any candidate root.

        Every candidate root is ALWAYS compared, never short-circuited on the
        first match, so the timing does not reveal how many roots are
        configured or which one (if any) validated.

        `key_id is not None` selects the scheme: present means a new-style
        token, verified against the HKDF-derived per-purpose key for each
        root; absent means a legacy token from a sibling that has not rolled
        to the HKDF-derived scheme yet, verified the way this module always
        has — raw-root HMAC — across every candidate root.
        """
        matched = False
        if key_id is not None:
            for root in self._roots:
                derived_signature = hmac.new(
                    _derive_service_token_key(root), payload_bytes, hashlib.sha256
                ).hexdigest()
                if hmac.compare_digest(provided_signature, derived_signature):
                    matched = True
        else:
            for root in self._roots:
                legacy_signature = hmac.new(
                    root.encode("utf-8"), payload_bytes, hashlib.sha256
                ).hexdigest()
                if hmac.compare_digest(provided_signature, legacy_signature):
                    matched = True
            if matched:
                logger.info(
                    "Accepted a legacy (no key_id) internal auth token; "
                    "the issuing service has not been rolled yet"
                )
        return matched

    def validate_token(
        self,
        token: str,
        expected_service: Optional[str] = None,
        expected_client_ip: Optional[str] = None
    ) -> Tuple[bool, Optional[Dict]]:
        """
        Validate token and return payload if valid.

        Args:
            token: Base64-encoded token string
            expected_service: Expected service name (optional)
            expected_client_ip: Expected client IP (optional)

        Returns:
            Tuple of (is_valid, payload_dict)
        """
        try:
            # Decode base64
            import base64
            token_json = base64.b64decode(token.encode('utf-8')).decode('utf-8')
            token_data = json.loads(token_json)

            payload = token_data.get("payload", {})
            provided_signature = token_data.get("signature", "")
            key_id = token_data.get("key_id")

            # Recreate signature to verify
            payload_json = json.dumps(payload, sort_keys=True)
            payload_bytes = payload_json.encode('utf-8')

            if not self._signature_matches_any_root(
                provided_signature, payload_bytes, key_id
            ):
                return False, None

            # Check expiration
            current_time = int(time.time())
            expires_at = payload.get("expires_at", 0)

            if current_time > expires_at:
                return False, None  # Token expired

            # Check service name if provided
            if expected_service and payload.get("service") != expected_service:
                return False, None

            # Check client IP if provided
            if expected_client_ip and payload.get("client_ip") != expected_client_ip:
                return False, None

            return True, payload

        except Exception:
            return False, None

    def get_token_info(self, token: str) -> Optional[Dict]:
        """
        Get token information without validating signature (for debugging).

        Args:
            token: Base64-encoded token string

        Returns:
            Token payload dict or None if invalid format
        """
        try:
            import base64
            token_json = base64.b64decode(token.encode('utf-8')).decode('utf-8')
            token_data = json.loads(token_json)
            return token_data.get("payload", {})
        except Exception:
            return None


class MCPAuthManager:
    """High-level authentication manager for PTAB MCP service."""

    def __init__(self):
        self.auth_token = InternalAuthToken()
        self.service_name = "ptab-mcp"

    def create_service_token(self, target_service: str, metadata: Optional[Dict] = None) -> str:
        """
        Create a token for communicating with another service.

        Args:
            target_service: Name of the target service
            metadata: Additional context data

        Returns:
            Authorization token
        """
        return self.auth_token.create_token(
            service_name=self.service_name,
            client_ip="127.0.0.1",
            metadata={
                "target_service": target_service,
                **(metadata or {})
            }
        )

    def validate_incoming_token(self, token: str) -> Tuple[bool, Optional[Dict]]:
        """
        Validate a token from another service.

        Args:
            token: Token to validate

        Returns:
            Tuple of (is_valid, token_payload)
        """
        return self.auth_token.validate_token(token)

    def create_document_access_token(
        self,
        identifier: str,
        identifier_type: str,
        document_identifier: str
    ) -> str:
        """
        Create a token specifically for PTAB document access.

        Args:
            identifier: Trial/appeal/interference number
            identifier_type: Type of identifier (trial, appeal, interference)
            document_identifier: Document identifier

        Returns:
            Document access token
        """
        metadata = {
            "type": "document_access",
            "identifier": identifier,
            "identifier_type": identifier_type,
            "document_identifier": document_identifier
        }

        return self.auth_token.create_token(
            service_name=self.service_name,
            client_ip="127.0.0.1",
            ttl_minutes=10,  # Longer TTL for document downloads
            metadata=metadata
        )


# Global instance for easy access
mcp_auth = MCPAuthManager()
