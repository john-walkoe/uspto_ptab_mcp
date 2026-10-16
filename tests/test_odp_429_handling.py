"""ODP 429 handling and the shared limiter's refusal (rate-limit wave
2026-10-11, plan 2c / 4a / 4c.2 and 4c.3).

The rule: on a 429, note it on the shared key cooldown, then wait
max(5 s, Retry-After) and send ONCE more, only when that wait is <= 10 s and
fits the call's remaining budget; otherwise answer at once with the
rate-limit envelope carrying retry_after_seconds = max(5, Retry-After).
Never a second retry. The wait holds no shared slot. The shared limiter's
TimeoutError is answered at once with the envelope, no retry. The download
proxy buffers the PDF under the slot and releases it before serving, so a
slow consumer never holds the slot.

No network: httpx is routed through a MockTransport and sleeps are recorded.
"""

import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException

import ptab_mcp.shared.uspto_shared_rate_limiter as rate_limiter_module
from ptab_mcp.api import ptab_client as ptab_client_module
from ptab_mcp.api.ptab_client import (
    RATE_LIMIT_SOURCE_SHARED_LIMITER,
    RATE_LIMIT_SOURCE_UPSTREAM,
    PTABClient,
    RateLimitedError,
    planned_429_wait,
    rate_limited_envelope,
    retry_after_seconds,
)
from ptab_mcp.shared.uspto_shared_rate_limiter import SharedLimiterTimeoutError
from ptab_mcp.util.response_formatter import from_api_envelope

_REAL_ASYNC_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def _no_limiter_singleton(monkeypatch):
    monkeypatch.setattr(rate_limiter_module, "_singleton", None)
    monkeypatch.setattr(rate_limiter_module, "_singleton_checked", False)
    monkeypatch.delenv("USPTO_SHARED_RATE_LIMIT_DIR", raising=False)
    yield


@pytest.fixture
def sleeps(monkeypatch):
    """Record the client's sleeps instead of waiting them out."""
    recorded = []

    async def fake_sleep(seconds):
        recorded.append(seconds)

    monkeypatch.setattr(ptab_client_module.asyncio, "sleep", fake_sleep)
    return recorded


@pytest.fixture
def noted(monkeypatch):
    """Record every note_429 the client makes on the shared key."""
    recorded = []
    monkeypatch.setattr(ptab_client_module, "note_429", recorded.append)
    return recorded


def _route_httpx_through(monkeypatch, handler):
    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _responses(monkeypatch, *responses):
    """Serve the given responses in order; returns the list of requests seen."""
    seen = []
    queue = list(responses)

    def handler(request):
        seen.append(request)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    _route_httpx_through(monkeypatch, handler)
    return seen


def _429(retry_after=None):
    headers = {} if retry_after is None else {"Retry-After": str(retry_after)}
    return httpx.Response(429, text="slow down", headers=headers)


_OK = httpx.Response(200, json={"patentTrialProceedingDataBag": []})
_PDF = httpx.Response(200, content=b"%PDF-1.4 bytes")


# ---------------------------------------------------------------- the rule

class TestPlannedWait:
    @pytest.mark.parametrize("retry_after, expected", [(None, 5.0), (2, 5.0), (5, 5.0), (10, 10.0)])
    def test_waits_once_at_the_floor_or_the_header(self, retry_after, expected):
        assert planned_429_wait(retry_after, False, 30.0) == expected

    def test_a_header_above_the_absorb_ceiling_means_the_envelope(self):
        assert planned_429_wait(30, False, 60.0) is None
        assert planned_429_wait(10.5, False, 60.0) is None

    def test_a_second_429_is_never_retried(self):
        assert planned_429_wait(None, True, 60.0) is None

    def test_a_wait_outside_the_remaining_budget_means_the_envelope(self):
        assert planned_429_wait(None, False, 4.9) is None
        assert planned_429_wait(None, False, 5.0) == 5.0

    def test_retry_after_header_parsing(self):
        assert retry_after_seconds(_429()) is None
        assert retry_after_seconds(_429(2)) == 2.0
        assert retry_after_seconds(_429("7.5")) == 7.5
        assert retry_after_seconds(_429("Wed, 21 Oct 2026 07:28:00 GMT")) is None
        assert retry_after_seconds(None) is None

    def test_envelope_shape(self):
        env = rate_limited_envelope(2, RATE_LIMIT_SOURCE_UPSTREAM, "rid", response=_429(2))
        assert env["rate_limited"] is True
        assert env["retry_after_seconds"] == 5.0  # never under the floor
        assert env["status_code"] == 429
        assert env["rate_limit_source"] == RATE_LIMIT_SOURCE_UPSTREAM
        shared = rate_limited_envelope(None, RATE_LIMIT_SOURCE_SHARED_LIMITER, "rid")
        assert shared["retry_after_seconds"] == 5.0
        assert shared["rate_limit_source"] == RATE_LIMIT_SOURCE_SHARED_LIMITER

    def test_the_tool_envelope_carries_the_wait(self):
        tool = json.loads(from_api_envelope(
            rate_limited_envelope(30, RATE_LIMIT_SOURCE_UPSTREAM, "rid", response=_429(30))
        ))
        assert tool["error_type"] == "RATE_LIMIT_ERROR"
        assert tool["details"]["retry_after_seconds"] == 30.0
        assert tool["details"]["rate_limited"] is True
        assert tool["details"]["rate_limit_source"] == RATE_LIMIT_SOURCE_UPSTREAM


# ---------------------------------------------------------------- _make_request

class TestMakeRequest429:
    @pytest.mark.parametrize("retry_after", [None, 2, 5])
    async def test_exactly_one_retry_after_at_least_five_seconds(self, monkeypatch, sleeps, noted, retry_after):
        seen = _responses(monkeypatch, _429(retry_after), _OK)
        client = PTABClient(api_key="test-key-not-a-real-credential")

        result = await client.get_trial_proceeding("IPR2024-01353")
        await client.aclose()

        assert "patentTrialProceedingDataBag" in result
        assert len(seen) == 2
        assert sleeps == [5.0]
        assert noted == [None if retry_after is None else float(retry_after)]

    async def test_retry_after_30_is_the_envelope_with_no_retry(self, monkeypatch, sleeps, noted):
        seen = _responses(monkeypatch, _429(30), _OK)
        client = PTABClient(api_key="test-key-not-a-real-credential")

        result = await client.get_trial_proceeding("IPR2024-01353")
        await client.aclose()

        assert len(seen) == 1
        assert sleeps == []
        assert noted == [30.0]
        assert result["rate_limited"] is True
        assert result["retry_after_seconds"] == 30.0
        assert result["status_code"] == 429
        assert result["rate_limit_source"] == RATE_LIMIT_SOURCE_UPSTREAM

    async def test_a_persistent_429_is_never_retried_twice(self, monkeypatch, sleeps, noted):
        seen = _responses(monkeypatch, _429(), _429(2), _429(2))
        client = PTABClient(api_key="test-key-not-a-real-credential")

        result = await client.get_trial_proceeding("IPR2024-01353")
        await client.aclose()

        assert len(seen) == 2
        assert sleeps == [5.0]
        assert len(noted) == 2
        assert result["rate_limited"] is True
        assert result["retry_after_seconds"] == 5.0

    async def test_the_wait_fits_the_calls_budget_or_it_is_the_envelope(self, monkeypatch, sleeps, noted):
        seen = _responses(monkeypatch, _429(), _OK)
        client = PTABClient(api_key="test-key-not-a-real-credential")
        # A tool asked for a 5 s budget; the 5 s floor cannot fit once any
        # time has passed, so no wait is absorbed.
        result = await client._make_request("trials/proceedings/IPR2024-01353", timeout=5.0)
        await client.aclose()

        assert len(seen) == 1
        assert sleeps == []
        assert result["rate_limited"] is True

    async def test_the_wait_holds_no_shared_slot(self, monkeypatch, tmp_path):
        monkeypatch.setenv("USPTO_SHARED_RATE_LIMIT_DIR", str(tmp_path))
        monkeypatch.setenv("USPTO_SHARED_RATE_LIMIT_RPS", "1000")
        # The real limiter is on, so the retry would wait out the 5 s
        # cooldown the 429 wrote; floor it at 0 for the test.
        monkeypatch.setattr(rate_limiter_module, "_COOLDOWN_FLOOR_SECONDS", 0.0)
        limiter = rate_limiter_module.get_shared_limiter()
        slot_free_during_wait = []
        real_sleep = asyncio.sleep

        async def fake_sleep(seconds):
            if seconds < 1.0:  # the limiter's own polls stay real
                await real_sleep(seconds)
                return
            fh = limiter._try_acquire_any_slot()
            slot_free_during_wait.append(fh is not None)
            if fh is not None:
                limiter._release_slot(fh)

        monkeypatch.setattr(ptab_client_module.asyncio, "sleep", fake_sleep)
        _responses(monkeypatch, _429(), _OK)
        client = PTABClient(api_key="test-key-not-a-real-credential")

        result = await client.get_trial_proceeding("IPR2024-01353")
        await client.aclose()

        assert "patentTrialProceedingDataBag" in result
        assert slot_free_during_wait == [True]
        # And the real limiter saw the 429: the cooldown is on the key.
        assert limiter._read_cooldown_until() > 0

    async def test_limiter_timeout_is_the_envelope_at_once(self, monkeypatch, sleeps, noted):
        seen = _responses(monkeypatch, _OK)
        client = PTABClient(api_key="test-key-not-a-real-credential")

        async def refuse(*args, **kwargs):
            raise SharedLimiterTimeoutError("shared USPTO rate limiter: no request slot within 45s")

        monkeypatch.setattr(client, "_send_once", refuse)
        result = await client.get_trial_proceeding("IPR2024-01353")
        await client.aclose()

        assert seen == []
        assert sleeps == []
        assert noted == []
        assert result["rate_limited"] is True
        assert result["rate_limit_source"] == RATE_LIMIT_SOURCE_SHARED_LIMITER
        assert result["retry_after_seconds"] == 5.0
        assert result["status_code"] == 429


# ---------------------------------------------------------------- downloads

class TestDownload429:
    async def test_exactly_one_retry(self, monkeypatch, sleeps, noted):
        seen = _responses(monkeypatch, _429(2), _PDF)
        client = PTABClient(api_key="test-key-not-a-real-credential")

        content = await client.download_trial_document("https://api.uspto.gov/doc.pdf")
        await client.aclose()

        assert content.startswith(b"%PDF-")
        assert len(seen) == 2
        assert sleeps == [5.0]
        assert noted == [2.0]

    async def test_retry_after_30_raises_the_envelope(self, monkeypatch, sleeps, noted):
        seen = _responses(monkeypatch, _429(30), _PDF)
        client = PTABClient(api_key="test-key-not-a-real-credential")

        with pytest.raises(RateLimitedError) as exc_info:
            await client.download_trial_document("https://api.uspto.gov/doc.pdf")
        await client.aclose()

        assert len(seen) == 1
        assert sleeps == []
        assert exc_info.value.retry_after_seconds == 30.0
        assert exc_info.value.envelope["rate_limit_source"] == RATE_LIMIT_SOURCE_UPSTREAM

    async def test_a_persistent_429_is_never_retried_twice(self, monkeypatch, sleeps, noted):
        seen = _responses(monkeypatch, _429(), _429(), _429())
        client = PTABClient(api_key="test-key-not-a-real-credential")

        with pytest.raises(RateLimitedError) as exc_info:
            await client.download_trial_document("https://api.uspto.gov/doc.pdf")
        await client.aclose()

        assert len(seen) == 2
        assert sleeps == [5.0]
        assert exc_info.value.retry_after_seconds == 5.0

    async def test_limiter_timeout_raises_the_envelope_at_once(self, monkeypatch, sleeps, noted):
        seen = _responses(monkeypatch, _PDF)
        client = PTABClient(api_key="test-key-not-a-real-credential")

        async def refuse(*args, **kwargs):
            raise SharedLimiterTimeoutError("no slot")

        monkeypatch.setattr(client, "_read_capped_under_limiter", refuse)
        with pytest.raises(RateLimitedError) as exc_info:
            await client.download_trial_document("https://api.uspto.gov/doc.pdf")
        await client.aclose()

        assert seen == []
        assert sleeps == []
        assert exc_info.value.envelope["rate_limit_source"] == RATE_LIMIT_SOURCE_SHARED_LIMITER


# ---------------------------------------------------------------- proxy

class _FakeResponse:
    status_code = 200

    def __init__(self, chunks, status=200):
        self._chunks = chunks
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://api.uspto.gov/doc.pdf")
            response = httpx.Response(self.status_code, request=request, headers={"Retry-After": "7"})
            raise httpx.HTTPStatusError("err", request=request, response=response)

    async def aiter_bytes(self, chunk_size=8192):
        for chunk in self._chunks:
            yield chunk

    async def aclose(self):
        pass


def _fake_client(monkeypatch, chunks, status=200):
    from ptab_mcp.proxy import server as proxy_server

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        def build_request(self, *a, **kw):
            return object()

        async def send(self, request, stream=False):
            return _FakeResponse(chunks, status)

        async def aclose(self):
            pass

    monkeypatch.setattr(proxy_server.httpx, "AsyncClient", FakeClient)
    return proxy_server


class TestProxyBuffersUnderTheSlot:
    async def test_a_slow_consumer_does_not_hold_the_slot(self, monkeypatch, tmp_path):
        monkeypatch.setenv("USPTO_SHARED_RATE_LIMIT_DIR", str(tmp_path))
        monkeypatch.setenv("USPTO_SHARED_RATE_LIMIT_RPS", "1000")
        limiter = rate_limiter_module.get_shared_limiter()
        proxy_server = _fake_client(monkeypatch, [b"%PDF-1.7 fake", b" more", b" bytes"])

        stream = await proxy_server._open_upstream_pdf_stream("https://x/y.pdf", "key")

        # Before the first byte is consumed the slot is already free.
        fh = limiter._try_acquire_any_slot()
        assert fh is not None
        limiter._release_slot(fh)

        chunks = []
        async for chunk in stream:
            await asyncio.sleep(0.05)  # a deliberately slow consumer
            fh = limiter._try_acquire_any_slot()
            assert fh is not None  # still free while the consumer dawdles
            limiter._release_slot(fh)
            chunks.append(chunk)
        assert b"".join(chunks) == b"%PDF-1.7 fake more bytes"

    async def test_limiter_timeout_is_a_503_with_retry_after(self, monkeypatch, tmp_path):
        monkeypatch.setenv("USPTO_SHARED_RATE_LIMIT_DIR", str(tmp_path))
        monkeypatch.setenv("USPTO_SHARED_MAX_WAIT_SECONDS", "0.2")
        limiter = rate_limiter_module.get_shared_limiter()
        proxy_server = _fake_client(monkeypatch, [b"%PDF-1.7 fake"])
        monkeypatch.setattr(limiter, "_try_acquire_any_slot", lambda: None)

        with pytest.raises(HTTPException) as exc_info:
            await proxy_server._open_upstream_pdf_stream("https://x/y.pdf", "key")
        assert exc_info.value.status_code == 503
        assert exc_info.value.headers["Retry-After"] == "5"

    async def test_an_upstream_429_is_noted_on_the_key(self, monkeypatch, tmp_path):
        monkeypatch.setenv("USPTO_SHARED_RATE_LIMIT_DIR", str(tmp_path))
        monkeypatch.setenv("USPTO_SHARED_RATE_LIMIT_RPS", "1000")
        limiter = rate_limiter_module.get_shared_limiter()
        proxy_server = _fake_client(monkeypatch, [], status=429)

        with pytest.raises(httpx.HTTPStatusError):
            await proxy_server._open_upstream_pdf_stream("https://x/y.pdf", "key")
        assert limiter._read_cooldown_until() > 0
        # The slot was released on the way out.
        fh = limiter._try_acquire_any_slot()
        assert fh is not None
        limiter._release_slot(fh)

    async def test_the_byte_cap_bounds_the_buffer(self, monkeypatch):
        proxy_server = _fake_client(monkeypatch, [b"%PDF-1.7 ", b"x" * 100])

        with pytest.raises(HTTPException) as exc_info:
            await proxy_server._open_upstream_pdf_stream("https://x/y.pdf", "key", max_bytes=50)
        assert exc_info.value.status_code == 502

        stream = await proxy_server._open_upstream_pdf_stream("https://x/y.pdf", "key", max_bytes=500)
        assert len(b"".join([c async for c in stream])) == 109
