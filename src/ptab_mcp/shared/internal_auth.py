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


class InternalAuthToken:
    """Generate and validate time-limited tokens for internal MCP communication."""

    def __init__(self, shared_secret: Optional[str] = None):
        """
        Initialize with shared secret for HMAC operations.

        Args:
            shared_secret: Shared secret for HMAC. If None, uses environment variable.
        """
        if shared_secret is None:
            shared_secret = os.getenv("INTERNAL_AUTH_SECRET")
            if not shared_secret:
                # Generate a random secret if none provided (for development)
                shared_secret = secrets.token_hex(32)

        self.shared_secret = shared_secret.encode('utf-8')
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

        # Create HMAC signature
        signature = hmac.new(
            self.shared_secret,
            payload_bytes,
            hashlib.sha256
        ).hexdigest()

        # Combine payload and signature
        token_data = {
            "payload": payload,
            "signature": signature
        }

        # Encode as base64 for transmission
        token_json = json.dumps(token_data)
        import base64
        return base64.b64encode(token_json.encode('utf-8')).decode('utf-8')

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

            # Recreate signature to verify
            payload_json = json.dumps(payload, sort_keys=True)
            payload_bytes = payload_json.encode('utf-8')

            expected_signature = hmac.new(
                self.shared_secret,
                payload_bytes,
                hashlib.sha256
            ).hexdigest()

            # Constant-time comparison
            if not hmac.compare_digest(provided_signature, expected_signature):
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
