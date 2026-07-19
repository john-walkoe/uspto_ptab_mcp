"""Regression tests for the resilience/error-handling audit cluster
(EF-1/RF-1 breaker wiring, EH-1 sanitization, EH-4 typed OPEN error,
RF-3 retry config, EH-2 task supervision)."""

import json

import httpx
import pytest

from ptab_mcp.api.ptab_client import PTABClient
from ptab_mcp.shared.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
)


@pytest.fixture
def fast_client(monkeypatch):
    """PTABClient with no retry sleeps and a single attempt."""
    monkeypatch.setenv("USPTO_MAX_RETRIES", "1")
    monkeypatch.setattr(PTABClient, "RETRY_DELAY", 0.0)
    return PTABClient(api_key="test_key_resilience")


# ------------------------------------------------- EF-1 / RF-1

@pytest.mark.asyncio
async def test_breaker_opens_on_retry_exhausted_timeouts(fast_client, monkeypatch):
    """Retry-exhausted timeouts must reach the breaker and open it."""

    class TimeoutClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            raise httpx.ConnectTimeout("boom")

        async def post(self, *a, **kw):
            raise httpx.ConnectTimeout("boom")

    from ptab_mcp.api import ptab_client as client_mod
    monkeypatch.setattr(client_mod.httpx, "AsyncClient", TimeoutClient)

    breaker = fast_client.trials_circuit_breaker
    threshold = breaker.failure_threshold

    # Each call = 1 attempt (retries=1) = 1 breaker failure; caller still
    # gets a formatted 408 error dict, not an exception.
    for i in range(threshold):
        result = await fast_client._make_request("trials/proceedings/search")
        assert result["error"]
        assert result["status_code"] == 408
        assert breaker.failure_count == i + 1 or breaker.state == CircuitState.OPEN

    assert breaker.state == CircuitState.OPEN

    # Next call fails fast with the typed OPEN path -> 503 (no cache)
    result = await fast_client._make_request("trials/proceedings/search")
    assert result["error"]
    assert result["status_code"] == 503


@pytest.mark.asyncio
async def test_4xx_does_not_trip_breaker(fast_client, monkeypatch):
    """Client errors (4xx) return immediately and never count as breaker failures."""

    class Resp:
        status_code = 404
        text = "not found"

        def raise_for_status(self):
            raise httpx.HTTPStatusError("404", request=None, response=self)

        def json(self):
            return {}

    class Client404:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            return Resp()

        async def post(self, *a, **kw):
            return Resp()

    from ptab_mcp.api import ptab_client as client_mod
    monkeypatch.setattr(client_mod.httpx, "AsyncClient", Client404)

    for _ in range(10):
        result = await fast_client._make_request("trials/proceedings/x")
        assert result["status_code"] == 404
    assert fast_client.trials_circuit_breaker.state == CircuitState.CLOSED
    assert fast_client.trials_circuit_breaker.failure_count == 0


# ------------------------------------------------- EH-4

@pytest.mark.asyncio
async def test_circuit_breaker_open_error_is_typed():
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=9999, name="t")

    async def fail():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        await breaker.call(fail)
    assert breaker.state == CircuitState.OPEN

    async def ok():
        return 1

    with pytest.raises(CircuitBreakerOpenError) as exc_info:
        await breaker.call(ok)
    assert exc_info.value.name == "t"


# ------------------------------------------------- EH-1

def test_tool_error_formatter_sanitizes():
    from ptab_mcp.util.response_formatter import format_error_response

    long_token = "A1b2C3d4E5f6G7h8I9j0A1b2C3d4E5f6G7h8I9j0X1y"
    raw = f"upstream said: token={long_token} for jdoe@example.com"
    payload = json.loads(format_error_response(raw, "API_ERROR"))
    assert long_token not in payload["message"]
    assert "jdoe@example.com" not in payload["message"]
    assert payload["error_type"] == "API_ERROR"


# ------------------------------------------------- RF-3

def test_retry_attempts_env(monkeypatch):
    monkeypatch.setenv("USPTO_MAX_RETRIES", "5")
    client = PTABClient(api_key="k1234567890")
    assert client.retry_attempts == 5

    monkeypatch.setenv("USPTO_MAX_RETRIES", "not-a-number")
    client = PTABClient(api_key="k1234567890")
    assert client.retry_attempts == PTABClient.RETRY_ATTEMPTS


# ------------------------------------------------- EH-2

@pytest.mark.asyncio
async def test_proxy_done_callback_clears_running_flag():
    import asyncio
    from src.ptab_mcp import server_bootstrap

    async def dying_proxy():
        raise RuntimeError("bind failed")

    task = asyncio.get_event_loop().create_task(dying_proxy())
    task.add_done_callback(server_bootstrap._on_proxy_task_done)
    server_bootstrap._proxy_server_running = True
    with pytest.raises(RuntimeError):
        await task
    # Callback runs via call_soon — yield once
    await asyncio.sleep(0)
    assert server_bootstrap._proxy_server_running is False
