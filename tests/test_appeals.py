"""
Tests for PTAB Appeals API endpoints

Tests all 3 appeals endpoints:
- search_appeals
- get_appeal_decisions
- download_appeal_document
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from src.ptab_mcp.api.ptab_client import PTABClient
from src.ptab_mcp.config.filter_field_mapping import AppealFilterFields


@pytest.fixture
def mock_api_key():
    """Provide a mock API key for testing"""
    return "test_api_key_12345"


@pytest.fixture
def ptab_client(mock_api_key):
    """Create PTABClient instance with mock API key"""
    return PTABClient(api_key=mock_api_key)


@pytest.fixture
def mock_appeal_response():
    """Mock appeal search response"""
    return {
        "count": 1,
        "patentAppealDataBag": [{
            "appealNumber": "12345678",
            "applicationNumber": "14123456",
            "filingDate": "2024-01-15",
            "decisionDate": "2024-06-15",
            "decisionType": "Affirmed",
            "appellantName": "John Doe"
        }]
    }


@pytest.mark.asyncio
async def test_search_appeals_basic(ptab_client, mock_appeal_response):
    """Test basic appeal search"""
    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=mock_appeal_response)):
        result = await ptab_client.search_appeals(
            filters=[{
                "name": "decisionType",
                "value": ["Affirmed"]
            }],
            pagination={"offset": 0, "limit": 1}
        )

        assert result["count"] >= 0
        assert "patentAppealDataBag" in result


@pytest.mark.asyncio
async def test_search_appeals_with_range_filters(ptab_client, mock_appeal_response):
    """Test appeal search with date range filters"""
    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=mock_appeal_response)):
        result = await ptab_client.search_appeals(
            range_filters=[{
                "field": "decisionDate",
                "valueFrom": "2024-01-01",
                "valueTo": "2024-12-31"
            }],
            pagination={"offset": 0, "limit": 10}
        )

        assert "patentAppealDataBag" in result


@pytest.mark.asyncio
async def test_search_appeals_with_field_filtering(ptab_client, mock_appeal_response):
    """Test appeal search with field filtering for context reduction"""
    # Use minimal field list (field sets now managed via YAML)
    minimal_fields = [
        "appealNumber",
        "applicationNumber",
        "decisionType",
        "decisionDate"
    ]

    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=mock_appeal_response)):
        result = await ptab_client.search_appeals(
            filters=[{
                "name": "decisionType",
                "value": ["Affirmed", "Reversed"]
            }],
            fields=minimal_fields,
            pagination={"offset": 0, "limit": 5}
        )

        assert "patentAppealDataBag" in result


@pytest.mark.asyncio
async def test_get_appeal_decisions(ptab_client):
    """Test getting appeal decisions"""
    mock_response = {
        "decisions": [{
            "decisionType": "Affirmed in Part",
            "decisionDate": "2024-06-15",
            "claimsAffirmed": [1, 2, 3],
            "claimsReversed": [4, 5]
        }]
    }

    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=mock_response)):
        result = await ptab_client.get_appeal_decisions("12345678")

        assert "decisions" in result


@pytest.mark.asyncio
async def test_download_appeal_document(ptab_client):
    """Test downloading appeal document"""
    mock_pdf_content = b"%PDF-1.4 mock appeal pdf"

    with patch('httpx.AsyncClient') as mock_client:
        mock_response = Mock()
        mock_response.content = mock_pdf_content
        mock_response.raise_for_status = Mock()

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_context

        result = await ptab_client.download_appeal_document(
            "https://api.uspto.gov/ui/patent/ptab-files/APPEAL/12345678/decision.pdf"
        )

        assert result == mock_pdf_content
        assert result.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_search_appeals_error_handling(ptab_client):
    """Test error handling in appeal search"""
    error_response = {
        "error": "API error: Invalid appeal number",
        "status_code": 404,
        "success": False
    }

    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=error_response)):
        result = await ptab_client.search_appeals(
            filters=[{"name": "appealNumber", "value": ["invalid"]}]
        )

        assert result["success"] is False
        assert "error" in result
