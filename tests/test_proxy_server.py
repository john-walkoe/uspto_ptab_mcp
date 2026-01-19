"""
Tests for PTAB proxy server.

Tests standalone mode, health checks, and basic functionality.
"""

import pytest
import httpx
import asyncio
from pathlib import Path
import sys
import os

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ptab_mcp.proxy.server import create_proxy_app, sanitize_description, generate_enhanced_filename


def test_sanitize_description():
    """Test description sanitization for filenames."""
    # Normal case
    assert sanitize_description("Final Written Decision") == "FINAL_WRITTEN_DECISION"

    # Special characters
    assert sanitize_description("Petitioner's Response (Updated)") == "PETITIONERS_RESPONSE_UPDATED"

    # Length limit
    long_desc = "A" * 100
    result = sanitize_description(long_desc, max_length=40)
    assert len(result) == 40

    # Empty string
    assert sanitize_description("") == "DOCUMENT"
    assert sanitize_description(None) == "DOCUMENT"


def test_generate_enhanced_filename():
    """Test enhanced filename generation."""
    # Full information
    filename = generate_enhanced_filename(
        filing_date="2024-05-15",
        identifier="IPR2024-00123",
        patent_number="8524787",
        document_description="Final Written Decision",
        document_code="FWD"
    )
    assert "PTAB-2024-05-15" in filename
    assert "IPR2024-00123" in filename
    assert "PAT-8524787" in filename
    assert "FINAL_WRITTEN_DECISION" in filename
    assert filename.endswith(".pdf")

    # No patent number
    filename = generate_enhanced_filename(
        filing_date="2024-05-15",
        identifier="CBM2024-00045",
        patent_number=None,
        document_description="Institution Decision",
        document_code="ID"
    )
    assert "PTAB-2024-05-15" in filename
    assert "CBM2024-00045" in filename
    assert "PAT-" not in filename
    assert "INSTITUTION_DECISION" in filename

    # No filing date
    filename = generate_enhanced_filename(
        filing_date=None,
        identifier="PGR2024-00001",
        patent_number="10234567",
        document_description="Patent Owner Response",
        document_code="POR"
    )
    assert "PTAB-UNKNOWN" in filename
    assert "PGR2024-00001" in filename
    assert "PAT-10234567" in filename


@pytest.mark.asyncio
async def test_proxy_health_check():
    """Test proxy health check endpoint."""
    from httpx import ASGITransport

    # Create app with test API key
    app = create_proxy_app(api_key="test_key_12345", port=8083)

    # Use ASGI transport for testing
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        response = await client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "PTAB Document Proxy"
        assert data["port"] == 8083


@pytest.mark.asyncio
async def test_proxy_rate_limit_endpoint():
    """Test rate limit check endpoint."""
    from httpx import ASGITransport

    app = create_proxy_app(api_key="test_key_12345", port=8083)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        response = await client.get("/rate-limit/127.0.0.1")

        assert response.status_code == 200
        data = response.json()
        assert "remaining_requests" in data
        assert "max_requests" in data
        assert data["max_requests"] == 5  # Default USPTO limit


def test_get_local_proxy_port():
    """Test safe port parsing."""
    from ptab_mcp.main import get_local_proxy_port

    # Test with environment variable
    os.environ['PTAB_PROXY_PORT'] = '8083'
    assert get_local_proxy_port() == 8083

    # Test with "none" sentinel
    os.environ['PTAB_PROXY_PORT'] = 'none'
    assert get_local_proxy_port() == 8083

    # Test with invalid value
    os.environ['PTAB_PROXY_PORT'] = 'invalid'
    assert get_local_proxy_port() == 8083

    # Clean up
    if 'PTAB_PROXY_PORT' in os.environ:
        del os.environ['PTAB_PROXY_PORT']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
