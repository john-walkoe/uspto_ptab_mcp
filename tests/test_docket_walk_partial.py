"""Docket-walk honesty and the OCR circuit breaker (fleet review 2026-09-03).

The trial docket walk used to swallow a first-page error and to blame the
max_docs safety cap for a mid-walk upstream failure, so a partial read reached
the model as "document not found". The OCR breaker was constructed and
reported on the health route but never invoked.
"""

import httpx
import pytest

from src.ptab_mcp.api.ptab_client import PTABClient
from src.ptab_mcp.shared.circuit_breaker import CircuitBreakerOpenError

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client():
    return PTABClient(api_key="test-key-not-a-real-credential")


# ---------------------------------------------------------------------------
# The docket walk tells the truth about a partial read
# ---------------------------------------------------------------------------

async def test_first_page_error_is_returned_not_treated_as_empty(client):
    async def fake_page(trial_number, offset=0, limit=100, **kwargs):
        return {"error": "Service temporarily unavailable", "status_code": 503}

    client.search_trial_documents = fake_page
    result = await client.search_all_trial_documents("IPR2024-01353")

    assert result["error"] == "Service temporarily unavailable"
    assert "docket_truncated" not in result
    assert "patentTrialDocumentDataBag" not in result


async def test_later_page_failure_is_marked_partial_not_truncated(client):
    async def fake_page(trial_number, offset=0, limit=100, **kwargs):
        if offset == 0:
            return {
                "count": 300,
                "patentTrialDocumentDataBag": [{"n": i} for i in range(100)],
            }
        return {"error": "Service temporarily unavailable", "status_code": 503}

    client.search_trial_documents = fake_page
    result = await client.search_all_trial_documents("IPR2024-01353")

    assert result["docket_partial"] is True
    assert result["docket_partial_at"] == 100
    assert result["docket_total"] == 300
    assert "failed upstream" in result["docket_partial_note"]
    # The safety cap did NOT cut this walk short and must not be blamed.
    assert "docket_truncated" not in result


async def test_safety_cap_still_reports_truncation(client):
    async def fake_page(trial_number, offset=0, limit=100, **kwargs):
        return {
            "count": 900,
            "patentTrialDocumentDataBag": [{"n": offset + i} for i in range(100)],
        }

    client.search_trial_documents = fake_page
    result = await client.search_all_trial_documents("IPR2024-01353", max_docs=200)

    assert result["docket_truncated"] is True
    assert result["docket_truncated_at"] == 200
    assert "docket_partial" not in result


async def test_ocr_breaker_opens_on_repeated_provider_failures(monkeypatch, client):
    """The OCR breaker was constructed and reported on the health route but
    never invoked: the OCR service returns an error ENVELOPE, and the breaker
    only counts raises. Drive it open through real failures."""
    from src.ptab_mcp.tools import documents as documents_module

    calls = {"n": 0}

    class _FakeOCR:
        async def extract_document_content(self, **kwargs):
            calls["n"] += 1
            return {"success": False, "error": "Extraction failed",
                    "message": "upstream said no"}

    monkeypatch.setattr(documents_module, "_client", lambda: client)
    monkeypatch.setattr(documents_module, "ocr_service", _FakeOCR())
    monkeypatch.setattr(documents_module, "get_authenticated_identity", lambda: None)

    threshold = client.mistral_circuit_breaker.failure_threshold
    for _ in range(threshold):
        result = await documents_module._try_mistral_extraction(
            b"%PDF", 1, "IPR2024-01353", "1", None
        )
        assert result["error"] == "Extraction failed"

    assert client.mistral_circuit_breaker.get_state()["state"] == "open"

    # Open circuit: the provider is not called again, and the caller gets a
    # distinct, temporary-sounding failure.
    before = calls["n"]
    result = await documents_module._try_mistral_extraction(
        b"%PDF", 1, "IPR2024-01353", "1", None
    )
    assert calls["n"] == before
    assert result["error"] == "OCR temporarily unavailable"


async def test_ocr_breaker_ignores_config_and_quota_errors(monkeypatch, client):
    """A missing key or our own per-caller throttle is not a provider outage
    and must not push the breaker toward OPEN."""
    from src.ptab_mcp.tools import documents as documents_module

    class _FakeOCR:
        async def extract_document_content(self, **kwargs):
            return {"success": False, "error": "Rate limit exceeded",
                    "message": "slow down"}

    monkeypatch.setattr(documents_module, "_client", lambda: client)
    monkeypatch.setattr(documents_module, "ocr_service", _FakeOCR())
    monkeypatch.setattr(documents_module, "get_authenticated_identity", lambda: None)

    for _ in range(client.mistral_circuit_breaker.failure_threshold + 2):
        result = await documents_module._try_mistral_extraction(
            b"%PDF", 1, "IPR2024-01353", "1", None
        )
        assert result["error"] == "Rate limit exceeded"

    assert client.mistral_circuit_breaker.get_state()["state"] == "closed"
    assert client.mistral_circuit_breaker.failure_count == 0


async def test_circuit_breaker_open_error_is_raised_not_stubbed(client):
    """Regression guard for tests that used to set `state = OPEN` by hand: the
    breaker must reach OPEN by counting real failures."""
    breaker = client.trials_circuit_breaker

    async def _boom():
        raise httpx.ConnectError("upstream down")

    for _ in range(breaker.failure_threshold):
        with pytest.raises(httpx.ConnectError):
            await breaker.call(_boom)

    with pytest.raises(CircuitBreakerOpenError):
        await breaker.call(_boom)


async def test_not_found_message_says_partial_read():
    from src.ptab_mcp.tools.documents import _not_found_message

    message = _not_found_message("123", "IPR2024-01353", {
        "docket_partial": True,
        "docket_partial_note": "a later page failed upstream",
    })
    assert "failed upstream" in message
    assert "may still be valid" in message
