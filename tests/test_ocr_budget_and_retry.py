"""OCR spend and transient-failure handling.

OCR was throttled at 10 calls per minute per identity with a 50-page
per-document cap, but nothing bounded the cumulative total: one authorized
caller sustaining the rate limit runs 14,400 calls a day, visible only in a
server-side log line nobody reads (PT-28).

Mistral was also the one paid tier with no retry at all (RF-7). A single
connection reset discarded a 120-second operation the user had already waited
for, and the caller then saw the document reported as a scanned image.

No network: the retry helper is driven against an httpx MockTransport.
"""

import httpx
import pytest

from src.ptab_mcp.services.ocr_service import OCRService


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "k" * 40)
    return OCRService()


class TestDailyBudget:
    def test_the_per_minute_limit_still_applies(self, service):
        service.ocr_daily_limit = 0  # disable the daily cap
        for _ in range(service.ocr_rate_limit):
            assert service._check_ocr_rate_limit("a@b.com") is True

        assert service._check_ocr_rate_limit("a@b.com") is False

    def test_the_daily_budget_bounds_the_cumulative_total(self, service):
        service.ocr_rate_limit = 10_000        # take the minute window out of play
        service.ocr_daily_limit = 3

        for _ in range(3):
            assert service._check_ocr_rate_limit("a@b.com") is True

        assert service._check_ocr_rate_limit("a@b.com") is False

    def test_the_budget_is_per_identity(self, service):
        service.ocr_rate_limit = 10_000
        service.ocr_daily_limit = 2

        for _ in range(2):
            service._check_ocr_rate_limit("a@b.com")

        assert service._check_ocr_rate_limit("a@b.com") is False
        assert service._check_ocr_rate_limit("other@b.com") is True

    def test_zero_disables_the_daily_cap(self, service):
        service.ocr_rate_limit = 10_000
        service.ocr_daily_limit = 0

        for _ in range(50):
            assert service._check_ocr_rate_limit("a@b.com") is True

    def test_the_daily_dict_does_not_grow_without_bound(self, service, monkeypatch):
        """Idle callers are swept, the way the per-minute dict already was."""
        service.ocr_rate_limit = 10_000
        service.ocr_daily_limit = 5
        service.ocr_day_window = 0.01

        service._check_ocr_rate_limit("gone@b.com")
        import time
        time.sleep(0.02)
        service._check_ocr_rate_limit("here@b.com")

        assert "gone@b.com" not in service.ocr_daily_calls


class TestPostRetry:
    async def test_a_transient_status_is_retried(self, service, monkeypatch):
        monkeypatch.setattr("asyncio.sleep", _no_sleep)
        calls = []

        def handler(request):
            calls.append(1)
            if len(calls) < 3:
                return httpx.Response(503)
            return httpx.Response(200, json={"id": "f1"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await service._post_with_retry(client, "https://x/files")

        assert response.status_code == 200
        assert len(calls) == 3

    async def test_a_transport_error_is_retried(self, service, monkeypatch):
        monkeypatch.setattr("asyncio.sleep", _no_sleep)
        calls = []

        def handler(request):
            calls.append(1)
            if len(calls) < 2:
                raise httpx.ConnectError("reset")
            return httpx.Response(200, json={"id": "f1"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await service._post_with_retry(client, "https://x/ocr")

        assert response.status_code == 200
        assert len(calls) == 2

    async def test_a_client_error_is_not_retried(self, service, monkeypatch):
        """A 402 will not become a 200, and it has its own envelope upstream."""
        monkeypatch.setattr("asyncio.sleep", _no_sleep)
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(402)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await service._post_with_retry(client, "https://x/ocr")

        assert response.status_code == 402
        assert len(calls) == 1

    async def test_attempts_are_bounded(self, service, monkeypatch):
        monkeypatch.setattr("asyncio.sleep", _no_sleep)
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(503)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await service._post_with_retry(client, "https://x/ocr")

        assert response.status_code == 503
        assert len(calls) == service._RETRY_ATTEMPTS


async def _no_sleep(_seconds):
    return None
