"""Hermetic tests for the shared search pipeline (dup §2.1 refactor) and the
bulk auto-chunking path (TI-3). All API calls mocked via conftest's
mock_api_client seam."""

import json

from src.ptab_mcp.main import (
    search_appeals_minimal,
    search_interferences_minimal,
    search_trials_minimal,
)


def _trial_bag(n, start=0):
    return [
        {
            "trialNumber": f"IPR2024-{start + i:05d}",
            "trialMetaData": {"trialTypeCode": "IPR", "trialStatusCategory": "Instituted"},
        }
        for i in range(n)
    ]


class TestSearchPipeline:
    async def test_trials_minimal_happy_path(self, mock_api_client, mock_trial_search_response):
        mock_api_client.search_trials.return_value = mock_trial_search_response

        result = json.loads(await search_trials_minimal(trial_type="IPR", limit=5))

        assert result["data_type"] == "trials"
        assert result["field_set"] == "trials_minimal"
        assert result["count"] == 1
        assert result["results"][0]["trialNumber"] == "IPR2024-00123"
        assert "context_reduction" in result
        # Filters were built and forwarded
        kwargs = mock_api_client.search_trials.call_args.kwargs
        assert kwargs["pagination"] == {"offset": 0, "limit": 5}
        assert any(f["name"].endswith("trialTypeCode") for f in kwargs["filters"])

    async def test_trials_minimal_custom_fields(self, mock_api_client, mock_trial_search_response):
        mock_api_client.search_trials.return_value = mock_trial_search_response

        result = json.loads(await search_trials_minimal(
            trial_type="IPR", fields=["trialNumber"], limit=5))

        assert result["field_set"] == "custom"
        assert list(result["results"][0].keys()) == ["trialNumber"]

    async def test_validation_error_envelope(self, mock_api_client):
        result = json.loads(await search_trials_minimal(trial_number="NOT-A-TRIAL"))
        assert result["error"]
        assert result["error_type"] == "VALIDATION_ERROR"
        mock_api_client.search_trials.assert_not_called()

    async def test_api_error_passthrough(self, mock_api_client):
        mock_api_client.search_trials.return_value = {"error": True, "message": "boom"}
        result = json.loads(await search_trials_minimal(trial_type="IPR"))
        assert result["error"]

    async def test_appeals_minimal_happy_path(self, mock_api_client):
        mock_api_client.search_appeals.return_value = {
            "count": 1,
            "patentAppealDataBag": [{"appealNumber": "2025000943"}],
        }
        result = json.loads(await search_appeals_minimal(limit=3))
        assert result["data_type"] == "appeals"
        assert result["field_set"] == "appeals_minimal"

    async def test_interferences_minimal_happy_path(self, mock_api_client):
        mock_api_client.search_interferences.return_value = {
            "count": 1,
            "patentInterferenceDataBag": [{"interferenceNumber": "106035"}],
        }
        result = json.loads(await search_interferences_minimal(limit=3))
        assert result["data_type"] == "interferences"
        assert result["field_set"] == "interferences_minimal"


class TestBulkLookupChunking:
    """TI-3: the >100-entry auto-chunking path had zero coverage."""

    async def test_bulk_150_entries_uses_two_chunks(self, mock_api_client):
        trial_numbers = [f"IPR2024-{i:05d}" for i in range(150)]
        responses = [
            {"count": 100, "patentTrialProceedingDataBag": _trial_bag(100)},
            {"count": 50, "patentTrialProceedingDataBag": _trial_bag(50, start=100)},
        ]
        mock_api_client.search_trials.side_effect = responses

        result = json.loads(await search_trials_minimal(trial_number=trial_numbers))

        assert mock_api_client.search_trials.call_count == 2
        info = result["query_info"]
        assert info["bulk_lookup"] is True
        assert info["input_count"] == 150
        assert info["matched_count"] == 150
        assert info["chunks_used"] == 2
        assert "truncated" not in info
        assert result["count"] == 150
        # Each chunk call respects the API's 100-row hard cap
        for call in mock_api_client.search_trials.call_args_list:
            assert call.kwargs["pagination"]["limit"] == 100

    async def test_bulk_small_list_single_call(self, mock_api_client):
        trial_numbers = ["IPR2024-00001", "IPR2024-00002"]
        mock_api_client.search_trials.return_value = {
            "count": 1, "patentTrialProceedingDataBag": _trial_bag(1)}

        result = json.loads(await search_trials_minimal(trial_number=trial_numbers))

        assert mock_api_client.search_trials.call_count == 1
        info = result["query_info"]
        assert info["bulk_lookup"] is True
        assert info["input_count"] == 2
        assert info["matched_count"] == 1
        assert info["truncated"] is True

    async def test_bulk_over_200_rejected(self, mock_api_client):
        trial_numbers = [f"IPR2024-{i:05d}" for i in range(201)]
        result = json.loads(await search_trials_minimal(trial_number=trial_numbers))
        assert result["error"]
        assert result["error_type"] == "VALIDATION_ERROR"
        mock_api_client.search_trials.assert_not_called()


class TestContextReduction:
    """TI-4: the context-reduction value prop finally has hermetic coverage."""

    @staticmethod
    def _fat_trial(i):
        return {
            "trialNumber": f"IPR2024-{i:05d}",
            "trialMetaData": {
                "trialTypeCode": "IPR",
                "trialStatusCategory": "Instituted",
                "accordedFilingDate": "2024-01-15",
                "institutionDecisionDate": "2024-06-01",
                "finalDecisionDate": "2025-01-01",
                "lastModifiedDate": "2025-02-02",
            },
            "petitionerData": {
                "petitionerPartyName": "Apple Inc.",
                "petitionerCounselName": "Counsel A",
                "petitionerRealPartyName": "Apple RPI",
            },
            "patentOwnerData": {
                "patentOwnerName": "Samsung",
                "patentOwnerCounselName": "Counsel B",
                "patentNumber": "8524787",
            },
            "respondentData": {
                "patentNumber": "8524787",
                "patentTitle": "Widget",
                "applicationNumber": "12/345,678",
                "inventorName": "Jane Doe",
                "grantDate": "2013-09-03",
                "technologyCenterNumber": "2128",
            },
        }

    async def test_minimal_tier_reduces_context(self, mock_api_client):
        mock_api_client.search_trials.return_value = {
            "count": 5,
            "patentTrialProceedingDataBag": [self._fat_trial(i) for i in range(5)],
        }
        result = json.loads(await search_trials_minimal(trial_type="IPR", limit=5))

        reduction = result["context_reduction"]
        pct = float(reduction["reduction_percentage"].rstrip("%"))
        assert 0 < pct <= 99
        assert reduction["filtered_field_count"] < reduction["original_field_count"]

    async def test_balanced_returns_more_fields_than_minimal(self, mock_api_client):
        from src.ptab_mcp.main import search_trials_balanced

        payload = {
            "count": 1,
            "patentTrialProceedingDataBag": [self._fat_trial(0)],
        }
        mock_api_client.search_trials.return_value = payload
        minimal = json.loads(await search_trials_minimal(trial_type="IPR", limit=1))
        mock_api_client.search_trials.return_value = payload
        balanced = json.loads(await search_trials_balanced(trial_type="IPR", limit=1))

        assert (balanced["context_reduction"]["filtered_field_count"]
                >= minimal["context_reduction"]["filtered_field_count"])

    async def test_complete_tier_has_no_reduction(self, mock_api_client):
        from src.ptab_mcp.main import search_trials_complete

        mock_api_client.search_trials.return_value = {
            "count": 1,
            "patentTrialProceedingDataBag": [self._fat_trial(0)],
        }
        result = json.loads(await search_trials_complete(trial_type="IPR", limit=1))
        assert result.get("context_reduction") is None
