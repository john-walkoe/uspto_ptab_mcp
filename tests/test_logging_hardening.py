"""Tests for the content-minimization logging posture.

Covers the three guarantees:
1. The sink-level SanitizingFilter scrubs secrets/credentials from every
   record regardless of which logger emitted it (raw logging.getLogger
   included), message and traceback alike.
2. Extraction code paths log character counts, never extracted/OCR text.
3. Auth-failure paths log an event but never the presented key/token.
"""

import io
import logging
import re
from pathlib import Path

import pytest

from ptab_mcp.shared.log_sanitizer import SanitizingFilter

SRC_DIR = Path(__file__).parent.parent / "src" / "ptab_mcp"

# 30 lowercase letters — matches the USPTO API key shape the sanitizer masks
PLANTED_SECRET = "abcdefghijklmnopqrstuvwxyzabcd"
PLANTED_LINK_HASH = "deadbeefdeadbeefdeadbeef"  # sha256[:24]-style hex
PLANTED_QUERY_URL = (
    "https://api.uspto.gov/api/v1/patent/trials/proceedings/search"
    "?petitionerName=Apple+Inc"
)


def _capture_logger(name: str):
    """Raw logging.getLogger wired to a StringIO handler with the sink filter."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SanitizingFilter())
    raw_logger = logging.getLogger(name)
    raw_logger.setLevel(logging.DEBUG)
    raw_logger.handlers = [handler]
    raw_logger.propagate = False
    return raw_logger, stream


class TestSinkFilter:
    """SanitizingFilter must scrub records at the handler, not the call site."""

    def test_scrubs_secret_query_and_link_hash_from_raw_logger(self):
        raw_logger, stream = _capture_logger("test_raw_bypass")

        raw_logger.info(
            f"key={PLANTED_SECRET} url={PLANTED_QUERY_URL} "
            f"link=/download/persistent/{PLANTED_LINK_HASH}"
        )
        output = stream.getvalue()

        assert PLANTED_SECRET not in output
        assert "petitionerName=Apple" not in output
        assert PLANTED_LINK_HASH not in output
        assert "[LINK_HASH]" in output
        assert "[QUERY_REDACTED]" in output

    def test_scrubs_exception_tracebacks(self):
        # Handlers format exc_info AFTER filters run — the filter must
        # pre-render and sanitize the traceback text.
        raw_logger, stream = _capture_logger("test_raw_exc")

        try:
            raise RuntimeError(f"boom {PLANTED_SECRET}")
        except RuntimeError:
            raw_logger.error("operation failed", exc_info=True)
        output = stream.getvalue()

        assert "operation failed" in output
        assert "RuntimeError" in output
        assert PLANTED_SECRET not in output

    def test_setup_logging_attaches_filter_to_all_handlers(self):
        from ptab_mcp.config import log_config

        root = logging.getLogger()
        before = list(root.handlers)
        was_configured = log_config._configured
        log_config._configured = False
        try:
            log_config.setup_logging(log_level="INFO")
            added = [h for h in root.handlers if h not in before]
            assert added, "setup_logging added no handlers"
            for handler in added:
                assert any(
                    isinstance(f, SanitizingFilter) for f in handler.filters
                ), f"handler {handler} missing SanitizingFilter"
        finally:
            for h in [h for h in root.handlers if h not in before]:
                root.removeHandler(h)
            log_config._configured = was_configured


class TestExtractionLogsCountsNotContent:
    """No extraction path may interpolate raw document/OCR text into a log."""

    # f-string interpolation of a raw text variable; {len(text)} does not match
    _CONTENT_INTERPOLATION = re.compile(
        r'logger\.\w+\([^)]*\{(extracted_text|full_content|page_text|ocr_text|markdown|text)\}'
    )

    @pytest.mark.parametrize("relative_path", [
        "services/ocr_service.py",
        "api/docling_client.py",
        "main.py",
    ])
    def test_no_raw_text_interpolation_in_log_calls(self, relative_path):
        source = (SRC_DIR / relative_path).read_text(encoding="utf-8")
        matches = self._CONTENT_INTERPOLATION.findall(source)
        assert not matches, (
            f"{relative_path} logs raw extracted text variable(s): {matches} — "
            "log character counts, never content"
        )


class TestAuthFailureLogging:
    """Auth failures log an event and never the presented credential."""

    @pytest.mark.asyncio
    async def test_proxy_token_failure_logs_event_not_token(self, caplog):
        from starlette.requests import Request
        from fastapi import HTTPException
        from ptab_mcp.proxy.server import ProxyTokenDependency

        presented = "totally-wrong-token-value-123456789"
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/register-download",
            "query_string": b"",
            "headers": [(b"x-proxy-token", presented.encode())],
        }
        request = Request(scope)

        with caplog.at_level(logging.WARNING):
            with pytest.raises(HTTPException) as exc_info:
                await ProxyTokenDependency()(request)

        assert exc_info.value.status_code == 401
        assert "Proxy token auth failed" in caplog.text
        assert presented not in caplog.text

    @pytest.mark.asyncio
    async def test_api_key_failure_logs_event_not_key(self, caplog, monkeypatch):
        from ptab_mcp.main import APIKeyAuthMiddleware

        monkeypatch.setenv("INTERNAL_AUTH_SECRET", "expected-secret-value")
        presented = "wrong-api-key-abcdef"
        sent = []

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            sent.append(message)

        async def inner_app(scope, receive, send):
            raise AssertionError("request must not reach the inner app")

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "query_string": b"",
            "headers": [(b"x-api-key", presented.encode())],
            "server": ("127.0.0.1", 8765),
            "scheme": "http",
        }

        with caplog.at_level(logging.WARNING):
            await APIKeyAuthMiddleware(inner_app)(scope, receive, send)

        start = next(m for m in sent if m["type"] == "http.response.start")
        assert start["status"] == 401
        assert "HTTP auth failed" in caplog.text
        assert presented not in caplog.text
