"""Trial-search tier contract: the date filters, the deprecated alias, the
bulk list. Three defects from the 2026-09-03 skill QA ledger.

1. The minimal trials tier rejected institution_date_* and the decision-date
   filters at the schema, so an agent got a raw pydantic "Unexpected keyword
   argument" instead of results. The ranges are a property of the trials
   ENDPOINT, not of a tier's field set, so all three tiers now build them
   through one helper.
2. final_decision_date_* is a deprecated alias that ranges on
   trialMetaData.latestDecisionDate, a Federal Circuit docketing date on
   IPR2024-00990, and said nothing about it. query_info names the field now.
6. A bulk trial_number list reached the balanced and complete tiers and died
   in validate_trial_number's `.strip()` with a bare AttributeError; it now
   names the tier that takes a list.

All hermetic: the mock_api_client seam from conftest, no network.
"""

import json

import pytest

from src.ptab_mcp.config.filter_field_mapping import TrialFilterFields
from src.ptab_mcp.main import (
    search_trials_balanced,
    search_trials_complete,
    search_trials_minimal,
)

INSTITUTION = TrialFilterFields.INSTITUTION_DECISION_DATE
LATEST = TrialFilterFields.LATEST_DECISION_DATE


def _bag(trial="IPR2024-00990"):
    return {
        "count": 1,
        "patentTrialProceedingDataBag": [{"trialNumber": trial}],
    }


def _ranges(mock_api_client):
    """The range filters actually sent, keyed by API field name."""
    return {r["field"]: r for r in
            (mock_api_client.search_trials.call_args.kwargs["range_filters"] or [])}


# ---------------------------------------------------------------------------
# (1) The minimal tier accepts the date-range filters
# ---------------------------------------------------------------------------

class TestMinimalTierTakesTheDateFilters:
    """A raw pydantic "Unexpected keyword argument" is not an answer. The
    minimal field set already RETURNS institutionDecisionDate, so rejecting a
    filter on it was indefensible; latestDecisionDate is filterable on every
    tier and returned by balanced."""

    @pytest.mark.parametrize(
        "parameter",
        [
            "institution_date_from", "institution_date_to",
            "latest_decision_date_from", "latest_decision_date_to",
            "final_decision_date_from", "final_decision_date_to",
        ],
    )
    def test_parameter_is_in_the_minimal_signature(self, parameter):
        import inspect

        assert parameter in inspect.signature(search_trials_minimal).parameters

    async def test_institution_range_reaches_the_api(self, mock_api_client):
        mock_api_client.search_trials.return_value = _bag()

        await search_trials_minimal(
            institution_date_from="2025-01-01", institution_date_to="2025-12-31",
        )

        sent = _ranges(mock_api_client)[INSTITUTION]
        assert sent["valueFrom"] == "2025-01-01"
        assert sent["valueTo"] == "2025-12-31"

    async def test_latest_decision_range_reaches_the_api(self, mock_api_client):
        mock_api_client.search_trials.return_value = _bag()

        await search_trials_minimal(
            latest_decision_date_from="2026-01-01",
            latest_decision_date_to="2026-07-31",
        )

        assert _ranges(mock_api_client)[LATEST]["valueTo"] == "2026-07-31"

    @pytest.mark.parametrize(
        "tool", [search_trials_minimal, search_trials_balanced]
    )
    async def test_both_tiers_range_on_the_same_fields(self, mock_api_client, tool):
        mock_api_client.search_trials.return_value = _bag()

        await tool(
            institution_date_from="2025-03-07",
            latest_decision_date_from="2026-03-04",
        )

        assert set(_ranges(mock_api_client)) == {INSTITUTION, LATEST}

    async def test_a_bad_date_is_a_validation_error_not_a_traceback(
        self, mock_api_client
    ):
        mock_api_client.search_trials.return_value = _bag()

        result = json.loads(
            await search_trials_minimal(institution_date_from="03/07/2025")
        )

        assert result["error"] is True
        assert result["error_type"] == "VALIDATION_ERROR"

    async def test_no_date_filter_sends_no_ranges(self, mock_api_client):
        """A search that names no date must be byte-identical to before."""
        mock_api_client.search_trials.return_value = _bag()

        result = json.loads(await search_trials_minimal(trial_type="IPR"))

        assert not mock_api_client.search_trials.call_args.kwargs["range_filters"]
        assert "deprecated_alias_used" not in result["query_info"]


# ---------------------------------------------------------------------------
# (2) The deprecated alias says which field it ranged on
# ---------------------------------------------------------------------------

class TestFinalDecisionDateAliasIsExplicit:
    @pytest.mark.parametrize(
        "tool", [search_trials_minimal, search_trials_balanced]
    )
    async def test_alias_reports_the_field_it_ranged_on(self, mock_api_client, tool):
        mock_api_client.search_trials.return_value = _bag()

        result = json.loads(await tool(
            final_decision_date_from="2025-01-01",
            final_decision_date_to="2026-12-31",
        ))

        info = result["query_info"]
        assert info["deprecated_alias_used"] == [
            "final_decision_date_from", "final_decision_date_to",
        ]
        assert info["deprecated_alias_ranged_on"] == LATEST
        assert _ranges(mock_api_client)[LATEST]["valueFrom"] == "2025-01-01"

    async def test_the_note_names_the_federal_circuit_trap(self, mock_api_client):
        mock_api_client.search_trials.return_value = _bag()

        result = json.loads(
            await search_trials_balanced(final_decision_date_from="2025-01-01")
        )

        note = result["query_info"]["deprecated_alias_note"]
        assert LATEST in note
        assert "IPR2024-00990" in note
        assert "NO FINAL-DECISION-DATE FIELD" in note.upper()
        assert "latest_decision_date_from" in note

    async def test_the_honest_name_carries_no_alias_keys(self, mock_api_client):
        mock_api_client.search_trials.return_value = _bag()

        result = json.loads(
            await search_trials_balanced(latest_decision_date_from="2025-01-01")
        )

        assert "deprecated_alias_used" not in result["query_info"]
        assert "deprecated_alias_note" not in result["query_info"]

    async def test_an_overridden_alias_says_it_was_ignored(self, mock_api_client):
        """The honest name wins; a silently dropped parameter is the defect
        class this whole file exists for, so the drop is reported."""
        mock_api_client.search_trials.return_value = _bag()

        result = json.loads(await search_trials_balanced(
            latest_decision_date_from="2025-01-01",
            final_decision_date_from="2019-01-01",
        ))

        info = result["query_info"]
        assert info["deprecated_alias_ignored"] == ["final_decision_date_from"]
        assert "deprecated_alias_used" not in info
        assert _ranges(mock_api_client)[LATEST]["valueFrom"] == "2025-01-01"

    @pytest.mark.parametrize(
        "tool", [search_trials_minimal, search_trials_balanced]
    )
    def test_the_docstring_teaches_the_honest_name(self, tool):
        doc = tool.__doc__ or ""

        assert "latest_decision_date_from" in doc
        assert "trialMetaData.latestDecisionDate" in doc
        assert "DEPRECATED alias" in doc


# ---------------------------------------------------------------------------
# (6) A bulk list on balanced/complete names the tier that takes it
# ---------------------------------------------------------------------------

class TestBulkListIsMinimalOnly:
    @pytest.mark.parametrize(
        "tool", [search_trials_balanced, search_trials_complete]
    )
    async def test_a_list_is_a_guided_error(self, mock_api_client, tool):
        mock_api_client.search_trials.return_value = _bag()

        result = json.loads(
            await tool(trial_number=["IPR2024-01353", "IPR2024-00864"])
        )

        assert result["error"] is True
        assert result["error_type"] == "VALIDATION_ERROR"
        assert "PTAB_search_trials_minimal" in result["message"]
        # No request went out on a rejected input.
        mock_api_client.search_trials.assert_not_called()

    @pytest.mark.parametrize(
        "tool", [search_trials_balanced, search_trials_complete]
    )
    async def test_the_error_is_not_the_old_attribute_error(
        self, mock_api_client, tool
    ):
        mock_api_client.search_trials.return_value = _bag()

        result = json.loads(await tool(trial_number=["IPR2024-01353"]))

        assert "has no attribute" not in result["message"]

    async def test_minimal_still_takes_the_list(self, mock_api_client):
        mock_api_client.search_trials.return_value = _bag("IPR2024-01353")

        result = json.loads(await search_trials_minimal(
            trial_number=["IPR2024-01353", "IPR2024-00864"]
        ))

        assert result["query_info"]["bulk_lookup"] is True
        assert result["query_info"]["input_count"] == 2

    @pytest.mark.parametrize(
        "tool", [search_trials_balanced, search_trials_complete]
    )
    def test_the_docstring_points_at_the_bulk_tier(self, tool):
        assert "PTAB_search_trials_minimal" in (tool.__doc__ or "")
