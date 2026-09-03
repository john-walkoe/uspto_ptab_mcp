"""
Tests for PTAB Trials API endpoints

Tests all 5 trials endpoints:
- search_trials
- get_trial_proceeding
- get_trial_documents
- get_trial_decisions
- download_trial_document
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from src.ptab_mcp.api.ptab_client import PTABClient


@pytest.fixture
def mock_api_key():
    """Provide a mock API key for testing"""
    return "test_api_key_12345"


@pytest.fixture
def ptab_client(mock_api_key):
    """Create PTABClient instance with mock API key"""
    return PTABClient(api_key=mock_api_key)


@pytest.fixture
def mock_trial_response():
    """Mock trial search response"""
    return {
        "count": 1,
        "patentTrialProceedingDataBag": [{
            "trialNumber": "IPR2024-01353",
            "trialMetaData": {
                "trialTypeCode": "IPR",
                "accordedFilingDate": "2024-01-15",
                "trialStatusCategory": "Terminated"
            },
            # Live bag names (config/filter_field_mapping.py:92): a trial record
            # has no respondentData bag, the petitioner is
            # regularPetitionerData.realPartyInInterestName, and
            # patentOwnerData.patentOwnerName is never populated.
            "regularPetitionerData": {
                "realPartyInInterestName": "Apple Inc."
            },
            "patentOwnerData": {
                "realPartyInInterestName": "Samsung Electronics",
                "patentNumber": "7883848",
                "applicationNumberText": "13/456,789"
            }
        }]
    }


@pytest.mark.asyncio
async def test_search_trials_basic(ptab_client, mock_trial_response):
    """The client forwards filters and pagination into the POST body.

    Asserting on the request the client BUILT, not on the mock's own echo:
    `result["count"] >= 0` and `"patentTrialProceedingDataBag" in result` hold
    for every possible response, including an error envelope, and exercised no
    production branch.
    """
    send = AsyncMock(return_value=mock_trial_response)
    with patch.object(ptab_client, '_make_request', new=send):
        result = await ptab_client.search_trials(
            filters=[{
                "name": "trialMetaData.trialTypeCode",
                "value": ["IPR"]
            }],
            pagination={"offset": 0, "limit": 1}
        )

    body = send.call_args.kwargs["json"]
    assert body["filters"] == [{"name": "trialMetaData.trialTypeCode", "value": ["IPR"]}]
    assert body["pagination"] == {"offset": 0, "limit": 1}
    assert send.call_args.kwargs["method"] == "POST"
    assert send.call_args.args[0] == "trials/proceedings/search"
    assert result["patentTrialProceedingDataBag"][0]["trialNumber"] == "IPR2024-01353"


@pytest.mark.asyncio
async def test_search_trials_with_range_filters(ptab_client, mock_trial_response):
    """A range filter goes onto the body as `rangeFilters`, not `filters`."""
    send = AsyncMock(return_value=mock_trial_response)
    with patch.object(ptab_client, '_make_request', new=send):
        await ptab_client.search_trials(
            range_filters=[{
                "field": "trialMetaData.accordedFilingDate",
                "valueFrom": "2024-01-01",
                "valueTo": "2024-12-31"
            }],
            pagination={"offset": 0, "limit": 10}
        )

    body = send.call_args.kwargs["json"]
    assert body["rangeFilters"] == [{
        "field": "trialMetaData.accordedFilingDate",
        "valueFrom": "2024-01-01",
        "valueTo": "2024-12-31",
    }]
    assert "filters" not in body


@pytest.mark.asyncio
async def test_search_trials_with_field_filtering(ptab_client, mock_trial_response):
    """Test trial search with field filtering for context reduction"""
    # Use minimal field list (field sets now managed via YAML)
    minimal_fields = [
        "trialNumber",
        "trialMetaData.accordedFilingDate",
        "trialMetaData.trialTypeCode",
        "patentOwnerData.patentNumber"
    ]

    send = AsyncMock(return_value=mock_trial_response)
    with patch.object(ptab_client, '_make_request', new=send):
        await ptab_client.search_trials(
            filters=[{
                "name": "trialMetaData.trialTypeCode",
                "value": ["IPR"]
            }],
            fields=minimal_fields,
            pagination={"offset": 0, "limit": 5}
        )

    assert send.call_args.kwargs["json"]["fields"] == minimal_fields


@pytest.mark.asyncio
async def test_get_trial_proceeding(ptab_client):
    """Test getting specific trial proceeding"""
    mock_response = {
        "trialNumber": "IPR2024-01353",
        "trialMetaData": {
            "trialTypeCode": "IPR",
            "accordedFilingDate": "2024-01-15"
        }
    }

    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=mock_response)):
        result = await ptab_client.get_trial_proceeding("IPR2024-01353")

        assert result["trialNumber"] == "IPR2024-01353"
        assert "trialMetaData" in result


@pytest.mark.asyncio
async def test_get_trial_documents(ptab_client):
    """Test getting trial documents"""
    mock_response = {
        "documents": [{
            "documentIdentifier": "12345",
            "documentCode": "PETITION",
            "fileDownloadURI": "https://api.uspto.gov/ui/patent/ptab-files/IPR/2024/01353/12345.pdf"
        }]
    }

    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=mock_response)):
        result = await ptab_client.get_trial_documents("IPR2024-01353")

        assert "documents" in result


@pytest.mark.asyncio
async def test_get_trial_decisions(ptab_client):
    """Test getting trial decisions"""
    mock_response = {
        "decisions": [{
            "decisionType": "Final Written Decision",
            "decisionDate": "2024-06-15"
        }]
    }

    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=mock_response)):
        result = await ptab_client.get_trial_decisions("IPR2024-01353")

        assert "decisions" in result


@pytest.mark.asyncio
async def test_download_trial_document(ptab_client):
    """Test downloading trial document"""
    mock_pdf_content = b"%PDF-1.4 mock pdf content"

    with patch('httpx.AsyncClient') as mock_client:
        # The download STREAMS now, bounded by PTAB_MAX_PDF_BYTES, instead of
        # buffering response.content whole.
        async def _chunks():
            yield mock_pdf_content

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.aiter_bytes = Mock(return_value=_chunks())

        stream_cm = AsyncMock()
        stream_cm.__aenter__ = AsyncMock(return_value=mock_response)
        stream_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.stream = Mock(return_value=stream_cm)

        result = await ptab_client.download_trial_document(
            "https://api.uspto.gov/ui/patent/ptab-files/IPR/2024/01353/12345.pdf"
        )

        assert result == mock_pdf_content
        assert result.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_circuit_breaker_status(ptab_client):
    """Test circuit breaker status monitoring"""
    status = ptab_client.get_circuit_breaker_status()

    assert "trials" in status
    assert "appeals" in status
    assert "interferences" in status
    assert status["trials"]["name"] == "PTAB_Trials"


@pytest.mark.asyncio
async def test_search_trials_error_handling(ptab_client):
    """Test error handling in trial search"""
    error_response = {
        "error": "API error: Invalid parameter",
        "status_code": 400,
        "success": False
    }

    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=error_response)):
        result = await ptab_client.search_trials(
            filters=[{"name": "invalid.field", "value": ["test"]}]
        )

        assert result["success"] is False
        assert "error" in result


class TestTrialDateRangeFields:
    """Open item #2: the institution / final-decision date filters mapped to
    fields the trial payload does not carry, so every range returned nothing.

    Verified live 2026-08-30: a rangeFilter on trialMetaData.institutionDate
    or trialMetaData.finalDecisionDate returns HTTP 404 for every window,
    while institutionDecisionDate (1046 hits) and latestDecisionDate (1385)
    return records for 2024-01-01..2024-12-31.
    """

    async def _run(self, mock_api_client, **kwargs):
        from src.ptab_mcp.tools.trials import search_trials_balanced

        mock_api_client.search_trials.return_value = {
            "count": 0, "patentTrialProceedingDataBag": []
        }
        await search_trials_balanced(**kwargs)
        return mock_api_client.search_trials.call_args.kwargs["range_filters"]

    async def test_institution_range_uses_institution_decision_date(
        self, mock_api_client
    ):
        ranges = await self._run(
            mock_api_client,
            institution_date_from="2024-01-01", institution_date_to="2024-12-31",
        )
        fields = {r["field"] for r in ranges}
        assert "trialMetaData.institutionDecisionDate" in fields
        assert "trialMetaData.institutionDate" not in fields

    async def test_latest_decision_range_uses_latest_decision_date(
        self, mock_api_client
    ):
        ranges = await self._run(
            mock_api_client,
            latest_decision_date_from="2024-01-01",
            latest_decision_date_to="2024-12-31",
        )
        fields = {r["field"] for r in ranges}
        assert "trialMetaData.latestDecisionDate" in fields
        assert "trialMetaData.finalDecisionDate" not in fields

    async def test_deprecated_final_decision_params_still_work(
        self, mock_api_client
    ):
        ranges = await self._run(
            mock_api_client,
            final_decision_date_from="2024-01-01",
            final_decision_date_to="2024-12-31",
        )
        assert [r["field"] for r in ranges] == ["trialMetaData.latestDecisionDate"]

    async def test_one_sided_range_is_closed_before_it_reaches_the_api(
        self, mock_api_client
    ):
        """A null bound is HTTP 400, so no range filter may carry one."""
        ranges = await self._run(
            mock_api_client,
            filing_date_from="2024-01-01",
            institution_date_to="2024-12-31",
        )
        assert ranges
        assert all(r["valueFrom"] and r["valueTo"] for r in ranges)


class TestNoClaimLevelOutcomes:
    """Open item #5: the dead decisionData.* constants promised claim-level
    data the trials endpoint has never carried."""

    def test_dead_decision_data_constants_are_gone(self):
        from src.ptab_mcp.api.field_constants import TrialFields

        for dead in ("CLAIMS_CHALLENGED", "CLAIMS_FOUND_UNPATENTABLE",
                     "DECISION_TYPE", "DECISION_OUTCOME"):
            assert not hasattr(TrialFields, dead), dead

    def test_dead_date_constants_are_gone(self):
        from src.ptab_mcp.api.field_constants import TrialFields

        assert not hasattr(TrialFields, "INSTITUTION_DATE")
        assert not hasattr(TrialFields, "FINAL_DECISION_DATE")
        assert TrialFields.INSTITUTION_DECISION_DATE == (
            "trialMetaData.institutionDecisionDate")

    def test_every_trial_tool_says_no_claim_level_outcomes(self):
        from src.ptab_mcp.tools import trials

        for fn in (trials.search_trials_minimal,
                   trials.search_trials_balanced,
                   trials.search_trials_complete):
            doc = fn.__doc__ or ""
            assert "NO CLAIM-LEVEL OUTCOMES" in doc, fn.__name__
            assert "document_category='FINAL'" in doc, fn.__name__
