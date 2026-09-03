"""
Tests for PTAB proxy server.

Tests standalone mode, health checks, and basic functionality.
"""

import pytest
import httpx
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
        identifier="IPR2024-01353",
        patent_number="7883848",
        document_description="Final Written Decision",
        document_code="FWD"
    )
    assert "PTAB-2024-05-15" in filename
    assert "IPR2024-01353" in filename
    assert "PAT-7883848" in filename
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
async def test_proxy_rate_limit_endpoint_requires_the_proxy_token():
    """/rate-limit/{client_ip} reports another client's request budget.

    This assertion used to require a 200 with no header at all, which encoded
    the defect: it was the one machine-facing route carrying neither the proxy
    token nor a viewer key, and PROXY_TRUSTED_IPS admits everything arriving
    behind a declared reverse-proxy hop.
    """
    from httpx import ASGITransport

    from ptab_mcp.proxy.server import _get_proxy_token

    app = create_proxy_app(api_key="test_key_12345", port=8083)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        unauthorized = await client.get("/rate-limit/127.0.0.1")
        assert unauthorized.status_code == 401

        response = await client.get(
            "/rate-limit/127.0.0.1",
            headers={"X-Proxy-Token": _get_proxy_token()},
        )

        assert response.status_code == 200
        data = response.json()
        assert "remaining_requests" in data
        assert "max_requests" in data
        assert data["max_requests"] == 5  # Default USPTO limit


@pytest.mark.asyncio
async def test_rate_limit_reads_do_not_grow_the_limiter_dict():
    """Both read-only getters indexed a defaultdict, so every distinct string
    handed to the route allocated a permanent entry and _evict_idle only ever
    ran from is_allowed."""
    from ptab_mcp.proxy.rate_limiter import RateLimiter

    limiter = RateLimiter()

    for i in range(500):
        limiter.get_remaining_requests(f"10.0.0.{i}")
        limiter.get_reset_time(f"10.0.0.{i}")

    assert limiter.requests == {}
    # ...and an untracked IP still reports a full budget
    assert limiter.get_remaining_requests("10.0.0.1") == limiter.max_requests


@pytest.mark.asyncio
async def test_download_route_requires_proxy_token():
    """The machine-facing /download route must reject requests without X-Proxy-Token."""
    from httpx import ASGITransport

    app = create_proxy_app(api_key="test_key_12345", port=8083)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        response = await client.get("/download/trial/IPR2024-01353/12345")
        assert response.status_code == 401

        # With the token, auth passes (request proceeds into the handler)
        from ptab_mcp.proxy.server import _get_proxy_token
        response = await client.get(
            "/download/trial/IPR2024-01353/12345",
            headers={"X-Proxy-Token": _get_proxy_token()}
        )
        assert response.status_code != 401


@pytest.mark.asyncio
async def test_persistent_link_unknown_hash_404():
    """Persistent endpoint returns 404 for unknown hashes — and needs no token."""
    from httpx import ASGITransport

    app = create_proxy_app(api_key="test_key_12345", port=8083)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        response = await client.get("/download/persistent/" + "0" * 24)
        assert response.status_code == 404
        assert "expired" in response.json()["detail"].lower() or \
               "not found" in response.json()["detail"].lower()


def test_secure_link_cache_roundtrip(tmp_path):
    """Persistent links resolve back to the full encrypted payload."""
    from ptab_mcp.proxy.secure_link_cache import SecureLinkCache

    cache = SecureLinkCache(db_path=str(tmp_path / "links.db"))
    url = cache.generate_persistent_link(
        identifier_type="trial",
        identifier="IPR2024-01353",
        document_id="170603095",
        file_download_uri="https://api.uspto.gov/api/v1/patent/ptab-files/IPR/2023/01035/170603095.pdf",
        enhanced_filename="PTAB-2023-06-09_IPR2023-01035_PETITION.pdf",
        base_url="http://localhost:8083",
    )
    assert url.startswith("http://localhost:8083/download/persistent/")
    link_hash = url.rsplit("/", 1)[-1]
    assert len(link_hash) == 24

    resolved = cache.resolve_persistent_link(link_hash)
    assert resolved is not None
    assert resolved["identifier_type"] == "trial"
    assert resolved["identifier"] == "IPR2024-01353"
    assert resolved["document_id"] == "170603095"
    assert resolved["file_download_uri"].endswith("170603095.pdf")
    assert resolved["enhanced_filename"].endswith(".pdf")

    # Base URL override for Docker/reverse-proxy deployments
    url_ext = cache.generate_persistent_link(
        identifier_type="trial",
        identifier="IPR2024-01353",
        document_id="170603095",
        file_download_uri="https://api.uspto.gov/x.pdf",
        enhanced_filename="x.pdf",
        base_url="https://ptab-proxy.example.com/",
    )
    assert url_ext.startswith("https://ptab-proxy.example.com/download/persistent/")


def test_secure_link_cache_expiry(tmp_path):
    """Expired links resolve to None."""
    from ptab_mcp.proxy.secure_link_cache import SecureLinkCache

    cache = SecureLinkCache(cache_duration_days=-1, db_path=str(tmp_path / "links.db"))
    url = cache.generate_persistent_link(
        identifier_type="appeal",
        identifier="2024-000001",
        document_id="999",
        file_download_uri="https://api.uspto.gov/x.pdf",
        enhanced_filename="x.pdf",
    )
    link_hash = url.rsplit("/", 1)[-1]
    assert cache.resolve_persistent_link(link_hash) is None


@pytest.mark.asyncio
async def test_register_and_list_recent_downloads():
    """Register a download via the token-protected API and read it back."""
    from httpx import ASGITransport
    from ptab_mcp.proxy.server import _get_proxy_token

    app = create_proxy_app(api_key="test_key_12345", port=8083)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        # Without token -> 401
        response = await client.post("/api/register-download", json={"identifier": "x"})
        assert response.status_code == 401

        payload = {
            "download_url": "http://localhost:8083/download/persistent/abc",
            "identifier": "IPR2024-01353",
            "identifier_type": "trial",
            "document_id": "170603095",
            "enhanced_filename": "PTAB-TEST.pdf",
        }
        payload["viewer_key"] = "viewer-key-test-1"
        response = await client.post(
            "/api/register-download",
            json=payload,
            headers={"X-Proxy-Token": _get_proxy_token()}
        )
        assert response.status_code == 200
        download_id = response.json()["download_id"]
        assert download_id

        # C-1: anonymous listing is refused — entries hold live credentials
        response = await client.get("/api/recent-downloads")
        assert response.status_code == 401

        # Wrong viewer key -> no entries
        response = await client.get("/api/recent-downloads", params={"s": "wrong-key"})
        assert response.status_code == 200
        assert all(d["download_id"] != download_id
                   for d in response.json()["downloads"])

        # Correct viewer key -> own entry, internal hash never exposed
        response = await client.get("/api/recent-downloads",
                                    params={"s": "viewer-key-test-1"})
        assert response.status_code == 200
        downloads = response.json()["downloads"]
        assert any(d["download_id"] == download_id for d in downloads)
        assert all("_viewer_key_hash" not in d for d in downloads)

        # Proxy token -> full registry (machine-facing)
        response = await client.get("/api/recent-downloads",
                                    headers={"X-Proxy-Token": _get_proxy_token()})
        assert response.status_code == 200
        assert any(d["download_id"] == download_id
                   for d in response.json()["downloads"])


@pytest.mark.asyncio
async def test_trusted_proxy_forwarding(monkeypatch):
    """H-1: X-Forwarded-For honored only from PROXY_TRUSTED_IPS peers."""
    from httpx import ASGITransport

    # Untrusted non-loopback peer is rejected by the allowlist
    monkeypatch.delenv("PROXY_TRUSTED_IPS", raising=False)
    monkeypatch.delenv("PROXY_ALLOWED_IPS", raising=False)
    app = create_proxy_app(api_key="test_key_12345", port=8083)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app, client=("203.0.113.9", 4444)),
        base_url="http://test"
    ) as client:
        response = await client.get("/")
        assert response.status_code == 403

    # Same peer declared as a trusted reverse proxy -> accepted, and the
    # forwarded client IP becomes the rate-limit/logging identity
    monkeypatch.setenv("PROXY_TRUSTED_IPS", "203.0.113.9")
    app = create_proxy_app(api_key="test_key_12345", port=8083)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app, client=("203.0.113.9", 4444)),
        base_url="http://test"
    ) as client:
        response = await client.get("/", headers={"X-Forwarded-For": "198.51.100.7"})
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_downloads_page():
    """The /downloads page serves without a token and carries highlight logic."""
    from httpx import ASGITransport

    app = create_proxy_app(api_key="test_key_12345", port=8083)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        response = await client.get("/downloads")
        assert response.status_code == 200
        assert "PTAB Recent Downloads" in response.text
        assert "highlight" in response.text  # ?highlight= deep-link support
        assert "/api/recent-downloads" in response.text


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
