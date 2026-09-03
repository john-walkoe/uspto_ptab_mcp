"""Outbound-transport hardening for PTABClient (fleet review 2026-09-03).

Covers PT-03 (the ODP key rode cross-origin redirects), the per-attempt httpx
client (keepalive limits never applied), and the uncapped buffered PDF
download.
"""

import asyncio

import httpx
import pytest

from src.ptab_mcp.api.ptab_client import PTABClient
from src.ptab_mcp.shared.uspto_hosts import (
    is_uspto_url,
    strip_api_key_off_uspto,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client():
    return PTABClient(api_key="test-key-not-a-real-credential")


# ---------------------------------------------------------------------------
# PT-03: the API key must not leave uspto.gov
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://api.uspto.gov/api/v1/patent/trials", True),
    ("https://developer.uspto.gov/x", True),
    ("https://uspto.gov/x", True),
    ("http://api.uspto.gov/x", False),            # plaintext
    ("https://uspto.gov.evil.example/x", False),  # suffix confusion
    ("https://s3.amazonaws.com/signed", False),   # the real redirect target
])
async def test_host_allowlist(url, expected):
    assert is_uspto_url(url) is expected


async def test_hook_strips_key_on_foreign_host():
    request = httpx.Request(
        "GET", "https://s3.amazonaws.com/signed",
        headers={"X-API-KEY": "secret", "Accept": "application/pdf"},
    )
    await strip_api_key_off_uspto(request)
    assert "x-api-key" not in request.headers
    assert request.headers["Accept"] == "application/pdf"


async def test_hook_keeps_key_on_uspto_host():
    request = httpx.Request(
        "GET", "https://api.uspto.gov/x", headers={"X-API-KEY": "secret"},
    )
    await strip_api_key_off_uspto(request)
    assert request.headers["x-api-key"] == "secret"


async def test_download_follows_redirect_without_the_key(client):
    """End to end through a real httpx client over a mock transport: the
    second hop must carry no key. httpx strips only Authorization and Cookie
    on its own."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("x-api-key")))
        if request.url.host == "api.uspto.gov":
            return httpx.Response(
                302, headers={"Location": "https://s3.example.com/signed.pdf"}
            )
        return httpx.Response(200, content=b"%PDF-1.4 body")

    client._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        event_hooks={"request": [strip_api_key_off_uspto]},
    )
    client._http_client_loop = asyncio.get_running_loop()

    body = await client.download_trial_document("https://api.uspto.gov/doc.pdf")

    assert body == b"%PDF-1.4 body"
    assert seen[0][1] == "test-key-not-a-real-credential"
    assert seen[1][0] == "https://s3.example.com/signed.pdf"
    assert seen[1][1] is None


# ---------------------------------------------------------------------------
# One pooled client per instance, not one per attempt
# ---------------------------------------------------------------------------

async def test_http_client_is_reused_across_calls(client):
    first = client._get_http_client()
    second = client._get_http_client()
    assert first is second
    assert first.follow_redirects is True
    await client.aclose()
    assert client._http_client is None


async def test_http_client_is_rebuilt_on_a_different_loop(client):
    built = client._get_http_client()
    # Simulate the client having been created on another running loop.
    client._http_client_loop = object()
    assert client._get_http_client() is not built


# ---------------------------------------------------------------------------
# The download is capped instead of buffering an arbitrary body
# ---------------------------------------------------------------------------

async def test_download_aborts_above_the_byte_cap(client):
    def handler(request: httpx.Request) -> httpx.Response:
        # A real PDF header: the body must pass the %PDF- magic check so this
        # test still exercises the size cap rather than the content check.
        return httpx.Response(200, content=b"%PDF-1.7\n" + b"x" * 5000)

    client._http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    client._http_client_loop = asyncio.get_running_loop()
    client.max_pdf_bytes = 1000

    with pytest.raises(ValueError, match="download limit"):
        await client.download_trial_document("https://api.uspto.gov/big.pdf")


async def test_a_non_pdf_body_is_refused_before_it_reaches_the_parser(client):
    """An HTML error page returned with a 200 used to be handed to the PDF
    parser and then uploaded to a paid third-party OCR service declared as
    application/pdf. The proxy stream path already did this check; the tool
    download path never got it."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html><body>Service Unavailable</body></html>")

    client._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client._http_client_loop = asyncio.get_running_loop()

    with pytest.raises(ValueError, match="magic-byte"):
        await client.download_trial_document("https://api.uspto.gov/notapdf.pdf")


async def test_a_real_pdf_body_is_returned(client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.7\nbody")

    client._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client._http_client_loop = asyncio.get_running_loop()

    assert await client.download_trial_document(
        "https://api.uspto.gov/ok.pdf") == b"%PDF-1.7\nbody"
