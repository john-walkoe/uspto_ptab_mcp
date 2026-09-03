"""Hermetic unit tests for ptab_get_documents (TI-5).

These pin the flatten/filter/sort/paginate behavior of the document tools with
a mocked PTABClient so the Phase-5 refactor (adapter extraction) has a
regression net. No network, no API key required.
"""

import json


from src.ptab_mcp.main import ptab_get_documents


def serve_like_the_api(response):
    """A search_trial_documents side_effect that honours extra_filters.

    PTAB_get_documents now pushes document_category / filing_party /
    document_title into the trials/documents/search index, so a mock that
    ignores extra_filters would return the whole docket and make a pushdown
    look like a broken filter. This stands in for the index: exact
    case-insensitive match on category and filing party, phrase (here:
    substring) match on documentTitleText, then offset/limit.
    """
    bag = response["patentTrialDocumentDataBag"]

    async def _call(trial_number, offset=0, limit=25, sort_order="desc",
                    extra_filters=None):
        rows = list(bag)
        for spec in extra_filters or []:
            field = spec["name"].split(".")[-1]
            wanted = [v.lower() for v in spec["value"]]
            if field == "documentTitleText":
                rows = [
                    r for r in rows
                    if any(w in (r["documentData"].get("documentTitleText") or "").lower()
                           for w in wanted)
                ]
            else:
                rows = [
                    r for r in rows
                    if (r["documentData"].get(field) or "").lower() in wanted
                ]
        rows.sort(key=lambda r: r["documentData"]["documentFilingDate"],
                  reverse=(sort_order == "desc"))
        return {
            "count": len(rows),
            "patentTrialDocumentDataBag": rows[offset:offset + limit],
        }

    return _call


class TestTrialDocuments:
    async def test_flatten_and_metadata(self, mock_api_client, mock_trial_documents_response):
        mock_api_client.search_trial_documents.return_value = mock_trial_documents_response

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-01353", identifier_type="trial"))

        assert result["identifier"] == "IPR2024-01353"
        assert result["identifier_type"] == "trial"
        assert result["total_documents"] == 4
        assert result["returned_count"] == 4
        docs = result["documents"]
        # Flattened: documentData fields at top level + trial metadata
        assert docs[0]["trialNumber"] == "IPR2024-01353"
        assert "documentIdentifier" in docs[0]
        assert "lastModifiedDateTime" in docs[0]
        # Default sort: desc by documentFilingDate
        dates = [d["documentFilingDate"] for d in docs]
        assert dates == sorted(dates, reverse=True)

    async def test_sort_asc(self, mock_api_client, mock_trial_documents_response):
        mock_api_client.search_trial_documents.return_value = mock_trial_documents_response

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-01353", identifier_type="trial", sort_order="asc"))

        dates = [d["documentFilingDate"] for d in result["documents"]]
        assert dates == sorted(dates)
        # Server-side sort parameter must be forwarded for trials
        kwargs = mock_api_client.search_trial_documents.call_args.kwargs
        assert kwargs["sort_order"] == "asc"

    async def test_document_category_filter(self, mock_api_client, mock_trial_documents_response):
        """Category filtering is pushed into the API index, docket-wide."""
        mock_api_client.search_trial_documents.side_effect = serve_like_the_api(
            mock_trial_documents_response)

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-01353", identifier_type="trial",
            document_category="decision"))

        sent = mock_api_client.search_trial_documents.call_args.kwargs["extra_filters"]
        assert {"name": "documentData.documentCategory",
                "value": ["decision"]} in sent
        assert result["returned_count"] == 1
        assert result["filters_applied"] == {"document_category": "decision"}
        assert result["filters_server_side"] == ["document_category"]
        assert "filters_client_side" not in result
        assert result["documents"][0]["documentTitleText"] == "Institution Decision on Petition"

    async def test_final_written_decision_is_category_final(
        self, mock_api_client, mock_trial_documents_response
    ):
        """The FWD is FINAL. DECISION is the institution decision."""
        mock_api_client.search_trial_documents.side_effect = serve_like_the_api(
            mock_trial_documents_response)

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-01353", identifier_type="trial",
            document_category="FINAL"))

        assert result["returned_count"] == 1
        assert result["documents"][0]["documentTitleText"] == "Final Written Decision"
        assert "coverage_note" not in result

    async def test_unknown_category_is_warned_about(
        self, mock_api_client, mock_trial_documents_response
    ):
        """An unlisted category returns nothing, which reads like an empty
        docket — say that it is not a known value instead."""
        mock_api_client.search_trial_documents.side_effect = serve_like_the_api(
            mock_trial_documents_response)

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-01353", identifier_type="trial",
            document_category="JUDGMENT"))

        assert result["returned_count"] == 0
        assert "JUDGMENT" in result["filter_warning"]
        assert "FINAL" in result["filter_warning"]

    async def test_filing_party_filter(self, mock_api_client, mock_trial_documents_response):
        mock_api_client.search_trial_documents.side_effect = serve_like_the_api(
            mock_trial_documents_response)

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-01353", identifier_type="trial",
            filing_party="patent owner"))

        assert result["returned_count"] == 1
        assert result["documents"][0]["documentTitleText"] == "Patent Owner Response"
        assert result["filters_server_side"] == ["filing_party"]

    async def test_document_title_filter_is_pushed_server_side(
        self, mock_api_client, mock_trial_documents_response
    ):
        mock_api_client.search_trial_documents.side_effect = serve_like_the_api(
            mock_trial_documents_response)

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-01353", identifier_type="trial",
            document_title="institution"))

        sent = mock_api_client.search_trial_documents.call_args.kwargs["extra_filters"]
        assert {"name": "documentData.documentTitleText",
                "value": ["institution"]} in sent
        assert result["returned_count"] == 1
        assert "Institution" in result["documents"][0]["documentTitleText"]
        assert result["filters_server_side"] == ["document_title"]
        assert "SERVER-side" in result["filter_semantics_note"]

    async def test_no_matching_records_404_is_an_empty_result_not_an_error(
        self, mock_api_client
    ):
        """With a filter pushed down, the API's no-match 404 means zero rows."""
        mock_api_client.search_trial_documents.return_value = {
            "error": "No matching records found, refine your search criteria",
            "status_code": 404,
        }

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-01353", identifier_type="trial",
            document_category="REHEARING"))

        assert result.get("error") is None
        assert result["returned_count"] == 0
        assert result["documents"] == []

    async def test_page_all_walks_every_page_before_filtering(
        self, mock_api_client, mock_trial_documents_response
    ):
        """page_all=True: substring filtering over the WHOLE docket, and the
        page count is reported rather than left to be inferred."""
        mock_api_client.search_trial_documents.side_effect = serve_like_the_api(
            mock_trial_documents_response)

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-01353", identifier_type="trial",
            document_title="respons", page_all=True))

        # A partial word: only the client-side substring pass can match it
        assert result["returned_count"] == 1
        assert result["documents"][0]["documentTitleText"] == "Patent Owner Response"
        assert result["page_all"] is True
        assert result["pages_fetched"] == 1
        assert result["paging"]["pages_fetched"] == 1
        assert result["paging"]["has_more"] is False
        assert result["filters_client_side"] == ["document_title"]
        # Title must NOT have been pushed server-side under page_all
        sent = mock_api_client.search_trial_documents.call_args.kwargs["extra_filters"]
        assert all(f["name"] != "documentData.documentTitleText" for f in sent)

    async def test_page_all_reports_every_page_it_fetched(
        self, mock_api_client, mock_trial_documents_response
    ):
        """Two server pages -> pages_fetched 2, and every row is scanned."""
        rows = mock_trial_documents_response["patentTrialDocumentDataBag"]

        async def _paged(trial_number, offset=0, limit=25, sort_order="desc",
                         extra_filters=None):
            page_size = 2  # pretend the API cap is 2 rows
            return {"count": len(rows),
                    "patentTrialDocumentDataBag": rows[offset:offset + page_size]}

        mock_api_client.search_trial_documents.side_effect = _paged

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-01353", identifier_type="trial", page_all=True,
            limit=100))

        assert result["pages_fetched"] == 2
        assert result["returned_count"] == 4
        assert result["paging"]["scanned"] == 4

    async def test_trial_server_side_pagination_metadata(self, mock_api_client, mock_trial_documents_response):
        # API says 4 total; page of 2 starting at 0 -> next_offset hint of 2
        page = dict(mock_trial_documents_response)
        page["patentTrialDocumentDataBag"] = mock_trial_documents_response["patentTrialDocumentDataBag"][:2]
        mock_api_client.search_trial_documents.return_value = page

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-01353", identifier_type="trial", limit=2))

        assert result["total_documents"] == 4
        assert result["returned_count"] == 2
        assert result["next_offset"] == 2
        kwargs = mock_api_client.search_trial_documents.call_args.kwargs
        assert kwargs["limit"] == 2
        assert kwargs["offset"] == 0

    async def test_client_side_filter_cursor_advances_by_page_consumed(self):
        """A page of 2 server rows (API total 4) whose client-side filter
        matches none of them must still advance to offset 2, never stall at 0.

        Exercised directly on the envelope builder: for trials the title,
        category and filing-party filters are now pushed into the API index,
        so the tool no longer reaches this path with them — but appeals,
        interferences and outcome_category still do, and the stall was a real
        infinite loop (IPR2015-00040, 2026-08-21).
        """
        from src.ptab_mcp.tools.documents import _documents_paging_envelope

        payload = _documents_paging_envelope(
            {"documents": []},
            identifier_type="trial",
            limit_requested=2,
            offset=0,
            total_documents=4,
            total_is_docket_total=True,
            scanned=2,
            client_side_filters={"document_title": "no such title"},
        )

        paging = payload["paging"]
        assert paging["returned"] == 0
        assert paging["scanned"] == 2
        assert paging["has_more"] is True
        assert paging["next_offset"] == 2
        assert paging["client_side_filters"] == ["document_title"]


class TestAppealAndInterferenceDocuments:
    async def test_appeal_flatten_and_outcome_filter(self, mock_api_client, mock_appeal_decisions_response):
        mock_api_client.get_appeal_decisions.return_value = mock_appeal_decisions_response

        result = json.loads(await ptab_get_documents(
            identifier="2025000943", identifier_type="appeal",
            outcome_category="affirmed"))

        assert result["identifier_type"] == "appeal"
        assert result["returned_count"] == 1
        doc = result["documents"][0]
        assert doc["appealNumber"] == "2025000943"
        assert doc["appealOutcomeCategory"] == "Affirmed"
        assert doc["decisionIssueDate"] == "2025-04-01"

    async def test_appeal_client_side_pagination(self, mock_api_client, mock_appeal_decisions_response):
        mock_api_client.get_appeal_decisions.return_value = mock_appeal_decisions_response

        result = json.loads(await ptab_get_documents(
            identifier="2025000943", identifier_type="appeal",
            sort_order="asc", offset=1, limit=5))

        # 2 docs, offset 1 -> 1 returned; client-side slicing for appeals
        assert result["returned_count"] == 1
        assert result["documents"][0]["documentFilingDate"] == "2025-06-01"

    async def test_interference_flatten(self, mock_api_client):
        mock_api_client.get_interference_decisions.return_value = {
            "count": 1,
            "patentInterferenceDataBag": [
                {
                    "interferenceNumber": "106035",
                    "interferenceMetaData": {
                        "interferenceStyleName": "Foo v. Bar",
                        "declarationDate": "2015-03-01",
                    },
                    "documentData": {
                        "documentIdentifier": "300000001",
                        "documentTitleText": "Judgment",
                        "documentFilingDate": "2016-01-01",
                    },
                }
            ],
        }

        result = json.loads(await ptab_get_documents(
            identifier="106035", identifier_type="interference"))

        doc = result["documents"][0]
        assert doc["interferenceNumber"] == "106035"
        assert doc["interferenceStyleName"] == "Foo v. Bar"
        assert doc["declarationDate"] == "2015-03-01"


class TestValidationAndErrors:
    async def test_invalid_identifier_type(self, mock_api_client):
        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-01353", identifier_type="docket"))
        assert result["error"]

    async def test_invalid_limit(self, mock_api_client):
        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-01353", identifier_type="trial", limit=0))
        assert result["error"]

    async def test_invalid_sort_order(self, mock_api_client):
        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-01353", identifier_type="trial", sort_order="sideways"))
        assert result["error"]

    async def test_api_error_passthrough(self, mock_api_client):
        mock_api_client.search_trial_documents.return_value = {
            "error": True, "message": "upstream unavailable"}
        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-01353", identifier_type="trial"))
        assert result["error"]


class TestOcrTruncationSurfaced:
    """SD-6: Mistral page-truncation must reach the tool response, not just
    the OCR service's return dict."""

    async def test_run_tiers_propagates_truncation(self, monkeypatch):
        from unittest.mock import AsyncMock
        from src.ptab_mcp.tools import documents as doc_mod

        async def _noop(*a, **k):
            return None

        monkeypatch.setattr(doc_mod, "_try_mistral_extraction", AsyncMock(return_value={
            "success": True,
            "extracted_content": "page text",
            "processing_cost_usd": 0.05,
            "truncated": True,
            "truncation_note": "Document has 120 pages; OCR processed the first 50 (MISTRAL_OCR_MAX_PAGES limit).",
            "pages_processed": 50,
        }))

        text, method, cost, extra = await doc_mod._run_extraction_tiers(
            b"%PDF-fake", page_count=120, identifier="IPR2023-01035",
            document_id="170603095", use_ocr=True, progress_cb=_noop,
        )
        assert method == "mistral_ocr"
        assert extra["truncated"] is True
        assert "120 pages" in extra["truncation_note"]
        assert extra["pages_processed"] == 50

    async def test_run_tiers_no_truncation_key_when_full(self, monkeypatch):
        from unittest.mock import AsyncMock
        from src.ptab_mcp.tools import documents as doc_mod

        async def _noop(*a, **k):
            return None

        monkeypatch.setattr(doc_mod, "_try_mistral_extraction", AsyncMock(return_value={
            "success": True,
            "extracted_content": "page text",
            "processing_cost_usd": 0.01,
            "truncated": False,
            "pages_processed": 10,
        }))

        _, _, _, extra = await doc_mod._run_extraction_tiers(
            b"%PDF-fake", page_count=10, identifier="IPR2023-01035",
            document_id="170603095", use_ocr=True, progress_cb=_noop,
        )
        # truncated=False is still surfaced (explicit), truncation_note absent
        assert extra["truncated"] is False
        assert "truncation_note" not in extra


    async def test_page_all_on_an_appeal_is_the_single_get(
        self, mock_api_client, mock_appeal_decisions_response
    ):
        """Appeals and interferences are one non-paginating GET, so page_all
        must be a no-op there rather than an error."""
        mock_api_client.get_appeal_decisions.return_value = mock_appeal_decisions_response

        result = json.loads(await ptab_get_documents(
            identifier="2024-001234", identifier_type="appeal", page_all=True))

        assert result["pages_fetched"] == 1
        assert result["page_all"] is True
        assert result["returned_count"] >= 1


class TestFinalWrittenDecisionCoverage:
    """Open item #6: a docket can omit the Board's own paper.

    On IPR2024-00864 (305 documents, sealed) `document_category='FINAL'`
    returns nothing and `filing_party='BOARD'` never returns an FWD; the only
    final written decision on the docket is Paper 86, a PETITIONER-filed
    public copy in category OTHER. An empty FINAL result is not evidence that
    no decision issued, and the tool has to say so.
    """

    SEALED_DOCKET_ROWS = [
        {
            "documentIdentifier": "171263180",
            "documentNumber": 86,
            "documentTitleText": "Final Written Decision (Public)",
            "documentTypeDescriptionText": "Other:  other",
            "documentCategory": "OTHER",
            "filingPartyCategory": "PETITIONER",
            "documentFilingDate": "2025-12-22",
        },
        {
            "documentIdentifier": "171263182",
            "documentNumber": 87,
            "documentTitleText": "Public Final Written Decision Certificate of Service",
            "documentTypeDescriptionText": "Other:  other",
            "documentCategory": "OTHER",
            "filingPartyCategory": "PETITIONER",
            "documentFilingDate": "2025-12-22",
        },
    ]

    def test_note_names_the_party_copy_when_no_final_row_exists(self):
        from src.ptab_mcp.tools.documents import _fwd_coverage_note

        note = _fwd_coverage_note(self.SEALED_DOCKET_ROWS)

        assert note is not None
        assert "171263180" in note
        assert "OTHER" in note
        assert "PETITIONER" in note
        assert "86" in note

    def test_no_note_when_the_board_paper_is_a_row(self, mock_trial_documents_response):
        from src.ptab_mcp.tools.documents import _fwd_coverage_note

        rows = [item["documentData"]
                for item in mock_trial_documents_response["patentTrialDocumentDataBag"]]
        assert any(r["documentCategory"] == "FINAL" for r in rows)

        assert _fwd_coverage_note(rows) is None

    def test_no_note_when_nothing_mentions_a_final_written_decision(self):
        from src.ptab_mcp.tools.documents import _fwd_coverage_note

        assert _fwd_coverage_note([
            {"documentTitleText": "Petition for Inter Partes Review",
             "documentCategory": "PETITION"},
        ]) is None

    def test_no_note_for_a_mere_paper_about_the_decision(self):
        """A notice of appeal mentions the FWD but is not a copy of it."""
        from src.ptab_mcp.tools.documents import _fwd_coverage_note

        assert _fwd_coverage_note([
            {"documentTitleText": "Patent Owner's Notice of Appeal of Final "
                                  "Written Decision",
             "documentCategory": "NOTICE",
             "filingPartyCategory": "PATENT OWNER"},
        ]) is None

    async def test_empty_final_request_probes_and_explains(self, mock_api_client):
        """document_category='FINAL' returning nothing triggers one title
        probe, and the answer comes back as coverage_note."""
        calls = []

        async def _call(trial_number, offset=0, limit=25, sort_order="desc",
                        extra_filters=None):
            calls.append(extra_filters)
            names = {f["name"] for f in extra_filters or []}
            if "documentData.documentTitleText" in names:
                return {
                    "count": 2,
                    "patentTrialDocumentDataBag": [
                        {"trialNumber": "IPR2024-00864", "documentData": row}
                        for row in self.SEALED_DOCKET_ROWS
                    ],
                }
            return {"count": 0, "patentTrialDocumentDataBag": []}

        mock_api_client.search_trial_documents.side_effect = _call

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-00864", identifier_type="trial",
            document_category="FINAL", limit=100))

        assert result["returned_count"] == 0
        assert "coverage_note" in result
        assert "171263180" in result["coverage_note"]
        assert len(calls) == 2, "exactly one extra probe call"

    async def test_no_probe_when_final_rows_came_back(
        self, mock_api_client, mock_trial_documents_response
    ):
        mock_api_client.search_trial_documents.side_effect = serve_like_the_api(
            mock_trial_documents_response)

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-01353", identifier_type="trial",
            document_category="FINAL"))

        assert result["returned_count"] == 1
        assert "coverage_note" not in result
        assert mock_api_client.search_trial_documents.call_count == 1
