"""Hermetic tests for the extraction / paging / truncation-honesty fixes that
shipped with the shared response-size guard.

Each test pins ONE previously-silent lie:
- a missing pageCount defaulting to 50, so `truncated = 50 > 50` read false
  and a capped 300-page exhibit looked like a complete 50-page document;
- the free pypdf tier running unbounded over every page, with no page
  markers for the text-window helper to snap to;
- sub-100-char pypdf output being discarded, so an all-tiers-failed response
  reported `text: ""` and never mentioned the partial text existed;
- an envelope echoing the REQUESTED limit while the client clamped it to 100;
- the 500-document docket walk stopping silently, so a later paper surfaced
  as "not found".

No network, no API key, no real PDFs beyond a tiny generated one.
"""

import json
from unittest.mock import AsyncMock, Mock

import pytest

from src.ptab_mcp.shared.response_bounds import BOUNDS_KEY, WINDOW_KEY
from src.ptab_mcp.tools.documents import (
    _all_tiers_failed_response,
    _coerce_page_count,
    _documents_paging_envelope,
    _not_found_message,
    _pdf_page_count,
    _resolve_page_count,
    _try_pypdf2_extraction,
    pypdf_max_pages,
)


def _pdf_bytes(pages: int, text: str = "Final Written Decision text.") -> bytes:
    """A real multi-page PDF built with the PDF library already in the deps."""
    from io import BytesIO

    import pypdf

    writer = pypdf.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# (a) page count: never fabricate 50
# ---------------------------------------------------------------------------

class TestPageCountResolution:
    def test_missing_page_count_is_none_not_fifty(self):
        # THE bug: every one of these used to come back as 50.
        assert _coerce_page_count(None) is None
        assert _coerce_page_count("") is None
        assert _coerce_page_count("not-a-number") is None
        assert _coerce_page_count(0) is None
        assert _coerce_page_count(-3) is None
        assert _coerce_page_count(True) is None
        assert _coerce_page_count({}) is None

    def test_usable_page_counts_pass_through(self):
        assert _coerce_page_count(300) == 300
        assert _coerce_page_count("300") == 300
        assert _coerce_page_count(" 42 ") == 42

    def test_real_count_is_recovered_from_the_pdf_bytes(self):
        pdf = _pdf_bytes(7)

        assert _pdf_page_count(pdf) == 7
        # Metadata is missing, so the local count wins — and it is the TRUTH,
        # not the old fabricated 50.
        assert _resolve_page_count(None, pdf) == (7, "pdf_bytes")

    def test_metadata_wins_when_present(self):
        assert _resolve_page_count(300, _pdf_bytes(2)) == (300, "metadata")

    def test_unresolvable_is_marked_unknown_never_guessed(self):
        count, source = _resolve_page_count(None, b"not a pdf at all")

        assert count is None
        assert source == "unknown"

    def test_unparseable_bytes_yield_no_local_count(self):
        assert _pdf_page_count(b"") is None
        assert _pdf_page_count(b"%PDF-1.4 truncated") is None


# ---------------------------------------------------------------------------
# (b) free tier: page cap + page markers
# ---------------------------------------------------------------------------

class TestPypdfPageCap:
    def test_default_cap_and_env_override(self, monkeypatch):
        monkeypatch.delenv("PYPDF_MAX_PAGES", raising=False)
        assert pypdf_max_pages() == 200

        monkeypatch.setenv("PYPDF_MAX_PAGES", "3")
        assert pypdf_max_pages() == 3

        monkeypatch.setenv("PYPDF_MAX_PAGES", "garbage")
        assert pypdf_max_pages() == 200

    def test_extraction_is_capped_and_marked(self, monkeypatch):
        monkeypatch.setenv("PYPDF_MAX_PAGES", "4")
        status = {}

        _try_pypdf2_extraction(_pdf_bytes(10), status)

        assert status["pages_extracted"] == 4
        assert status["page_count"] == 10
        assert status["truncated"] is True
        assert "first 4" in status["truncation_note"]
        assert "PYPDF_MAX_PAGES" in status["truncation_note"]

    def test_page_headers_are_emitted_for_every_page(self, monkeypatch):
        monkeypatch.setenv("PYPDF_MAX_PAGES", "200")
        status = {}

        _try_pypdf2_extraction(_pdf_bytes(3), status)
        text = status["partial_text"]

        # Blank pages keep their header rather than vanishing, so the page
        # numbers never imply a complete document that isn't there.
        assert text.count("=== PAGE ") == 3
        assert text.startswith("=== PAGE 1 ===")
        assert "=== PAGE 3 ===" in text
        assert "[no text recovered from this page]" in text

    def test_page_markers_drive_page_edge_windows(self, monkeypatch):
        """The headers exist so the shared text-window helper can snap the
        window edges to page boundaries instead of splitting a page in half."""
        from src.ptab_mcp.shared.response_bounds import window_text

        monkeypatch.setenv("PYPDF_MAX_PAGES", "200")
        status = {}
        _try_pypdf2_extraction(_pdf_bytes(6), status)

        result = window_text(status["partial_text"], offset=0, max_chars=100)

        assert result[WINDOW_KEY]["edges"] == "page"
        assert result[WINDOW_KEY]["unit"] == "char"
        assert status["partial_text"][result[WINDOW_KEY]["next_offset"]:].startswith(
            "=== PAGE "
        )

    def test_page_headers_do_not_count_toward_the_usability_threshold(self, monkeypatch):
        """A 40-page scanned PDF emits ~600 chars of headers alone. If those
        counted, a document with NO text layer would look extractable and OCR
        would never be reached."""
        monkeypatch.setenv("PYPDF_MAX_PAGES", "200")
        status = {}

        result = _try_pypdf2_extraction(_pdf_bytes(40), status)

        assert len(status["partial_text"]) > 100  # headers alone exceed it
        assert status["body_chars"] == 0
        assert result == ""  # escalates to OCR, correctly


# ---------------------------------------------------------------------------
# (c) partial text is never silently discarded
# ---------------------------------------------------------------------------

class TestPartialTextPreserved:
    def test_all_tiers_failed_reports_the_partial_text(self):
        status = {
            "partial_text": "=== PAGE 1 ===\nIPR2024",
            "body_chars": 7,
            "pages_extracted": 1,
        }

        response = json.loads(_all_tiers_failed_response("171303338", "IPR2024-01353", status))

        assert response["text"] == "=== PAGE 1 ===\nIPR2024"
        assert response["partial_text"] is True
        assert response["character_count"] == len("=== PAGE 1 ===\nIPR2024")
        assert response["pages_extracted"] == 1
        assert "7 character(s)" in response["extraction_note"]
        assert "PARTIAL" in response["extraction_note"]

    def test_all_tiers_failed_with_nothing_recovered_is_unchanged(self):
        response = json.loads(_all_tiers_failed_response("171303338", "IPR2024-01353", {}))

        assert response["text"] == ""
        assert "partial_text" not in response
        assert "extraction_note" not in response

    def test_mid_extraction_failure_is_surfaced(self):
        response = json.loads(_all_tiers_failed_response(
            "171303338", "IPR2024-01353",
            {"partial_text": "", "extraction_error": "pypdf extraction aborted after 2 page(s)"},
        ))

        assert "aborted after 2 page(s)" in response["extraction_error"]

    def test_extraction_failure_still_returns_what_it_had(self, monkeypatch):
        """A PDF whose pages blow up part-way keeps the pages that worked."""
        import pypdf

        real_reader = pypdf.PdfReader
        pdf = _pdf_bytes(5)

        class _ExplodingPage:
            def extract_text(self):
                raise ValueError("boom")

        class _PartialReader:
            def __init__(self, stream):
                self._pages = list(real_reader(stream).pages)[:2] + [_ExplodingPage()]

            @property
            def pages(self):
                return self._pages

        monkeypatch.setattr(pypdf, "PdfReader", _PartialReader)
        status = {}

        result = _try_pypdf2_extraction(pdf, status)

        assert result == ""  # not usable, so the caller escalates
        assert status["pages_extracted"] == 2
        assert "aborted after 2 page(s)" in status["extraction_error"]
        assert status["partial_text"].count("=== PAGE ") == 2


# ---------------------------------------------------------------------------
# (d) the limit ACTUALLY applied
# ---------------------------------------------------------------------------

class TestPagingEnvelope:
    def test_trial_limit_is_reported_as_clamped(self):
        """The tool accepts up to 200; api/ptab_client.py clamps a document
        page to 100. The envelope used to echo the requested value."""
        payload = {"documents": [{"documentIdentifier": str(i)} for i in range(100)]}

        _documents_paging_envelope(
            payload, identifier_type="trial", limit_requested=150, offset=0,
            total_documents=430, total_is_docket_total=True,
        )

        paging = payload["paging"]
        assert paging["limit_requested"] == 150
        assert paging["limit_applied"] == 100
        assert paging["returned"] == 100
        assert paging["total"] == 430
        assert paging["has_more"] is True
        assert paging["next_offset"] == 100
        assert paging["total_source"] == "api_count"

    def test_last_page_has_no_next_offset(self):
        payload = {"documents": [{"documentIdentifier": str(i)} for i in range(30)]}

        _documents_paging_envelope(
            payload, identifier_type="trial", limit_requested=50, offset=400,
            total_documents=430, total_is_docket_total=True,
        )

        assert payload["paging"]["has_more"] is False
        assert payload["paging"]["next_offset"] is None

    def test_unfiltered_page_reports_scanned_equal_to_returned(self):
        payload = {"documents": [{"documentIdentifier": str(i)} for i in range(50)]}

        _documents_paging_envelope(
            payload, identifier_type="trial", limit_requested=50, offset=0,
            total_documents=172, total_is_docket_total=True, scanned=50,
            client_side_filters={},
        )

        paging = payload["paging"]
        assert paging["scanned"] == 50
        assert paging["returned"] == 50
        assert paging["next_offset"] == 50
        assert "client_side_filters" not in paging
        assert "filter_note" not in paging

    def test_filtered_empty_page_advances_past_the_scanned_rows(self):
        """IPR2015-00040, document_title='Final Written Decision', limit=3:
        0 matches in a 3-row page used to yield has_more=true with
        next_offset=0 — a caller looping on next_offset never moved."""
        payload = {"documents": []}

        _documents_paging_envelope(
            payload, identifier_type="trial", limit_requested=3, offset=0,
            total_documents=172, total_is_docket_total=True, scanned=3,
            client_side_filters={"document_title": "Final Written Decision"},
        )

        paging = payload["paging"]
        assert paging["returned"] == 0
        assert paging["scanned"] == 3
        assert paging["has_more"] is True
        assert paging["next_offset"] == 3
        assert paging["client_side_filters"] == ["document_title"]
        assert "client_side_filters" in paging["filter_note"]

    def test_filtered_partial_page_advances_by_page_size_not_match_count(self):
        """IPR2015-00040, document_title='Petition', limit=100: 10 matches
        from a 100-row page. next_offset must be 100, not 10."""
        payload = {"documents": [{"documentIdentifier": str(i)} for i in range(10)]}

        _documents_paging_envelope(
            payload, identifier_type="trial", limit_requested=100, offset=0,
            total_documents=172, total_is_docket_total=True, scanned=100,
            client_side_filters={"document_title": "Petition"},
        )

        paging = payload["paging"]
        assert paging["returned"] == 10
        assert paging["scanned"] == 100
        assert paging["has_more"] is True
        assert paging["next_offset"] == 100

    def test_filtered_last_page_has_no_more(self):
        """offset=100 + 72 scanned rows reaches the 172-doc total even though
        only 2 of them matched."""
        payload = {"documents": [{"documentIdentifier": str(i)} for i in range(2)]}

        _documents_paging_envelope(
            payload, identifier_type="trial", limit_requested=100, offset=100,
            total_documents=172, total_is_docket_total=True, scanned=72,
            client_side_filters={"document_title": "Petition"},
        )

        paging = payload["paging"]
        assert paging["returned"] == 2
        assert paging["scanned"] == 72
        assert paging["has_more"] is False
        assert paging["next_offset"] is None

    def test_non_trial_total_is_not_passed_off_as_a_docket_total(self):
        """Appeals/interferences come from a non-paginating GET, so their
        total is a page size, not a docket total."""
        payload = {"documents": [{"documentIdentifier": "1"}]}

        _documents_paging_envelope(
            payload, identifier_type="appeal", limit_requested=50, offset=0,
            total_documents=2, total_is_docket_total=False,
        )

        paging = payload["paging"]
        assert paging["total"] is None
        assert paging["total_source"] == "returned_page"
        assert paging["has_more"] is False
        assert "does not paginate" in paging["note"] or "non-paginating" in paging["note"]
        # A client-side limit is applied exactly as asked for these types.
        assert paging["limit_applied"] == 50


class TestSearchPagingBlock:
    def test_block_reports_applied_limit_and_cursor(self):
        from src.ptab_mcp.util.search_runner import build_paging_block

        paging = build_paging_block(
            limit_requested=200, limit_applied=100, offset=100, returned=100,
            total=4312,
        )

        assert paging == {
            "limit_requested": 200,
            "limit_applied": 100,
            "offset": 100,
            "returned": 100,
            "total": 4312,
            "has_more": True,
            "next_offset": 200,
        }

    def test_unknown_total_never_claims_has_more(self):
        from src.ptab_mcp.util.search_runner import build_paging_block

        paging = build_paging_block(
            limit_requested=50, limit_applied=50, offset=0, returned=3, total=None,
        )

        assert paging["total"] is None
        assert paging["has_more"] is False
        assert paging["next_offset"] is None


# ---------------------------------------------------------------------------
# (e) the docket walk stops loudly
# ---------------------------------------------------------------------------

class TestDocketWalkTruncation:
    def _client(self, total: int, page_size: int = 100):
        from src.ptab_mcp.api.ptab_client import PTABClient

        client = PTABClient.__new__(PTABClient)

        async def _page(trial_number, offset=0, limit=100, sort_order="desc"):
            bag = [
                {"documentData": {"documentIdentifier": str(i)}}
                for i in range(offset, min(offset + page_size, total))
            ]
            return {"count": total, "patentTrialDocumentDataBag": bag}

        client.search_trial_documents = _page
        return client

    async def test_cap_is_marked(self):
        client = self._client(total=1200)

        result = await client.search_all_trial_documents("IPR2024-01353", max_docs=500)

        assert len(result["patentTrialDocumentDataBag"]) == 500
        assert result["docket_truncated"] is True
        assert result["docket_truncated_at"] == 500
        assert result["docket_total"] == 1200
        assert "1200 documents" in result["docket_truncation_note"]
        assert "PTAB_get_documents(offset=" in result["docket_truncation_note"]

    async def test_complete_walk_is_not_marked(self):
        client = self._client(total=230)

        result = await client.search_all_trial_documents("IPR2024-01353", max_docs=500)

        assert len(result["patentTrialDocumentDataBag"]) == 230
        assert "docket_truncated" not in result

    def test_not_found_message_says_the_walk_was_cut_short(self):
        truncated = {
            "docket_truncated": True,
            "docket_truncation_note": "This docket has 1200 documents; the walk stopped at 500.",
        }

        message = _not_found_message("171303338", "IPR2024-01353", truncated)

        assert "not found in IPR2024-01353" in message
        assert "1200 documents" in message
        assert "may still be valid" in message

    def test_not_found_message_is_plain_when_the_walk_completed(self):
        assert _not_found_message("171303338", "IPR2024-01353", {"count": 12}) == (
            "Document ID '171303338' not found in IPR2024-01353"
        )
        assert _not_found_message("171303338", "IPR2024-01353", None) == (
            "Document ID '171303338' not found in IPR2024-01353"
        )


# ---------------------------------------------------------------------------
# (h) the field-config fallback is no longer silent
# ---------------------------------------------------------------------------

class TestFieldSetFallbackMarking:
    def test_healthy_config_is_not_flagged(self):
        from pathlib import Path

        from src.ptab_mcp.config.field_manager import FieldManager

        manager = FieldManager(Path(__file__).resolve().parents[1] / "field_configs.yaml")

        assert manager.is_fallback() is False
        assert manager.fallback_note() is None

    def test_broken_config_is_flagged_with_an_explanation(self, tmp_path):
        from src.ptab_mcp.config.field_manager import FieldManager

        manager = FieldManager(tmp_path / "does_not_exist.yaml")

        assert manager.is_fallback() is True
        note = manager.fallback_note()
        assert "field_configs.yaml could not be loaded" in note
        assert "emergency field sets" in note
        # The label a response reports is IDENTICAL either way — that was the
        # whole problem, and the flag is what distinguishes them.
        assert manager.get_fields("trials_minimal")
        with pytest.raises(ValueError):
            manager.get_fields("trials_balanced")  # only *_minimal exists here


# ---------------------------------------------------------------------------
# The content tool end to end: page-count honesty + the text-window cursor
# ---------------------------------------------------------------------------

@pytest.fixture
def _content_runtime(monkeypatch):
    """Patch the document-content tool's collaborators at the module boundary."""
    from src.ptab_mcp.tools import documents as documents_module

    client = Mock()
    client.mistral_semaphore = AsyncMock()
    client.mistral_semaphore.__aenter__ = AsyncMock()
    client.mistral_semaphore.__aexit__ = AsyncMock()
    one_document_docket = {
        "count": 1,
        "patentTrialDocumentDataBag": [{
            "trialNumber": "IPR2024-01353",
            "documentData": {
                "documentIdentifier": "171303338",
                "documentTitleText": "Final Written Decision",
                # NOTE: no pageCount at all — the case the old default of 50
                # turned into a confident lie.
                "fileDownloadURI": "https://api.uspto.gov/x.pdf",
            },
        }],
    }
    client.search_all_trial_documents = AsyncMock(return_value=one_document_docket)
    # The tool resolves the paper by documentIdentifier before walking the
    # docket; a targeted query for this docket's only paper returns that row.
    client.search_trial_documents = AsyncMock(return_value=one_document_docket)
    client.download_trial_document = AsyncMock(return_value=b"%PDF-not-real")

    monkeypatch.setattr(documents_module, "_client", lambda: client)
    return client


async def test_content_reports_unknown_page_count_instead_of_fifty(
    _content_runtime, monkeypatch
):
    from src.ptab_mcp.tools import documents as documents_module

    async def _fake_tiers(*args, **kwargs):
        return "=== PAGE 1 ===\nBoard decision text.", "pypdf2", 0.0, {}

    monkeypatch.setattr(documents_module, "_run_extraction_tiers", _fake_tiers)

    result = json.loads(await documents_module.ptab_get_document_content(
        document_id="171303338", identifier="IPR2024-01353",
    ))

    assert result["page_count"] is None
    assert result["page_count_source"] == "unknown"
    assert "could not be determined" in result["page_count_note"]
    assert "50" not in str(result["page_count"])


async def test_content_windows_long_text_with_a_cursor(_content_runtime, monkeypatch):
    from src.ptab_mcp.tools import documents as documents_module

    pages = "\n\n".join(f"=== PAGE {i} ===\n{'word ' * 200}" for i in range(1, 41))

    async def _fake_tiers(*args, **kwargs):
        return pages, "mistral_ocr", 0.0, {}

    monkeypatch.setattr(documents_module, "_run_extraction_tiers", _fake_tiers)

    first = json.loads(await documents_module.ptab_get_document_content(
        document_id="171303338", identifier="IPR2024-01353", max_chars=3_000,
    ))

    window = first[WINDOW_KEY]
    assert window["edges"] == "page"
    assert window["unit"] == "char"
    assert window["total"] == len(pages)
    assert window["has_more"] is True
    assert first["character_count"] == len(first["text"])
    assert first[BOUNDS_KEY]["reason"] == "window"

    # The cursor walks the whole document without splitting a page.
    seen, offset, guard = [], 0, 0
    while True:
        guard += 1
        assert guard < 100
        page = json.loads(await documents_module.ptab_get_document_content(
            document_id="171303338", identifier="IPR2024-01353",
            char_offset=offset, max_chars=3_000,
        ))
        seen.append(page["text"])
        marker = page.get(WINDOW_KEY)
        if not marker or not marker["has_more"]:
            break
        offset = marker["next_offset"]

    assert "".join(seen) == pages


async def test_content_short_text_has_no_window_marker(_content_runtime, monkeypatch):
    from src.ptab_mcp.tools import documents as documents_module

    async def _fake_tiers(*args, **kwargs):
        return "=== PAGE 1 ===\nshort", "pypdf2", 0.0, {}

    monkeypatch.setattr(documents_module, "_run_extraction_tiers", _fake_tiers)

    result = json.loads(await documents_module.ptab_get_document_content(
        document_id="171303338", identifier="IPR2024-01353",
    ))

    assert WINDOW_KEY not in result
    assert BOUNDS_KEY not in result


# ---------------------------------------------------------------------------
# (f) search offset actually reaches the API, and the envelope pages
# ---------------------------------------------------------------------------

class TestSearchOffsetIsPlumbed:
    def _bag(self, n, start=0):
        return [{"trialNumber": f"IPR2024-{i:05d}"} for i in range(start, start + n)]

    async def test_offset_is_sent_in_the_request_body(self, mock_api_client):
        """`offset` was pinned to 0 in the request body, so no search tool
        could reach result 101 no matter what the caller passed."""
        from src.ptab_mcp.main import search_trials_minimal

        mock_api_client.search_trials.return_value = {
            "count": 4312, "patentTrialProceedingDataBag": self._bag(50, start=100)}

        result = json.loads(await search_trials_minimal(
            petitioner_name="Apple Inc", limit=50, offset=100))

        assert mock_api_client.search_trials.call_args.kwargs["pagination"] == {
            "offset": 100, "limit": 50
        }
        paging = result["paging"]
        assert paging["offset"] == 100
        assert paging["returned"] == 50
        # `count` is the API's TOTAL match count — it used to sit beside a
        # 50-row page with no has_more at all.
        assert result["count"] == 4312
        assert paging["total"] == 4312
        assert paging["has_more"] is True
        assert paging["next_offset"] == 150

    async def test_negative_offset_is_rejected(self, mock_api_client):
        from src.ptab_mcp.main import search_appeals_minimal

        result = json.loads(await search_appeals_minimal(appeal_number="2025000943", offset=-1))

        assert result["error"] is True
        assert result["error_type"] == "VALIDATION_ERROR"

    async def test_bulk_lookup_reports_the_per_chunk_limit_it_really_used(
        self, mock_api_client
    ):
        from src.ptab_mcp.main import search_trials_minimal

        mock_api_client.search_trials.return_value = {
            "count": 2, "patentTrialProceedingDataBag": self._bag(2)}

        result = json.loads(await search_trials_minimal(
            trial_number=["IPR2024-00001", "IPR2024-00002"], limit=25))

        paging = result["paging"]
        assert paging["limit_requested"] == 25
        assert paging["limit_applied"] == 100  # the chunk size actually used
        assert "Bulk trial-number lookup" in paging["note"]

    async def test_interference_search_pages_too(self, mock_api_client):
        from src.ptab_mcp.main import search_interferences_minimal

        mock_api_client.search_interferences.return_value = {
            "count": 12,
            "patentInterferenceDataBag": [{"interferenceNumber": "106001"}],
        }

        result = json.loads(await search_interferences_minimal(limit=5, offset=10))

        assert mock_api_client.search_interferences.call_args.kwargs["pagination"] == {
            "offset": 10, "limit": 5
        }
        assert result["paging"]["next_offset"] == 11
