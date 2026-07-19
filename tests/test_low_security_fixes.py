"""Regression tests for the Low-severity audit fixes (L-1/2/5/7/9/10)."""

import httpx
import pytest
from httpx import ASGITransport

from ptab_mcp.proxy.server import create_proxy_app, _get_proxy_token


# ---------------------------------------------------------------- L-1

@pytest.mark.asyncio
async def test_register_download_rejects_invalid_payload():
    app = create_proxy_app(api_key="test_key_12345", port=8083)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"X-Proxy-Token": _get_proxy_token()}

        # Missing required fields
        resp = await client.post("/api/register-download",
                                 json={"identifier": "x"}, headers=headers)
        assert resp.status_code == 400

        # Bad identifier_type
        resp = await client.post("/api/register-download", json={
            "download_url": "http://localhost:8083/download/persistent/abc",
            "identifier": "IPR2024-00123",
            "identifier_type": "docket",
            "document_id": "170603095",
        }, headers=headers)
        assert resp.status_code == 400

        # Unknown fields are dropped, not stored
        resp = await client.post("/api/register-download", json={
            "download_url": "http://localhost:8083/download/persistent/abc",
            "identifier": "IPR2024-00123",
            "identifier_type": "trial",
            "document_id": "170603095",
            "viewer_key": "vk-l1-test",
            "injected_field": "<script>alert(1)</script>",
        }, headers=headers)
        assert resp.status_code == 200

        resp = await client.get("/api/recent-downloads",
                                params={"s": "vk-l1-test"})
        entry = resp.json()["downloads"][0]
        assert "injected_field" not in entry


@pytest.mark.asyncio
async def test_register_download_accepts_real_tool_payload():
    """Regression: the download tool passes page_count as the string
    "Unknown" when the API omits pageCount. The L-1 model must accept it
    (Optional[int] rejected it -> 400 -> silent registration failure)."""
    app = create_proxy_app(api_key="test_key_12345", port=8083)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"X-Proxy-Token": _get_proxy_token()}
        payload = {
            "download_url": "http://localhost:8099/download/persistent/abc123",
            "identifier": "IPR2023-01035",
            "identifier_type": "trial",
            "document_id": "170603095",
            "document_description": "IPR2023-01035 - Petition",
            "enhanced_filename": "PTAB-2023-06-15_IPR2023-01035.pdf",
            "page_count": "Unknown",          # string, not int
            "filing_date": "2023-06-15",
            "patent_number": "10995048",
            "proxy_mode": "local",
            "viewer_key": "vk-pagecount-test",
        }
        resp = await client.post("/api/register-download", json=payload, headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["download_id"]

        # And an int page_count still works
        payload["page_count"] = 45
        payload["viewer_key"] = "vk-pagecount-int"
        resp = await client.post("/api/register-download", json=payload, headers=headers)
        assert resp.status_code == 200, resp.text

        entry = (await client.get("/api/recent-downloads",
                                  params={"s": "vk-pagecount-test"})).json()["downloads"][0]
        assert entry["page_count"] == "Unknown"


# ---------------------------------------------------------------- L-5

def test_no_inline_event_handlers_in_views():
    from ptab_mcp.ui import views

    assert "onclick=" not in views.DOWNLOADS_HTML
    assert "onclick=" not in views.SEARCH_RESULTS_HTML


# ---------------------------------------------------------------- L-7

def test_rate_limiter_evicts_idle_ips(monkeypatch):
    from ptab_mcp.proxy.rate_limiter import RateLimiter

    limiter = RateLimiter(max_requests=5, time_window=1)
    for i in range(50):
        limiter.is_allowed(f"10.0.0.{i}")
    assert len(limiter.requests) == 50

    # Advance time beyond both window and eviction interval
    import time as time_mod
    real_time = time_mod.time()
    monkeypatch.setattr(time_mod, "time", lambda: real_time + 120)
    limiter.is_allowed("10.0.1.1")
    assert len(limiter.requests) == 1  # only the fresh IP survives


# ---------------------------------------------------------------- L-10

def test_validate_document_id():
    from ptab_mcp.validation.validators import validate_document_id

    assert validate_document_id("171141394") == "171141394"
    assert validate_document_id(" 171141394 ") == "171141394"
    for bad in ("", 'doc"id', "a b", "x" * 65, "doc;rm", "../etc"):
        with pytest.raises(ValueError):
            validate_document_id(bad)


# ---------------------------------------------------------------- L-9

@pytest.mark.asyncio
async def test_magic_byte_check_rejects_non_pdf(monkeypatch):
    """_open_upstream_pdf_stream turns a non-PDF upstream body into a 502."""
    from fastapi import HTTPException
    from ptab_mcp.proxy import server as proxy_server

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        async def aiter_bytes(self, chunk_size=8192):
            yield b"<html>error page</html>"

        async def aclose(self):
            pass

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        def build_request(self, *a, **kw):
            return object()

        async def send(self, request, stream=False):
            return FakeResponse()

        async def aclose(self):
            pass

    monkeypatch.setattr(proxy_server.httpx, "AsyncClient", FakeClient)
    with pytest.raises(HTTPException) as exc_info:
        await proxy_server._open_upstream_pdf_stream("https://x/y.pdf", "key")
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_magic_byte_check_passes_pdf(monkeypatch):
    from ptab_mcp.proxy import server as proxy_server

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        async def aiter_bytes(self, chunk_size=8192):
            yield b"%PDF-1.7 fake"
            yield b" more bytes"

        async def aclose(self):
            pass

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        def build_request(self, *a, **kw):
            return object()

        async def send(self, request, stream=False):
            return FakeResponse()

        async def aclose(self):
            pass

    monkeypatch.setattr(proxy_server.httpx, "AsyncClient", FakeClient)
    stream = await proxy_server._open_upstream_pdf_stream("https://x/y.pdf", "key")
    chunks = [chunk async for chunk in stream]
    assert b"".join(chunks) == b"%PDF-1.7 fake more bytes"
