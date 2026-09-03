"""Hermetic tests for the shared search pipeline (dup §2.1 refactor) and the
bulk auto-chunking path (TI-3). All API calls mocked via conftest's
mock_api_client seam."""

import json

from src.ptab_mcp.main import (
    ptab_get_documents,
    search_appeals_minimal,
    search_interferences_minimal,
    search_trials_minimal,
)

# The exact envelope the USPTO PTAB API's "zero matching records" 404
# produces (verified live 2026-08-16), reproduced here rather than imported
# so the test also pins the wire shape run_search's mapping depends on.
_NO_MATCH_404 = {
    "error": (
        'API error: {"code":"404","detailedMessage":"No matching records '
        'found, refine your search criteria and try again"}'
    ),
    "status_code": 404,
    "success": False,
    "request_id": "abcd1234",
}


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
        assert result["results"][0]["trialNumber"] == "IPR2024-01353"
        assert "context_reduction" in result
        # Filters were built and forwarded
        kwargs = mock_api_client.search_trials.call_args.kwargs
        assert kwargs["pagination"] == {"offset": 0, "limit": 5}
        assert any(f["name"].endswith("trialTypeCode") for f in kwargs["filters"])

    async def test_trials_minimal_delivers_every_configured_field(
            self, mock_api_client, mock_trial_search_response):
        """The trials equivalent of the appeals/interferences field-path guard.

        `format_proceeding_response` already reports configured-but-absent paths
        in `fields_absent`; nothing asserted on it, so the canonical fixture was
        free to model a payload the API does not emit. It supplied one of the
        twelve fields `trials_minimal` declares, plus a `respondentData` bag that
        does not exist, and that is what kept the dead read in
        api/proceedings.py green.
        """
        mock_api_client.search_trials.return_value = mock_trial_search_response

        result = json.loads(await search_trials_minimal(trial_type="IPR", limit=5))

        assert "fields_absent" not in result, (
            "configured trials_minimal paths missing from the fixture payload: "
            f"{result.get('fields_absent', {}).get('fields')}"
        )
        row = result["results"][0]
        assert row["regularPetitionerData"]["realPartyInInterestName"] == "Apple Inc."
        assert row["patentOwnerData"]["realPartyInInterestName"] == "Samsung Electronics"
        assert "respondentData" not in row

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


class TestNoMatchesMapping:
    """The USPTO PTAB API signals zero matches with a raw HTTP 404 error
    envelope instead of an empty result set (verified live 2026-08-16).
    run_search (util/search_runner.py) maps that specific shape to a clean
    empty result; every other error shape — including other 404s — still
    passes through untouched, and document-list/by-id 404s are unaffected
    (documents.py deliberately doesn't call run_search)."""

    async def test_trials_no_matches_maps_to_empty_with_note(self, mock_api_client):
        mock_api_client.search_trials.return_value = dict(_NO_MATCH_404)

        result = json.loads(await search_trials_minimal(patent_owner_name="Broadcom"))

        assert "error" not in result
        assert result["data_type"] == "trials"
        assert result["count"] == 0
        assert result["results"] == []
        assert "No matching records" in result["note"]
        assert "Broadcom" in result["note"] or "exact form" in result["note"]

    async def test_appeals_no_matches_maps_to_empty_with_note(self, mock_api_client):
        mock_api_client.search_appeals.return_value = dict(_NO_MATCH_404)

        result = json.loads(await search_appeals_minimal(limit=3))

        assert "error" not in result
        assert result["data_type"] == "appeals"
        assert result["count"] == 0
        assert result["results"] == []
        assert "No matching records" in result["note"]

    async def test_interferences_no_matches_maps_to_empty_with_note(self, mock_api_client):
        mock_api_client.search_interferences.return_value = dict(_NO_MATCH_404)

        result = json.loads(await search_interferences_minimal(limit=3))

        assert "error" not in result
        assert result["data_type"] == "interferences"
        assert result["count"] == 0
        assert result["results"] == []
        assert "No matching records" in result["note"]

    async def test_non_no_matches_404_is_a_real_error(self, mock_api_client):
        """A 404 that isn't the no-matches marker (e.g. an actually-invalid
        request) must still surface as a real error, not an empty result.

        The assertion moved off a top-level `status_code`: that was the API
        layer's own envelope shape reaching the caller verbatim, where
        `"error"` is the message STRING while every other tool exit produces
        `"error": True`. The status code is still reported, under `details`.
        """
        mock_api_client.search_trials.return_value = {
            "error": "API error: not found",
            "status_code": 404,
            "success": False,
        }

        result = json.loads(await search_trials_minimal(trial_type="IPR"))

        assert result["error"] is True
        assert result["error_type"] == "API_ERROR"
        assert result["details"]["status_code"] == 404

    async def test_non_404_error_is_a_real_error(self, mock_api_client):
        mock_api_client.search_trials.return_value = {
            "error": "API error: internal server error",
            "status_code": 500,
            "success": False,
        }

        result = json.loads(await search_trials_minimal(trial_type="IPR"))

        assert result["error"] is True
        assert result["error_type"] == "API_ERROR"
        assert result["details"]["status_code"] == 500

    async def test_a_timeout_envelope_is_categorized_as_a_timeout(self, mock_api_client):
        """RATE_LIMIT_ERROR / TIMEOUT_ERROR / INTERNAL_ERROR were declared in
        the ErrorType Literal and never emitted, so a timeout, an open circuit
        and a server bug all reached the model labeled API_ERROR."""
        mock_api_client.search_trials.return_value = {
            "error": "Request timeout - please try again",
            "status_code": 408,
            "success": False,
        }

        result = json.loads(await search_trials_minimal(trial_type="IPR"))

        assert result["error_type"] == "TIMEOUT_ERROR"

    async def test_an_open_circuit_is_categorized_as_a_rate_limit(self, mock_api_client):
        from src.ptab_mcp.shared.circuit_breaker import CircuitBreakerOpenError

        mock_api_client.search_trials.side_effect = CircuitBreakerOpenError("Trials")

        result = json.loads(await search_trials_minimal(trial_type="IPR"))

        assert result["error"] is True
        assert result["error_type"] == "RATE_LIMIT_ERROR"

    async def test_bulk_lookup_no_matches_maps_to_empty(self, mock_api_client):
        """The trial_number bulk-lookup path (trials.py's _fetch_bulk_trials)
        makes its own API call outside run_search and must independently
        recognize the same no-matches shape."""
        mock_api_client.search_trials.return_value = dict(_NO_MATCH_404)

        result = json.loads(await search_trials_minimal(
            trial_number=["IPR2024-99991", "IPR2024-99992"]))

        assert "error" not in result
        assert result["count"] == 0
        assert result["results"] == []
        assert "No matching records" in result["note"]
        assert result["query_info"]["bulk_lookup"] is True

    async def test_document_list_404_stays_error(self, mock_api_client):
        """Document-list-by-id lookups (documents.py) are deliberately NOT
        routed through run_search, so the same no-matches-shaped 404 must
        still surface as a raw error there."""
        mock_api_client.search_trial_documents.return_value = dict(_NO_MATCH_404)

        result = json.loads(await ptab_get_documents(identifier="IPR2024-01353"))

        assert result["error"]
        assert result["status_code"] == 404


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
        # Unmatched INPUT, not truncated OUTPUT — the two used to share one
        # `truncated: true` flag that read as "records were dropped".
        assert info["unmatched_input_count"] == 1
        assert "unmatched_input_note" in info
        assert "truncated" not in info

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
            # Live bag names only. A fabricated respondentData bag would inflate
            # the measured reduction with fields the API never sends.
            "regularPetitionerData": {
                "realPartyInInterestName": "Apple Inc.",
                "counselName": "Counsel A",
                "partyName": "Apple Inc.",
            },
            "patentOwnerData": {
                "realPartyInInterestName": "Samsung",
                "counselName": "Counsel B",
                "patentNumber": "7883848",
                "applicationNumberText": "12/345,678",
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
