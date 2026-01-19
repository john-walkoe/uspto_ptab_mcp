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
import os
from unittest.mock import Mock, patch, AsyncMock
from src.ptab_mcp.api.ptab_client import PTABClient
from src.ptab_mcp.config.filter_field_mapping import TrialFilterFields


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
            "trialNumber": "IPR2024-00123",
            "trialMetaData": {
                "trialTypeCode": "IPR",
                "accordedFilingDate": "2024-01-15",
                "trialStatusCategory": "Terminated"
            },
            "petitionerData": {
                "petitionerPartyName": "Apple Inc."
            },
            "patentOwnerData": {
                "patentOwnerName": "Samsung Electronics"
            },
            "respondentData": {
                "patentNumber": "8524787",
                "patentTitle": "Test Patent"
            }
        }]
    }


@pytest.mark.asyncio
async def test_search_trials_basic(ptab_client, mock_trial_response):
    """Test basic trial search"""
    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=mock_trial_response)):
        result = await ptab_client.search_trials(
            filters=[{
                "name": "trialMetaData.trialTypeCode",
                "value": ["IPR"]
            }],
            pagination={"offset": 0, "limit": 1}
        )

        assert result["count"] >= 0
        assert "patentTrialProceedingDataBag" in result


@pytest.mark.asyncio
async def test_search_trials_with_range_filters(ptab_client, mock_trial_response):
    """Test trial search with date range filters"""
    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=mock_trial_response)):
        result = await ptab_client.search_trials(
            range_filters=[{
                "field": "trialMetaData.accordedFilingDate",
                "valueFrom": "2024-01-01",
                "valueTo": "2024-12-31"
            }],
            pagination={"offset": 0, "limit": 10}
        )

        assert "patentTrialProceedingDataBag" in result


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

    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=mock_trial_response)):
        result = await ptab_client.search_trials(
            filters=[{
                "name": "trialMetaData.trialTypeCode",
                "value": ["IPR"]
            }],
            fields=minimal_fields,
            pagination={"offset": 0, "limit": 5}
        )

        assert "patentTrialProceedingDataBag" in result


@pytest.mark.asyncio
async def test_get_trial_proceeding(ptab_client):
    """Test getting specific trial proceeding"""
    mock_response = {
        "trialNumber": "IPR2024-00123",
        "trialMetaData": {
            "trialTypeCode": "IPR",
            "accordedFilingDate": "2024-01-15"
        }
    }

    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=mock_response)):
        result = await ptab_client.get_trial_proceeding("IPR2024-00123")

        assert result["trialNumber"] == "IPR2024-00123"
        assert "trialMetaData" in result


@pytest.mark.asyncio
async def test_get_trial_documents(ptab_client):
    """Test getting trial documents"""
    mock_response = {
        "documents": [{
            "documentIdentifier": "12345",
            "documentCode": "PETITION",
            "fileDownloadURI": "https://api.uspto.gov/ui/patent/ptab-files/IPR/2024/00123/12345.pdf"
        }]
    }

    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=mock_response)):
        result = await ptab_client.get_trial_documents("IPR2024-00123")

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
        result = await ptab_client.get_trial_decisions("IPR2024-00123")

        assert "decisions" in result


@pytest.mark.asyncio
async def test_download_trial_document(ptab_client):
    """Test downloading trial document"""
    mock_pdf_content = b"%PDF-1.4 mock pdf content"

    with patch('httpx.AsyncClient') as mock_client:
        mock_response = Mock()
        mock_response.content = mock_pdf_content
        mock_response.raise_for_status = Mock()

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_context

        result = await ptab_client.download_trial_document(
            "https://api.uspto.gov/ui/patent/ptab-files/IPR/2024/00123/12345.pdf"
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
