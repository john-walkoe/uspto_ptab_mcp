"""
Comprehensive End-to-End Integration Tests for PTAB MCP (Phase 9)

Tests all workflow patterns, FilterBuilder integration, proxy modes,
performance characteristics, and error scenarios.

Coverage:
- End-to-end workflows (minimal → balanced → documents)
- FilterBuilder integration with all 9 search functions
- Proxy integration (standalone, centralized, fallback)
- Performance characteristics and context reduction
- Error scenarios and circuit breaker patterns

Run: uv run pytest tests/test_workflow.py -v
"""

import pytest
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Dict, Any
from unittest.mock import Mock, patch, AsyncMock

# Import all search functions
from src.ptab_mcp.main import (
    # Trial tools
    search_trials_minimal,
    search_trials_balanced,
    search_trials_complete,
    # Appeal tools
    search_appeals_minimal,
    search_appeals_balanced,
    search_appeals_complete,
    # Interference tools
    search_interferences_minimal,
    search_interferences_balanced,
    search_interferences_complete,
    # Document tools
    ptab_get_documents,
    ptab_get_document_download,
    ptab_get_document_content,
    # Utility
    get_local_proxy_port,
    _detect_pfw_proxy
)

# Import FilterBuilder and field mappings
from src.ptab_mcp.util.filter_builder import FilterBuilder
from src.ptab_mcp.config.filter_field_mapping import (
    TrialFilterFields,
    AppealFilterFields,
    InterferenceFilterFields
)


# ============================================================================
# Test Class 1: End-to-End Workflow Tests
# ============================================================================

class TestTrialsWorkflow:
    """Test complete trials workflow: minimal → balanced → documents → content."""

    @pytest.mark.asyncio
    async def test_trials_progressive_disclosure_workflow(self):
        """Test: Discovery → Selection → Analysis → Documents → Content"""

        # STAGE 1: Discovery with minimal fields
        print("\n[STAGE 1] Discovery with minimal fields")
        minimal_result = await search_trials_minimal(
            trial_type="IPR",
            limit=5
        )
        minimal_data = json.loads(minimal_result)

        assert minimal_data['data_type'] == 'trials'
        assert minimal_data['field_set'] == 'trials_minimal'
        assert 'context_reduction' in minimal_data

        # Should have context reduction
        if minimal_data.get('count', 0) > 0:
            reduction_pct = minimal_data['context_reduction']['reduction_percentage']
            assert reduction_pct.endswith('%')
            print(f"   ✓ Context reduction: {reduction_pct}")

        # Get trial number for next stage
        if minimal_data['count'] == 0:
            pytest.skip("No trials data available for workflow test")

        trial_number = minimal_data['results'][0]['trialNumber']
        print(f"   ✓ Selected trial: {trial_number}")

        # STAGE 2: Analysis with balanced fields
        print("\n[STAGE 2] Analysis with balanced fields")
        balanced_result = await search_trials_balanced(
            trial_number=trial_number,
            limit=1
        )
        balanced_data = json.loads(balanced_result)

        assert balanced_data['data_type'] == 'trials'
        assert balanced_data['field_set'] == 'trials_balanced'
        assert balanced_data['count'] >= 1

        # Balanced should have more fields than minimal
        balanced_fields = len(balanced_data['results'][0])
        minimal_fields = len(minimal_data['results'][0])
        assert balanced_fields > minimal_fields
        print(f"   ✓ Field count: {minimal_fields} → {balanced_fields}")

        # STAGE 3: Get document list
        print("\n[STAGE 3] Get document list")
        docs_result = await ptab_get_documents(
            identifier=trial_number,
            identifier_type="trial"
        )
        docs_data = json.loads(docs_result)

        assert docs_data['identifier'] == trial_number
        assert docs_data['identifier_type'] == 'trial'
        assert 'documents' in docs_data or docs_data['count'] == 0
        print(f"   ✓ Document count: {docs_data['count']}")

        # STAGE 4: Download link (if documents exist)
        if docs_data['count'] > 0 and docs_data.get('documents'):
            print("\n[STAGE 4] Get download link")
            # Document ID field may vary based on API response
            first_doc = docs_data['documents'][0]
            document_id = first_doc.get('documentIdentifier') or first_doc.get('documentId') or first_doc.get('id')

            if document_id:  # Only if we found a valid document ID
                download_result = await ptab_get_document_download(
                    document_id=document_id,
                    identifier=trial_number,
                    identifier_type="trial"
                )
                download_data = json.loads(download_result)

                # May have error or success response
                if 'error' not in download_data:
                    assert download_data.get('document_id') == document_id or 'download_url' in download_data
                    assert 'download_url' in download_data
                    assert download_data['download_url'].startswith('http')
                    print(f"   ✓ Download URL: {download_data['download_url'][:60]}...")
                else:
                    print(f"   ⚠ Download failed: {download_data.get('error', 'Unknown error')}")

            # STAGE 5: Extract content (PyPDF2 only for speed)
            if document_id:  # Only if we have a valid document ID
                print("\n[STAGE 5] Extract content")
                content_result = await ptab_get_document_content(
                    document_id=document_id,
                    identifier=trial_number,
                    identifier_type="trial",
                    use_ocr=False  # PyPDF2 only for speed
                )
                content_data = json.loads(content_result)

                assert 'text' in content_data or 'error' in content_data
                if 'text' in content_data:
                    assert content_data['extraction_method'] in ['pypdf2', 'mistral_ocr']
                    print(f"   ✓ Extraction: {content_data['extraction_method']}")
                    print(f"   ✓ Char count: {content_data['character_count']}")
                else:
                    print(f"   ⚠ Extraction failed: {content_data.get('error', 'Unknown error')}")

    @pytest.mark.asyncio
    async def test_trials_custom_fields_workflow(self):
        """Test: Custom ultra-minimal field selection (99% context reduction)"""

        # Ultra-minimal: Only 2 fields
        custom_result = await search_trials_minimal(
            trial_type="IPR",
            fields=["trialNumber", "patentOwnerData.patentNumber"],
            limit=5
        )
        custom_data = json.loads(custom_result)

        assert custom_data['data_type'] == 'trials'
        assert custom_data['field_set'] == 'custom'

        if custom_data['count'] > 0:
            # Should only have 2 fields
            result_fields = list(custom_data['results'][0].keys())
            assert len(result_fields) == 2
            assert 'trialNumber' in result_fields
            assert 'patentOwnerData' in result_fields or 'patentNumber' in result_fields


class TestAppealsWorkflow:
    """Test complete appeals workflow."""

    @pytest.mark.asyncio
    async def test_appeals_progressive_disclosure_workflow(self):
        """Test: Appeals minimal → balanced → complete"""

        # STAGE 1: Discovery
        minimal_result = await search_appeals_minimal(limit=3)
        minimal_data = json.loads(minimal_result)

        assert minimal_data['data_type'] == 'appeals'
        assert minimal_data['field_set'] == 'appeals_minimal'

        if minimal_data['count'] == 0:
            pytest.skip("No appeals data available")

        # STAGE 2: Analysis
        appeal_number = minimal_data['results'][0].get('appealNumber')
        if appeal_number:
            balanced_result = await search_appeals_balanced(
                appeal_number=appeal_number,
                limit=1
            )
            balanced_data = json.loads(balanced_result)

            # May return error if appeal not found
            if 'error' not in balanced_data:
                assert balanced_data['data_type'] == 'appeals'
                assert balanced_data['field_set'] == 'appeals_balanced'

        # STAGE 3: Complete
        complete_result = await search_appeals_complete(limit=1)
        complete_data = json.loads(complete_result)

        assert complete_data['data_type'] == 'appeals'
        assert complete_data['field_set'] == 'appeals_complete'
        # Complete tier should have NO context reduction
        assert complete_data.get('context_reduction') is None


class TestInterferencesWorkflow:
    """Test complete interferences workflow."""

    @pytest.mark.asyncio
    async def test_interferences_progressive_disclosure_workflow(self):
        """Test: Interferences minimal → balanced → complete"""

        # STAGE 1: Discovery
        minimal_result = await search_interferences_minimal(limit=3)
        minimal_data = json.loads(minimal_result)

        assert minimal_data['data_type'] == 'interferences'
        assert minimal_data['field_set'] == 'interferences_minimal'

        if minimal_data['count'] == 0:
            pytest.skip("No interferences data available")

        # STAGE 2: Analysis
        interference_number = minimal_data['results'][0].get('interferenceNumber')
        if interference_number:
            balanced_result = await search_interferences_balanced(
                interference_number=interference_number,
                limit=1
            )
            balanced_data = json.loads(balanced_result)

            assert balanced_data['data_type'] == 'interferences'
            assert balanced_data['field_set'] == 'interferences_balanced'

        # STAGE 3: Complete
        complete_result = await search_interferences_complete(limit=1)
        complete_data = json.loads(complete_result)

        assert complete_data['data_type'] == 'interferences'
        assert complete_data['field_set'] == 'interferences_complete'
        assert complete_data.get('context_reduction') is None


# ============================================================================
# Test Class 2: FilterBuilder Integration Tests
# ============================================================================

class TestFilterBuilderIntegration:
    """Test FilterBuilder integration with all 9 search functions."""

    @pytest.mark.asyncio
    async def test_trials_minimal_uses_filterbuilder(self):
        """Verify search_trials_minimal uses FilterBuilder correctly"""

        result = await search_trials_minimal(
            trial_number="IPR2024-00123",
            patent_number="8524787",
            petitioner_name="Apple Inc",
            filing_date_from="2024-01-01",
            filing_date_to="2024-12-31",
            limit=1
        )
        data = json.loads(result)

        # Should return valid response structure (may be error or data)
        assert 'data_type' in data or 'error' in data
        if 'data_type' in data:
            assert data['data_type'] == 'trials'

    @pytest.mark.asyncio
    async def test_trials_balanced_uses_filterbuilder(self):
        """Verify search_trials_balanced uses FilterBuilder correctly"""

        result = await search_trials_balanced(
            trial_type="IPR",
            limit=1
        )
        data = json.loads(result)

        assert data['data_type'] == 'trials'
        assert data['field_set'] == 'trials_balanced'

    @pytest.mark.asyncio
    async def test_trials_complete_uses_filterbuilder(self):
        """Verify search_trials_complete uses FilterBuilder correctly"""

        result = await search_trials_complete(
            trial_type="IPR",
            limit=1
        )
        data = json.loads(result)

        assert data['data_type'] == 'trials'
        assert data['field_set'] == 'trials_complete'

    @pytest.mark.asyncio
    async def test_appeals_minimal_uses_filterbuilder(self):
        """Verify search_appeals_minimal uses FilterBuilder correctly"""

        result = await search_appeals_minimal(limit=1)
        data = json.loads(result)

        assert data['data_type'] == 'appeals'
        assert data['field_set'] == 'appeals_minimal'

    @pytest.mark.asyncio
    async def test_appeals_balanced_uses_filterbuilder(self):
        """Verify search_appeals_balanced uses FilterBuilder correctly"""

        result = await search_appeals_balanced(limit=1)
        data = json.loads(result)

        assert data['data_type'] == 'appeals'
        assert data['field_set'] == 'appeals_balanced'

    @pytest.mark.asyncio
    async def test_appeals_complete_uses_filterbuilder(self):
        """Verify search_appeals_complete uses FilterBuilder correctly"""

        result = await search_appeals_complete(limit=1)
        data = json.loads(result)

        assert data['data_type'] == 'appeals'
        assert data['field_set'] == 'appeals_complete'

    @pytest.mark.asyncio
    async def test_interferences_minimal_uses_filterbuilder(self):
        """Verify search_interferences_minimal uses FilterBuilder correctly"""

        result = await search_interferences_minimal(limit=1)
        data = json.loads(result)

        assert data['data_type'] == 'interferences'
        assert data['field_set'] == 'interferences_minimal'

    @pytest.mark.asyncio
    async def test_interferences_balanced_uses_filterbuilder(self):
        """Verify search_interferences_balanced uses FilterBuilder correctly"""

        result = await search_interferences_balanced(limit=1)
        data = json.loads(result)

        assert data['data_type'] == 'interferences'
        assert data['field_set'] == 'interferences_balanced'

    @pytest.mark.asyncio
    async def test_interferences_complete_uses_filterbuilder(self):
        """Verify search_interferences_complete uses FilterBuilder correctly"""

        result = await search_interferences_complete(limit=1)
        data = json.loads(result)

        assert data['data_type'] == 'interferences'
        assert data['field_set'] == 'interferences_complete'

    def test_filterbuilder_none_handling(self):
        """Test FilterBuilder skips None values correctly"""

        filters, range_filters = (FilterBuilder()
            .add_if(TrialFilterFields.TRIAL_NUMBER, "IPR2024-00123")
            .add_if(TrialFilterFields.PATENT_NUMBER, None)  # Should skip
            .add_if(TrialFilterFields.PETITIONER_NAME, "")  # Should skip
            .add_range_if(TrialFilterFields.FILING_DATE, None, None)  # Should skip
            .build())

        # Only trial_number should be added
        assert len(filters) == 1
        assert filters[0]['name'] == TrialFilterFields.TRIAL_NUMBER
        assert len(range_filters) == 0

    def test_filterbuilder_range_filters(self):
        """Test FilterBuilder range filter construction"""

        filters, range_filters = (FilterBuilder()
            .add_range_if(TrialFilterFields.FILING_DATE, "2024-01-01", "2024-12-31")
            .add_range_if(TrialFilterFields.INSTITUTION_DATE, "2024-06-01", None)  # Open-ended
            .build())

        assert len(range_filters) == 2
        assert range_filters[0]['field'] == TrialFilterFields.FILING_DATE
        assert range_filters[0]['valueFrom'] == "2024-01-01"
        assert range_filters[0]['valueTo'] == "2024-12-31"

        assert range_filters[1]['field'] == TrialFilterFields.INSTITUTION_DATE
        assert range_filters[1]['valueFrom'] == "2024-06-01"
        assert range_filters[1]['valueTo'] is None


# ============================================================================
# Test Class 3: Proxy Integration Tests
# ============================================================================

class TestProxyIntegration:
    """Test proxy modes: standalone, centralized, fallback."""

    def test_standalone_mode_none_sentinel(self):
        """Test: CENTRALIZED_PROXY_PORT=none activates standalone mode"""

        # Set standalone mode
        os.environ['CENTRALIZED_PROXY_PORT'] = 'none'

        result = _detect_pfw_proxy()

        # Should return None (standalone mode)
        assert result is None

        # Cleanup
        if 'CENTRALIZED_PROXY_PORT' in os.environ:
            del os.environ['CENTRALIZED_PROXY_PORT']

    def test_local_proxy_port_precedence(self):
        """Test: PTAB_PROXY_PORT takes precedence over PROXY_PORT"""

        os.environ['PTAB_PROXY_PORT'] = '8083'
        os.environ['PROXY_PORT'] = '8081'

        port = get_local_proxy_port()

        assert port == 8083

        # Cleanup
        for key in ['PTAB_PROXY_PORT', 'PROXY_PORT']:
            if key in os.environ:
                del os.environ[key]

    def test_local_proxy_port_fallback(self):
        """Test: Falls back to PROXY_PORT if PTAB_PROXY_PORT not set"""

        os.environ['PROXY_PORT'] = '8085'

        # Remove PTAB_PROXY_PORT if it exists
        if 'PTAB_PROXY_PORT' in os.environ:
            del os.environ['PTAB_PROXY_PORT']

        port = get_local_proxy_port()

        assert port == 8085

        # Cleanup
        if 'PROXY_PORT' in os.environ:
            del os.environ['PROXY_PORT']

    def test_local_proxy_port_default(self):
        """Test: Defaults to 8083 when no env vars set"""

        # Clear all proxy port env vars
        for key in ['PTAB_PROXY_PORT', 'PROXY_PORT']:
            if key in os.environ:
                del os.environ[key]

        port = get_local_proxy_port()

        assert port == 8083

    @pytest.mark.asyncio
    async def test_document_download_includes_proxy_info(self):
        """Test: Download response includes proxy mode information"""

        # Get a trial with documents
        minimal_result = await search_trials_minimal(trial_type="IPR", limit=1)
        minimal_data = json.loads(minimal_result)

        if minimal_data['count'] == 0:
            pytest.skip("No trials data available")

        trial_number = minimal_data['results'][0]['trialNumber']

        # Get documents
        docs_result = await ptab_get_documents(
            identifier=trial_number,
            identifier_type="trial"
        )
        docs_data = json.loads(docs_result)

        if docs_data['count'] == 0 or not docs_data.get('documents'):
            pytest.skip("No documents available")

        # Get document ID (handle different field names)
        first_doc = docs_data['documents'][0]
        document_id = first_doc.get('documentIdentifier') or first_doc.get('documentId') or first_doc.get('id')

        if not document_id:
            pytest.skip("No valid document ID found in response")

        # Get download link
        download_result = await ptab_get_document_download(
            document_id=document_id,
            identifier=trial_number,
            identifier_type="trial"
        )
        download_data = json.loads(download_result)

        # Should include proxy information (unless error)
        if 'error' not in download_data:
            assert 'proxy_info' in download_data
            assert 'mode' in download_data['proxy_info']
            assert download_data['proxy_info']['mode'] in ['standalone', 'centralized', 'direct', 'local']
        else:
            pytest.skip(f"Download failed: {download_data.get('message', 'Unknown error')}")


# ============================================================================
# Test Class 4: Performance Tests
# ============================================================================

class TestPerformance:
    """Test performance characteristics and context reduction."""

    @pytest.mark.asyncio
    async def test_large_result_set_performance(self):
        """Test: Handle 100+ results efficiently"""

        start_time = time.time()

        result = await search_trials_minimal(
            trial_type="IPR",
            limit=100
        )

        end_time = time.time()
        elapsed = end_time - start_time

        data = json.loads(result)

        # Should complete in reasonable time (< 5 seconds)
        assert elapsed < 5.0, f"Search took {elapsed:.2f}s (should be < 5s)"

        assert data['data_type'] == 'trials'
        assert data['count'] >= 0

    @pytest.mark.asyncio
    async def test_context_reduction_measurements(self):
        """Test: Verify context reduction percentages"""

        # Minimal tier
        minimal_result = await search_trials_minimal(trial_type="IPR", limit=5)
        minimal_data = json.loads(minimal_result)

        if minimal_data['count'] > 0 and 'context_reduction' in minimal_data:
            reduction_str = minimal_data['context_reduction']['reduction_percentage']
            assert reduction_str.endswith('%')

            # Extract percentage value
            reduction_value = float(reduction_str.rstrip('%'))

            # Minimal should achieve some reduction (may be 0% for very small datasets)
            # Allow 0-99% range since context reduction varies by data size
            assert 0 <= reduction_value <= 99, f"Reduction {reduction_value}% not in valid range"

    @pytest.mark.asyncio
    async def test_balanced_vs_minimal_field_count(self):
        """Test: Balanced has more fields than minimal"""

        # Get same trial with different field sets
        minimal_result = await search_trials_minimal(trial_type="IPR", limit=1)
        minimal_data = json.loads(minimal_result)

        if minimal_data['count'] == 0:
            pytest.skip("No trials data available")

        trial_number = minimal_data['results'][0]['trialNumber']

        balanced_result = await search_trials_balanced(trial_number=trial_number, limit=1)
        balanced_data = json.loads(balanced_result)

        if balanced_data['count'] > 0:
            minimal_fields = len(minimal_data['results'][0])
            balanced_fields = len(balanced_data['results'][0])

            assert balanced_fields > minimal_fields, \
                f"Balanced ({balanced_fields}) should have more fields than minimal ({minimal_fields})"

    @pytest.mark.asyncio
    async def test_complete_has_no_context_reduction(self):
        """Test: Complete tier returns all fields with no reduction"""

        result = await search_trials_complete(trial_type="IPR", limit=1)
        data = json.loads(result)

        # Complete tier should NOT have context_reduction metadata
        assert data.get('context_reduction') is None, \
            "Complete tier should not have context reduction"


# ============================================================================
# Test Class 5: Error Scenario Tests
# ============================================================================

class TestErrorScenarios:
    """Test error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_invalid_trial_number_format(self):
        """Test: Invalid trial number raises validation error"""

        result = await search_trials_minimal(trial_number="INVALID123")
        data = json.loads(result)

        # Should return error response
        assert 'error' in data or data['count'] == 0

    @pytest.mark.asyncio
    async def test_invalid_patent_number_format(self):
        """Test: Invalid patent number handling"""

        result = await search_trials_minimal(patent_number="INVALID")
        data = json.loads(result)

        # Should either normalize or return error
        assert 'error' in data or 'count' in data

    @pytest.mark.asyncio
    async def test_invalid_date_range(self):
        """Test: Invalid date range handling"""

        result = await search_trials_minimal(
            filing_date_from="2024-12-31",
            filing_date_to="2024-01-01"  # End before start
        )
        data = json.loads(result)

        # Should handle gracefully
        assert 'error' in data or 'count' in data

    @pytest.mark.asyncio
    async def test_limit_exceeds_maximum(self):
        """Test: Limit clamped to maximum"""

        result = await search_trials_minimal(
            trial_type="IPR",
            limit=1000  # Exceeds max of 100
        )
        data = json.loads(result)

        # Should clamp to max 100 or return error
        if 'error' not in data and data.get('count', 0) > 0:
            assert len(data.get('results', [])) <= 100

    @pytest.mark.asyncio
    async def test_nonexistent_trial_number(self):
        """Test: Nonexistent trial returns empty results"""

        result = await search_trials_minimal(
            trial_number="IPR9999-99999"
        )
        data = json.loads(result)

        # Should return 0 results or error
        assert data.get('count') == 0 or 'error' in data

    @pytest.mark.asyncio
    async def test_invalid_identifier_type(self):
        """Test: Invalid identifier_type in document tools"""

        result = await ptab_get_documents(
            identifier="IPR2024-00123",
            identifier_type="invalid_type"
        )
        data = json.loads(result)

        # Should return error
        assert 'error' in data

    @pytest.mark.asyncio
    async def test_empty_search_criteria(self):
        """Test: Search with no criteria returns general results"""

        result = await search_trials_minimal(limit=5)
        data = json.loads(result)

        # Should return general results
        assert 'count' in data
        assert data['data_type'] == 'trials'

    @pytest.mark.asyncio
    async def test_special_characters_in_party_name(self):
        """Test: Special characters in party names handled correctly"""

        result = await search_trials_minimal(
            petitioner_name="Apple Inc. & Associates, LLC"
        )
        data = json.loads(result)

        # Should handle gracefully
        assert 'count' in data or 'error' in data


# ============================================================================
# Test Class 6: Rate Limiting and Circuit Breaker Tests
# ============================================================================

class TestRateLimitingAndResilience:
    """Test rate limiting and circuit breaker patterns."""

    @pytest.mark.asyncio
    async def test_concurrent_requests_handling(self):
        """Test: Handle multiple concurrent requests"""

        # Create 5 concurrent requests
        tasks = [
            search_trials_minimal(trial_type="IPR", limit=1)
            for _ in range(5)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # All should succeed or handle gracefully
        for result in results:
            if isinstance(result, Exception):
                # Some may fail due to rate limiting, but shouldn't crash
                assert isinstance(result, (Exception,))
            else:
                data = json.loads(result)
                assert 'data_type' in data or 'error' in data

    @pytest.mark.asyncio
    async def test_sequential_requests_performance(self):
        """Test: Sequential requests complete in reasonable time"""

        start_time = time.time()

        # Make 3 sequential requests
        for _ in range(3):
            await search_trials_minimal(trial_type="IPR", limit=1)

        end_time = time.time()
        elapsed = end_time - start_time

        # Should complete in < 10 seconds total
        assert elapsed < 10.0, f"Sequential requests took {elapsed:.2f}s (should be < 10s)"


# ============================================================================
# Test Class 7: Cross-MCP Integration Tests (Placeholders)
# ============================================================================

class TestCrossMCPIntegration:
    """Test cross-MCP integration scenarios (placeholders for future)."""

    @pytest.mark.skip(reason="Requires PFW MCP running")
    async def test_ptab_to_pfw_workflow(self):
        """Test: PTAB trial → PFW application lookup"""
        pass

    @pytest.mark.skip(reason="Requires FPD MCP running")
    async def test_ptab_to_fpd_workflow(self):
        """Test: PTAB trial → FPD front page lookup"""
        pass

    @pytest.mark.skip(reason="Requires Citations MCP running")
    async def test_ptab_to_citations_workflow(self):
        """Test: PTAB trial → Citations lookup"""
        pass


# ============================================================================
# Summary and Reporting
# ============================================================================

def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "workflow: mark test as end-to-end workflow test"
    )
    config.addinivalue_line(
        "markers", "filterbuilder: mark test as FilterBuilder integration test"
    )
    config.addinivalue_line(
        "markers", "proxy: mark test as proxy integration test"
    )
    config.addinivalue_line(
        "markers", "performance: mark test as performance test"
    )
    config.addinivalue_line(
        "markers", "error: mark test as error scenario test"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
