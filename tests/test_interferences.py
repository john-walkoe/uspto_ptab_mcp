"""
Tests for PTAB Interferences API endpoints

Tests all 3 interference endpoints:
- search_interferences
- get_interference_decisions
- download_interference_document
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
def mock_interference_response():
    """Mock interference search response"""
    return {
        "count": 1,
        "interferenceDecisionDataBag": [{
            "interferenceNumber": "106001",
            "filingDate": "2024-01-15",
            "decisionDate": "2024-06-15",
            "decisionType": "Final Decision",
            "seniorParty": "Party A",
            "juniorParty": "Party B"
        }]
    }


@pytest.mark.asyncio
async def test_search_interferences_basic(ptab_client, mock_interference_response):
    """Test basic interference search"""
    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=mock_interference_response)):
        result = await ptab_client.search_interferences(
            filters=[{
                "name": "decisionType",
                "value": ["Final Decision"]
            }],
            pagination={"offset": 0, "limit": 1}
        )

        assert result["count"] >= 0
        assert "interferenceDecisionDataBag" in result


@pytest.mark.asyncio
async def test_search_interferences_with_range_filters(ptab_client, mock_interference_response):
    """Test interference search with date range filters"""
    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=mock_interference_response)):
        result = await ptab_client.search_interferences(
            range_filters=[{
                "field": "decisionDate",
                "valueFrom": "2024-01-01",
                "valueTo": "2024-12-31"
            }],
            pagination={"offset": 0, "limit": 10}
        )

        assert "interferenceDecisionDataBag" in result


@pytest.mark.asyncio
async def test_search_interferences_with_field_filtering(ptab_client, mock_interference_response):
    """Test interference search with field filtering for context reduction"""
    # Use minimal field list (field sets now managed via YAML)
    minimal_fields = [
        "interferenceNumber",
        "applicationNumber",
        "decisionType",
        "decisionDate"
    ]

    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=mock_interference_response)):
        result = await ptab_client.search_interferences(
            filters=[{
                "name": "decisionType",
                "value": ["Final Decision"]
            }],
            fields=minimal_fields,
            pagination={"offset": 0, "limit": 5}
        )

        assert "interferenceDecisionDataBag" in result


@pytest.mark.asyncio
async def test_get_interference_decisions(ptab_client):
    """Test getting interference decisions"""
    mock_response = {
        "decisions": [{
            "decisionType": "Final Decision",
            "decisionDate": "2024-06-15",
            "decisionSummary": "Senior party prevails"
        }]
    }

    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=mock_response)):
        result = await ptab_client.get_interference_decisions("106001")

        assert "decisions" in result


@pytest.mark.asyncio
async def test_download_interference_document(ptab_client):
    """Test downloading interference document"""
    mock_pdf_content = b"%PDF-1.4 mock interference pdf"

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

        result = await ptab_client.download_interference_document(
            "https://api.uspto.gov/ui/patent/ptab-files/INTERFERENCE/106001/decision.pdf"
        )

        assert result == mock_pdf_content
        assert result.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_search_interferences_error_handling(ptab_client):
    """Test error handling in interference search"""
    error_response = {
        "error": "API error: Invalid interference number",
        "status_code": 404,
        "success": False
    }

    with patch.object(ptab_client, '_make_request', new=AsyncMock(return_value=error_response)):
        result = await ptab_client.search_interferences(
            filters=[{"name": "interferenceNumber", "value": ["invalid"]}]
        )

        assert result["success"] is False
        assert "error" in result
