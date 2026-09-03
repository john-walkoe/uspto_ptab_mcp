"""Resilience gaps where the primitive existed but was not wired.

Covers:
  * the HALF_OPEN probe permit the circuit breaker's own comment claimed and
    the code never implemented, so every caller arriving during recovery was
    admitted and burned a full retry budget against a still-down upstream;
  * the shared cross-process limiter's two `while True` acquire loops, which
    are crash-safe (flock is kernel-released on process death) but had no
    answer for a process that HANGS while holding a slot;
  * the two unguarded env parses in DoclingClient, constructed at import of
    every tool module, so DOCLING_TIMEOUT=5m took the server down with a
    float() traceback before a single tool registered;
  * an OCR tier failure being reported to the caller as a property of the
    document ("this is a scanned image") rather than as an outage.
"""

import asyncio
import json

import pytest

from src.ptab_mcp.shared.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError


class TestHalfOpenProbeLimit:
    async def test_only_one_probe_is_admitted_while_half_open(self):
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0, name="T")

        async def boom():
            raise RuntimeError("upstream down")

        with pytest.raises(RuntimeError):
            await breaker.call(boom)
        assert breaker.state.value == "open"

        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_probe():
            started.set()
            await release.wait()
            return "ok"

        probe = asyncio.create_task(breaker.call(slow_probe))
        await started.wait()

        # A second caller arriving during the probe must fail fast rather than
        # queue behind it and spend its own retry budget.
        with pytest.raises(CircuitBreakerOpenError):
            await breaker.call(slow_probe)

        release.set()
        assert await probe == "ok"

    async def test_the_permit_is_returned_after_a_probe_fails(self):
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0, name="T2")

        async def boom():
            raise RuntimeError("still down")

        with pytest.raises(RuntimeError):
            await breaker.call(boom)
        with pytest.raises(RuntimeError):
            await breaker.call(boom)  # the HALF_OPEN probe; re-opens the circuit

        assert breaker._probes_in_flight == 0

    async def test_three_successes_still_close_the_circuit(self):
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0, name="T3")

        async def boom():
            raise RuntimeError("down")

        async def ok():
            return "ok"

        with pytest.raises(RuntimeError):
            await breaker.call(boom)
        for _ in range(breaker.HALF_OPEN_SUCCESSES_TO_CLOSE):
            await breaker.call(ok)

        assert breaker.state.value == "closed"


class TestSharedLimiterWaitCeiling:
    async def test_a_stuck_slot_holder_raises_instead_of_hanging(self, monkeypatch, tmp_path):
        from src.ptab_mcp.shared import uspto_shared_rate_limiter as srl

        monkeypatch.setattr(srl, "_MAX_WAIT_SECONDS", 0.2)
        limiter = srl.SharedUsptoRateLimiter(str(tmp_path))
        # No slot will ever become free.
        monkeypatch.setattr(limiter, "_try_acquire_any_slot", lambda: None)

        with pytest.raises(TimeoutError, match="concurrency slot"):
            await limiter._acquire_slot()

    async def test_a_starved_token_bucket_raises_instead_of_hanging(self, monkeypatch, tmp_path):
        from src.ptab_mcp.shared import uspto_shared_rate_limiter as srl

        monkeypatch.setattr(srl, "_MAX_WAIT_SECONDS", 0.2)
        limiter = srl.SharedUsptoRateLimiter(str(tmp_path))
        monkeypatch.setattr(limiter, "_try_take_token", lambda: False)

        with pytest.raises(TimeoutError, match="token"):
            await limiter._acquire_token()


class TestDoclingEnvParsing:
    def test_a_garbage_timeout_falls_back_instead_of_crashing_import(self, monkeypatch):
        from src.ptab_mcp.api.docling_client import DoclingClient

        monkeypatch.setenv("DOCLING_TIMEOUT", "5m")
        monkeypatch.setenv("DOCLING_MAX_PAGES", "twenty")

        client = DoclingClient()

        assert isinstance(client.timeout, float)
        assert isinstance(client.max_pages, int)

    def test_a_valid_override_is_honored(self, monkeypatch):
        from src.ptab_mcp.api.docling_client import DoclingClient

        monkeypatch.setenv("DOCLING_TIMEOUT", "45")
        monkeypatch.setenv("DOCLING_MAX_PAGES", "7")

        client = DoclingClient()

        assert client.timeout == 45.0
        assert client.max_pages == 7


class TestOcrOutageIsNotADocumentProperty:
    def test_a_tier_failure_reason_reaches_the_caller(self):
        from src.ptab_mcp.tools.documents import _all_tiers_failed_response

        result = json.loads(_all_tiers_failed_response(
            "170603095", "IPR2023-01035",
            {"partial_text": "", "body_chars": 0},
            tier_failures=[{"tier": "mistral_ocr", "error": "Payment required",
                            "message": "billing lapse"}],
        ))

        assert result["tier_failures"][0]["error"] == "Payment required"
        assert "OCR tier may be unavailable" in result["error"]

    def test_without_a_tier_failure_the_scanned_document_diagnosis_stands(self):
        from src.ptab_mcp.tools.documents import _all_tiers_failed_response

        result = json.loads(_all_tiers_failed_response(
            "170603095", "IPR2023-01035", {"partial_text": "", "body_chars": 0}))

        assert "scanned/image-based" in result["error"]
        assert "tier_failures" not in result
