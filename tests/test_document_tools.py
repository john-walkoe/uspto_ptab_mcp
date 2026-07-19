"""Hermetic unit tests for ptab_get_documents (TI-5).

These pin the flatten/filter/sort/paginate behavior of the document tools with
a mocked PTABClient so the Phase-5 refactor (adapter extraction) has a
regression net. No network, no API key required.
"""

import json

import pytest

from src.ptab_mcp.main import ptab_get_documents


class TestTrialDocuments:
    async def test_flatten_and_metadata(self, mock_api_client, mock_trial_documents_response):
        mock_api_client.search_trial_documents.return_value = mock_trial_documents_response

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-00123", identifier_type="trial"))

        assert result["identifier"] == "IPR2024-00123"
        assert result["identifier_type"] == "trial"
        assert result["total_documents"] == 4
        assert result["returned_count"] == 4
        docs = result["documents"]
        # Flattened: documentData fields at top level + trial metadata
        assert docs[0]["trialNumber"] == "IPR2024-00123"
        assert "documentIdentifier" in docs[0]
        assert "lastModifiedDateTime" in docs[0]
        # Default sort: desc by documentFilingDate
        dates = [d["documentFilingDate"] for d in docs]
        assert dates == sorted(dates, reverse=True)

    async def test_sort_asc(self, mock_api_client, mock_trial_documents_response):
        mock_api_client.search_trial_documents.return_value = mock_trial_documents_response

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-00123", identifier_type="trial", sort_order="asc"))

        dates = [d["documentFilingDate"] for d in result["documents"]]
        assert dates == sorted(dates)
        # Server-side sort parameter must be forwarded for trials
        kwargs = mock_api_client.search_trial_documents.call_args.kwargs
        assert kwargs["sort_order"] == "asc"

    async def test_document_category_filter(self, mock_api_client, mock_trial_documents_response):
        mock_api_client.search_trial_documents.return_value = mock_trial_documents_response

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-00123", identifier_type="trial",
            document_category="decision"))

        assert result["returned_count"] == 2
        assert result["filters_applied"] == {"document_category": "decision"}
        assert all(d["documentCategory"] == "DECISION" for d in result["documents"])

    async def test_filing_party_filter(self, mock_api_client, mock_trial_documents_response):
        mock_api_client.search_trial_documents.return_value = mock_trial_documents_response

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-00123", identifier_type="trial",
            filing_party="patent owner"))

        assert result["returned_count"] == 1
        assert result["documents"][0]["documentTitleText"] == "Patent Owner Response"

    async def test_document_title_substring_filter(self, mock_api_client, mock_trial_documents_response):
        mock_api_client.search_trial_documents.return_value = mock_trial_documents_response

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-00123", identifier_type="trial",
            document_title="institution"))

        assert result["returned_count"] == 1
        assert "Institution" in result["documents"][0]["documentTitleText"]

    async def test_trial_server_side_pagination_metadata(self, mock_api_client, mock_trial_documents_response):
        # API says 4 total; page of 2 starting at 0 -> next_offset hint of 2
        page = dict(mock_trial_documents_response)
        page["patentTrialDocumentDataBag"] = mock_trial_documents_response["patentTrialDocumentDataBag"][:2]
        mock_api_client.search_trial_documents.return_value = page

        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-00123", identifier_type="trial", limit=2))

        assert result["total_documents"] == 4
        assert result["returned_count"] == 2
        assert result["next_offset"] == 2
        kwargs = mock_api_client.search_trial_documents.call_args.kwargs
        assert kwargs["limit"] == 2
        assert kwargs["offset"] == 0


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
            identifier="IPR2024-00123", identifier_type="docket"))
        assert result["error"]

    async def test_invalid_limit(self, mock_api_client):
        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-00123", identifier_type="trial", limit=0))
        assert result["error"]

    async def test_invalid_sort_order(self, mock_api_client):
        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-00123", identifier_type="trial", sort_order="sideways"))
        assert result["error"]

    async def test_api_error_passthrough(self, mock_api_client):
        mock_api_client.search_trial_documents.return_value = {
            "error": True, "message": "upstream unavailable"}
        result = json.loads(await ptab_get_documents(
            identifier="IPR2024-00123", identifier_type="trial"))
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
            "truncation_note": "Document has 120 pages; OCR processed the first 50 (MISTRAL_OCR_MAX_PAGES cost cap).",
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
