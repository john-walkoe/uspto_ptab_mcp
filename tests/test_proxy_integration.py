"""
Tests for PTAB proxy integration with PFW centralized proxy.

Tests centralized mode, automatic fallback, and JWT authentication.
"""

import pytest
import httpx
import os
import json
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ptab_mcp.main import _detect_pfw_proxy, get_local_proxy_port
from ptab_mcp.shared.internal_auth import InternalAuthToken, MCPAuthManager
from ptab_mcp.proxy.models import PTABDocumentRegistration


def test_detect_pfw_proxy_none_sentinel():
    """Test PFW detection with 'none' sentinel value."""
    # Set sentinel value
    os.environ['CENTRALIZED_PROXY_PORT'] = 'none'

    result = _detect_pfw_proxy()

    assert result is None

    # Clean up
    if 'CENTRALIZED_PROXY_PORT' in os.environ:
        del os.environ['CENTRALIZED_PROXY_PORT']


def test_detect_pfw_proxy_explicit_port():
    """Test PFW detection with explicit port."""
    # Set explicit port - detection will try this first
    os.environ['CENTRALIZED_PROXY_PORT'] = '9999'  # Use unlikely port

    # Detection will try explicit port, then retry with 8080
    result = _detect_pfw_proxy()

    # Could return None if PFW not running, or a port if it is running
    # Just verify function doesn't crash
    assert result is None or isinstance(result, int)

    # Clean up
    if 'CENTRALIZED_PROXY_PORT' in os.environ:
        del os.environ['CENTRALIZED_PROXY_PORT']


def test_get_local_proxy_port_precedence():
    """Test that PTAB_PROXY_PORT takes precedence over PROXY_PORT."""
    # Set both environment variables
    os.environ['PTAB_PROXY_PORT'] = '8083'
    os.environ['PROXY_PORT'] = '8081'

    port = get_local_proxy_port()

    # PTAB_PROXY_PORT should take precedence
    assert port == 8083

    # Clean up
    for key in ['PTAB_PROXY_PORT', 'PROXY_PORT']:
        if key in os.environ:
            del os.environ[key]


def test_get_local_proxy_port_fallback():
    """Test fallback to generic PROXY_PORT."""
    # Only set generic PROXY_PORT
    os.environ['PROXY_PORT'] = '8085'

    port = get_local_proxy_port()

    assert port == 8085

    # Clean up
    if 'PROXY_PORT' in os.environ:
        del os.environ['PROXY_PORT']


def test_get_local_proxy_port_default():
    """Test default port when no env vars set."""
    # Clear all proxy port env vars
    for key in ['PTAB_PROXY_PORT', 'PROXY_PORT']:
        if key in os.environ:
            del os.environ[key]

    port = get_local_proxy_port()

    # Should use default 8083
    assert port == 8083


def test_internal_auth_token_creation():
    """Test JWT token creation for inter-MCP communication."""
    # Create token with test secret
    auth = InternalAuthToken(shared_secret="test_secret_12345")

    token = auth.create_token(
        service_name="ptab-mcp",
        client_ip="127.0.0.1",
        ttl_minutes=5,
        metadata={"test": "data"}
    )

    # Token should be base64 encoded
    assert isinstance(token, str)
    assert len(token) > 0

    # Should be able to decode
    import base64
    decoded = base64.b64decode(token.encode('utf-8')).decode('utf-8')
    token_data = json.loads(decoded)

    assert "payload" in token_data
    assert "signature" in token_data


def test_internal_auth_token_validation():
    """Test JWT token validation."""
    auth = InternalAuthToken(shared_secret="test_secret_12345")

    # Create token
    token = auth.create_token(
        service_name="ptab-mcp",
        client_ip="127.0.0.1",
        ttl_minutes=5
    )

    # Validate token
    is_valid, payload = auth.validate_token(token)

    assert is_valid is True
    assert payload is not None
    assert payload["service"] == "ptab-mcp"
    assert payload["client_ip"] == "127.0.0.1"


def test_internal_auth_token_invalid_signature():
    """Test that tampered tokens are rejected."""
    auth = InternalAuthToken(shared_secret="test_secret_12345")

    # Create token
    token = auth.create_token(service_name="ptab-mcp", client_ip="127.0.0.1")

    # Tamper with token (change last character)
    tampered_token = token[:-1] + ("A" if token[-1] != "A" else "B")

    # Validation should fail
    is_valid, payload = auth.validate_token(tampered_token)

    assert is_valid is False
    assert payload is None


def test_mcp_auth_manager_document_token():
    """Test PTAB-specific document access token creation."""
    auth_mgr = MCPAuthManager()

    token = auth_mgr.create_document_access_token(
        identifier="IPR2024-00123",
        identifier_type="trial",
        document_identifier="171141394"
    )

    # Token should be created
    assert isinstance(token, str)
    assert len(token) > 0

    # Validate token
    is_valid, payload = auth_mgr.validate_incoming_token(token)

    assert is_valid is True
    assert payload["metadata"]["type"] == "document_access"
    assert payload["metadata"]["identifier"] == "IPR2024-00123"
    assert payload["metadata"]["identifier_type"] == "trial"


def test_ptab_document_registration_model():
    """Test Pydantic model for PTAB document registration."""
    # Valid registration
    reg = PTABDocumentRegistration(
        source="ptab",
        identifier="IPR2024-00123",
        identifier_type="trial",
        document_identifier="171141394",
        download_url="https://api.uspto.gov/ui/patent/ptab-files/IPR/2024/00123/171141394.pdf",
        api_key="test_key_12345",
        patent_number="8524787",
        enhanced_filename="PTAB-2024-05-15_IPR2024-00123_PAT-8524787_FINAL_WRITTEN_DECISION.pdf"
    )

    assert reg.source == "ptab"
    assert reg.identifier_type == "trial"
    assert reg.enhanced_filename.endswith(".pdf")


def test_ptab_document_registration_validation_source():
    """Test that source must be 'ptab'."""
    with pytest.raises(ValueError, match="source must be 'ptab'"):
        PTABDocumentRegistration(
            source="invalid",
            identifier="IPR2024-00123",
            identifier_type="trial",
            document_identifier="171141394",
            download_url="https://api.uspto.gov/test.pdf",
            api_key="test_key"
        )


def test_ptab_document_registration_validation_identifier_type():
    """Test that identifier_type must be valid."""
    with pytest.raises(ValueError, match="identifier_type must be one of"):
        PTABDocumentRegistration(
            source="ptab",
            identifier="IPR2024-00123",
            identifier_type="invalid_type",
            document_identifier="171141394",
            download_url="https://api.uspto.gov/test.pdf",
            api_key="test_key"
        )


def test_ptab_document_registration_validation_url():
    """Test that download_url must be HTTPS and from uspto.gov."""
    # HTTP should fail
    with pytest.raises(ValueError, match="download_url must use HTTPS"):
        PTABDocumentRegistration(
            source="ptab",
            identifier="IPR2024-00123",
            identifier_type="trial",
            document_identifier="171141394",
            download_url="http://api.uspto.gov/test.pdf",
            api_key="test_key"
        )

    # Wrong domain should fail
    with pytest.raises(ValueError, match="download_url must be from uspto.gov"):
        PTABDocumentRegistration(
            source="ptab",
            identifier="IPR2024-00123",
            identifier_type="trial",
            document_identifier="171141394",
            download_url="https://evil.com/test.pdf",
            api_key="test_key"
        )


def test_ptab_document_registration_validation_filename():
    """Test enhanced filename validation."""
    # No .pdf extension should fail
    with pytest.raises(ValueError, match="enhanced_filename must end with .pdf"):
        PTABDocumentRegistration(
            source="ptab",
            identifier="IPR2024-00123",
            identifier_type="trial",
            document_identifier="171141394",
            download_url="https://api.uspto.gov/test.pdf",
            api_key="test_key",
            enhanced_filename="document.txt"
        )

    # Invalid characters should fail
    with pytest.raises(ValueError, match="enhanced_filename contains invalid characters"):
        PTABDocumentRegistration(
            source="ptab",
            identifier="IPR2024-00123",
            identifier_type="trial",
            document_identifier="171141394",
            download_url="https://api.uspto.gov/test.pdf",
            api_key="test_key",
            enhanced_filename="doc with spaces.pdf"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
