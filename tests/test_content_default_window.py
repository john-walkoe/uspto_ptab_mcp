"""PTAB_get_document_content windows the FIRST read by default.

Defect 5 from the 2026-09-03 skill QA ledger: called with no max_chars on a
59,619-character decision, the tool returned the whole 72,283-character
envelope and the client replaced it with a truncation error the server never
saw, so `_bounds` never mattered. The default window is the response budget
now (shrunk further if the serialized envelope would still exceed it), with
`_window.has_more` and `_window.next_offset` carrying the rest.

Hermetic: the extraction waterfall and the API client are patched at the
module boundary, no network and no real PDFs.
"""

import json
from unittest.mock import AsyncMock, Mock

import pytest

from src.ptab_mcp.shared import response_bounds
from src.ptab_mcp.shared.response_bounds import WINDOW_KEY
from src.ptab_mcp.tools import documents as documents_module


@pytest.fixture
def _content_runtime(monkeypatch):
    """The document-content tool's collaborators, patched at the module
    boundary (same seam as tests/test_extraction_fixes.py)."""
    client = Mock()
    one_document_docket = {
        "count": 1,
        "patentTrialDocumentDataBag": [{
            "trialNumber": "IPR2024-00864",
            "documentData": {
                "documentIdentifier": "171263180",
                "documentTitleText": "Final Written Decision (Public)",
                "fileDownloadURI": "https://api.uspto.gov/x.pdf",
            },
        }],
    }
    client.search_all_trial_documents = AsyncMock(return_value=one_document_docket)
    client.search_trial_documents = AsyncMock(return_value=one_document_docket)
    client.download_trial_document = AsyncMock(return_value=b"%PDF-not-real")
    monkeypatch.setattr(documents_module, "_client", lambda: client)
    return client


def _install_text(monkeypatch, text):
    async def _fake_tiers(*args, **kwargs):
        return text, "pypdf2", 0.0, {}

    monkeypatch.setattr(documents_module, "_run_extraction_tiers", _fake_tiers)


#: The length of the sealed IPR2024-00864 decision whose unwindowed envelope
#: (72,283 characters) the client refused on 2026-09-03.
_MEASURED_DECISION_CHARS = 59_619


async def _content(**kwargs):
    return await documents_module.ptab_get_document_content(
        document_id="171263180", identifier="IPR2024-00864", **kwargs
    )


class TestDefaultContentWindow:
    async def test_a_first_read_with_no_max_chars_fits_the_budget(
        self, _content_runtime, monkeypatch
    ):
        pages = "\n\n".join(
            f"=== PAGE {i} ===\n{'word ' * 240}" for i in range(1, 51)
        )
        assert len(pages) > _MEASURED_DECISION_CHARS
        _install_text(monkeypatch, pages)

        raw = await _content()

        assert len(raw) <= response_bounds.response_char_budget()
        result = json.loads(raw)
        assert result[WINDOW_KEY]["has_more"] is True
        assert result[WINDOW_KEY]["total"] == len(pages)
        assert result["character_count"] == len(result["text"])

    async def test_the_cursor_still_reaches_the_whole_document(
        self, _content_runtime, monkeypatch
    ):
        pages = "\n\n".join(
            f"=== PAGE {i} ===\n{'word ' * 240}" for i in range(1, 51)
        )
        _install_text(monkeypatch, pages)

        seen, offset, guard = [], 0, 0
        while True:
            guard += 1
            assert guard < 100
            page = json.loads(await _content(char_offset=offset))
            seen.append(page["text"])
            marker = page.get(WINDOW_KEY)
            if not marker or not marker["has_more"]:
                break
            offset = marker["next_offset"]

        assert "".join(seen) == pages

    async def test_an_explicit_max_chars_is_still_honored(
        self, _content_runtime, monkeypatch
    ):
        """The default is conservative; a caller who asks for more gets more,
        up to the content budget."""
        pages = "\n\n".join(
            f"=== PAGE {i} ===\n{'word ' * 240}" for i in range(1, 51)
        )
        _install_text(monkeypatch, pages)

        default = json.loads(await _content())
        explicit = json.loads(await _content(max_chars=len(pages)))

        assert len(explicit["text"]) == len(pages)
        assert len(default["text"]) < len(explicit["text"])
        assert WINDOW_KEY not in explicit

    async def test_a_short_document_is_still_a_no_op(
        self, _content_runtime, monkeypatch
    ):
        _install_text(monkeypatch, "=== PAGE 1 ===\nshort")

        result = json.loads(await _content())

        assert WINDOW_KEY not in result
        assert response_bounds.BOUNDS_KEY not in result

    async def test_the_default_follows_the_configured_budget(
        self, _content_runtime, monkeypatch
    ):
        pages = "\n\n".join(
            f"=== PAGE {i} ===\n{'word ' * 240}" for i in range(1, 51)
        )
        _install_text(monkeypatch, pages)
        monkeypatch.setenv(response_bounds.ENV_MAX_RESPONSE_CHARS, "12000")

        raw = await _content()

        assert len(raw) <= 12_000
        assert json.loads(raw)[WINDOW_KEY]["has_more"] is True

    async def test_a_disabled_guard_still_windows_nothing(
        self, _content_runtime, monkeypatch
    ):
        """USPTO_RESPONSE_BOUNDS_ENABLED=false is an explicit opt out of the
        whole guard, default window included."""
        pages = "\n\n".join(
            f"=== PAGE {i} ===\n{'word ' * 240}" for i in range(1, 51)
        )
        _install_text(monkeypatch, pages)
        monkeypatch.setenv(response_bounds.ENV_ENABLED, "false")

        result = json.loads(await _content())

        assert result["text"] == pages
        assert WINDOW_KEY not in result
