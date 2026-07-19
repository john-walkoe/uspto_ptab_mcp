"""Shared pytest configuration and fixtures for the PTAB MCP test suite.

- Registers the auto-skip gate for @pytest.mark.network tests (live USPTO API):
  they are skipped unless PTAB_RUN_NETWORK_TESTS=1 is set, so a plain
  `uv run pytest` is hermetic and green without a real API key.
- Provides the shared PTABClient mock seam (`mock_api_client`) that patches the
  module-global client in main.py, plus canonical mock response fixtures.
"""

import os
from unittest.mock import AsyncMock, Mock

import pytest

# main.py exits at import without a USPTO key; give importing tests a placeholder
os.environ.setdefault("USPTO_API_KEY", "test_api_key_conftest")


def pytest_collection_modifyitems(config, items):
    if os.getenv("PTAB_RUN_NETWORK_TESTS"):
        return
    skip_network = pytest.mark.skip(
        reason="live USPTO API test; set PTAB_RUN_NETWORK_TESTS=1 to run"
    )
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)


@pytest.fixture
def mock_api_client(monkeypatch):
    """Patch main.py's module-global PTABClient with a configurable mock.

    Tests configure return values per endpoint, e.g.:
        mock_api_client.search_trial_documents.return_value = {...}
    """
    from src.ptab_mcp import runtime as ptab_runtime

    client = Mock()
    for method in (
        "search_trials",
        "search_appeals",
        "search_interferences",
        "search_trial_documents",
        "search_all_trial_documents",
        "get_trial_proceeding",
        "get_trial_documents",
        "get_trial_decisions",
        "get_appeal_decisions",
        "get_interference_decisions",
        "download_trial_document",
        "download_appeal_document",
        "download_interference_document",
    ):
        setattr(client, method, AsyncMock(return_value={}))

    monkeypatch.setattr(ptab_runtime, "api_client", client)
    monkeypatch.setattr(ptab_runtime, "get_api_client", lambda: client)
    return client


@pytest.fixture
def mock_trial_documents_response():
    """Canonical POST trial-document search response (server-side pagination)."""
    return {
        "count": 4,
        "patentTrialDocumentDataBag": [
            {
                "trialNumber": "IPR2024-00123",
                "lastModifiedDateTime": "2024-05-16T10:00:00",
                "documentData": {
                    "documentIdentifier": "171141394",
                    "documentTitleText": "Final Written Decision",
                    "documentTypeDescriptionText": "Final Written Decision",
                    "documentCategory": "DECISION",
                    "filingPartyCategory": "BOARD",
                    "documentFilingDate": "2024-05-15",
                    "documentSizeQuantity": 97699,
                },
            },
            {
                "trialNumber": "IPR2024-00123",
                "lastModifiedDateTime": "2024-02-02T10:00:00",
                "documentData": {
                    "documentIdentifier": "171141001",
                    "documentTitleText": "Institution Decision on Petition",
                    "documentTypeDescriptionText": "Institution Decision on Petition",
                    "documentCategory": "DECISION",
                    "filingPartyCategory": "BOARD",
                    "documentFilingDate": "2024-02-01",
                    "documentSizeQuantity": 50000,
                },
            },
            {
                "trialNumber": "IPR2024-00123",
                "lastModifiedDateTime": "2024-01-16T10:00:00",
                "documentData": {
                    "documentIdentifier": "171140900",
                    "documentTitleText": "Petition for Inter Partes Review",
                    "documentTypeDescriptionText": "Petition for Inter Partes Review",
                    "documentCategory": "PETITION",
                    "filingPartyCategory": "PETITIONER",
                    "documentFilingDate": "2024-01-15",
                    "documentSizeQuantity": 120000,
                },
            },
            {
                "trialNumber": "IPR2024-00123",
                "lastModifiedDateTime": "2024-03-02T10:00:00",
                "documentData": {
                    "documentIdentifier": "171141100",
                    "documentTitleText": "Patent Owner Response",
                    "documentTypeDescriptionText": "Patent Owner Response",
                    "documentCategory": "RESPONSE",
                    "filingPartyCategory": "PATENT OWNER",
                    "documentFilingDate": "2024-03-01",
                    "documentSizeQuantity": 80000,
                },
            },
        ],
    }


@pytest.fixture
def mock_appeal_decisions_response():
    """Canonical GET appeal-decisions response (no server-side pagination)."""
    return {
        "count": 2,
        "patentAppealDataBag": [
            {
                "appealNumber": "2025000943",
                "decisionData": {
                    "appealOutcomeCategory": "Affirmed",
                    "decisionIssueDate": "2025-04-01",
                },
                "documentData": {
                    "documentIdentifier": "200000001",
                    "documentTitleText": "Decision on Appeal",
                    "documentTypeDescriptionText": "Decision on Appeal",
                    "documentFilingDate": "2025-04-01",
                },
            },
            {
                "appealNumber": "2025000943",
                "decisionData": {
                    "appealOutcomeCategory": "Rehearing Decision Denied",
                    "decisionIssueDate": "2025-06-01",
                },
                "documentData": {
                    "documentIdentifier": "200000002",
                    "documentTitleText": "Rehearing Decision",
                    "documentTypeDescriptionText": "Rehearing Decision",
                    "documentFilingDate": "2025-06-01",
                },
            },
        ],
    }


@pytest.fixture
def mock_trial_search_response():
    """Canonical trial search response shared across test modules (TI-7)."""
    return {
        "count": 1,
        "patentTrialProceedingDataBag": [
            {
                "trialNumber": "IPR2024-00123",
                "trialMetaData": {
                    "trialTypeCode": "IPR",
                    "accordedFilingDate": "2024-01-15",
                    "trialStatusCategory": "Terminated",
                },
                "petitionerData": {"petitionerPartyName": "Apple Inc."},
                "patentOwnerData": {"patentOwnerName": "Samsung Electronics"},
                "respondentData": {
                    "patentNumber": "8524787",
                    "patentTitle": "Test Patent",
                },
            }
        ],
    }
