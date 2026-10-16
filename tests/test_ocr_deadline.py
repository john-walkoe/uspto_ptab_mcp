"""One end-to-end deadline per PTAB_get_document_content call.

Cloudflare cuts a proxied request at about 100 s. The Mistral tier used to
budget each attempt on its own (120 s per request, three attempts, two
requests), so a slow OCR run could not finish inside the cut no matter what.
Now one Deadline (default 85 s) is created when the tool starts, every
Mistral attempt is capped at what is left, a retry is taken only when its
backoff leaves room for another attempt, and Docling runs only on the rest.

Time is faked: the Deadline takes an injectable clock, and asyncio.sleep is
patched to advance that clock instead of waiting. Mistral is an httpx
MockTransport. No network.
"""

import asyncio

import httpx
import pytest

from src.ptab_mcp.services.ocr_service import OCRService
from src.ptab_mcp.util import deadline as deadline_module
from src.ptab_mcp.util.deadline import Deadline, DeadlineExceeded


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)
        fake.t += seconds

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    fake.slept = slept
    return fake


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "k" * 40)
    return OCRService()


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestDeadline:
    def test_remaining_counts_down_and_never_goes_negative(self, clock):
        d = Deadline(85, clock=clock)
        clock.t += 80
        assert d.remaining() == pytest.approx(5)
        clock.t += 10
        assert d.remaining() == 0.0 and d.expired()

    @pytest.mark.parametrize("raw, expected", [
        ("", 85.0), ("60", 60.0), ("junk", 85.0), ("0", 85.0), ("-5", 85.0)])
    def test_env(self, monkeypatch, raw, expected):
        monkeypatch.setenv("PTAB_CONTENT_DEADLINE_SECONDS", raw)
        assert deadline_module.content_deadline_seconds() == expected


class TestRetryInsideTheDeadline:
    async def test_a_429_is_retried_while_there_is_room(self, service, clock):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(429) if len(calls) == 1 else httpx.Response(200, json={})

        async with _client(handler) as client:
            response = await service._post_with_retry(
                client, "https://x/ocr", deadline=Deadline(85, clock=clock))

        assert response.status_code == 200
        assert len(calls) == 2

    async def test_a_5xx_retry_that_would_not_fit_is_not_taken(self, service, clock):
        """Budget 4 s: the first backoff (~1.1-1.5 s) leaves room for one more
        attempt; the second (~2.1-2.5 s) would not, so the last status comes
        back after two attempts instead of three."""
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(503)

        async with _client(handler) as client:
            response = await service._post_with_retry(
                client, "https://x/ocr", deadline=Deadline(4.0, clock=clock))

        assert response.status_code == 503
        assert len(calls) == 2
        assert len(clock.slept) == 1

    async def test_without_room_a_transport_failure_becomes_deadline_exceeded(
            self, service, clock):
        def handler(request):
            clock.t += 3.0  # the failed attempt itself used most of the budget
            raise httpx.ConnectError("reset")

        async with _client(handler) as client:
            with pytest.raises(DeadlineExceeded):
                await service._post_with_retry(
                    client, "https://x/files", deadline=Deadline(4.0, clock=clock))

    async def test_no_attempt_is_started_on_a_spent_deadline(self, service, clock):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(200, json={})

        spent = Deadline(85, clock=clock)
        clock.t += 84.5
        async with _client(handler) as client:
            with pytest.raises(DeadlineExceeded):
                await service._post_with_retry(client, "https://x/ocr", deadline=spent)

        assert calls == []

    async def test_a_hung_attempt_is_cut_at_the_deadline(self, service, monkeypatch):
        """Real (tiny) time here: wait_for has to fire on the event loop."""
        monkeypatch.setattr(OCRService, "_MIN_ATTEMPT_SECONDS", 0.01)

        class Hang(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                await asyncio.Event().wait()

        async with httpx.AsyncClient(transport=Hang()) as client:
            with pytest.raises(DeadlineExceeded):
                await service._post_with_retry(
                    client, "https://x/ocr", deadline=Deadline(0.2))

    async def test_without_a_deadline_the_old_bounds_hold(self, service, clock):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(503)

        async with _client(handler) as client:
            response = await service._post_with_retry(client, "https://x/ocr")

        assert response.status_code == 503
        assert len(calls) == service._RETRY_ATTEMPTS


class TestEndToEnd:
    async def test_extract_reports_a_spent_deadline_as_its_own_error(
            self, service, clock, monkeypatch):
        real = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: real(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"id": "f"})),
            **k))
        spent = Deadline(85, clock=clock)
        clock.t += 85

        result = await service.extract_document_content(
            b"%PDF-1.4", 3, "IPR2024-01353", "1", deadline=spent)

        assert result["success"] is False
        assert result["error"] == "Deadline exceeded"
        assert "$" not in result["message"]

    async def test_a_spent_deadline_does_not_count_toward_the_ocr_breaker(self, monkeypatch):
        from src.ptab_mcp.api.ptab_client import PTABClient
        from src.ptab_mcp.tools import documents as documents_module

        client = PTABClient(api_key="test-key-not-a-real-credential")

        class _FakeOCR:
            async def extract_document_content(self, **kwargs):
                return {"success": False, "error": "Deadline exceeded", "message": "m"}

        monkeypatch.setattr(documents_module, "_client", lambda: client)
        monkeypatch.setattr(documents_module, "ocr_service", _FakeOCR())
        monkeypatch.setattr(documents_module, "get_authenticated_identity", lambda: None)

        for _ in range(client.mistral_circuit_breaker.failure_threshold + 1):
            await documents_module._try_mistral_extraction(b"%PDF", 1, "IPR2024-01353", "1", None)

        assert client.mistral_circuit_breaker.get_state()["state"] == "closed"

    async def test_docling_is_skipped_when_the_budget_is_nearly_spent(self, monkeypatch, clock):
        from src.ptab_mcp.tools import documents as documents_module

        called = []

        class _Docling:
            max_pages = 20

            def is_available(self):
                return True

            def within_page_limit(self, n):
                return True

            async def extract(self, *a, **k):
                called.append(1)
                return "text"

        async def progress(*a):
            return None

        monkeypatch.setattr(documents_module, "docling_client", _Docling())
        nearly_spent = Deadline(85, clock=clock)
        clock.t += 83

        text = await documents_module._try_docling_extraction(
            b"%PDF", 3, "1", progress, nearly_spent)

        assert text == "" and called == []

    async def test_the_tool_hands_one_deadline_to_the_extraction_tiers(self, monkeypatch):
        from unittest.mock import AsyncMock, Mock

        from src.ptab_mcp.tools import documents as documents_module

        monkeypatch.setenv("PTAB_CONTENT_DEADLINE_SECONDS", "60")
        client = Mock()
        docket = {"count": 1, "patentTrialDocumentDataBag": [{
            "trialNumber": "IPR2024-00864",
            "documentData": {"documentIdentifier": "171263180",
                             "fileDownloadURI": "https://api.uspto.gov/x.pdf"}}]}
        client.search_all_trial_documents = AsyncMock(return_value=docket)
        client.search_trial_documents = AsyncMock(return_value=docket)
        client.download_trial_document = AsyncMock(return_value=b"%PDF-not-real")
        monkeypatch.setattr(documents_module, "_client", lambda: client)
        seen = {}

        async def fake_tiers(*args, **kwargs):
            seen["deadline"] = args[7] if len(args) > 7 else kwargs.get("deadline")
            return "text " * 50, "pypdf2", 0.0, {}

        monkeypatch.setattr(documents_module, "_run_extraction_tiers", fake_tiers)

        await documents_module.ptab_get_document_content(
            document_id="171263180", identifier="IPR2024-00864")

        assert isinstance(seen["deadline"], Deadline)
        assert seen["deadline"].seconds == 60.0
        assert 0 < seen["deadline"].remaining() <= 60.0
