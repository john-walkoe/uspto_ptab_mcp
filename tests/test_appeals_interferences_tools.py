"""Hermetic tool-level cover for the six appeals / interferences search tools.

Before this module, `src/ptab_mcp/tools/appeals.py` and
`src/ptab_mcp/tools/interferences.py` (815 lines between them) executed only
under `PTAB_RUN_NETWORK_TESTS=1`, because the only callers were the
`@pytest.mark.network` classes in `tests/test_workflow.py`. The adjacent
`tests/test_appeals.py` / `tests/test_interferences.py` drive the HTTP client's
endpoints, not the tools. That hole is why two defects survived review:

  * both `*_complete` tiers passed `max_limit=100` while their own docstrings
    promised "max 50" (the bodies were byte-identical copies of `*_balanced`), and
  * the interference tiers emitted TWO filter entries for
    `seniorPartyData.patentOwnerName` when `party_name` and `senior_party` were
    both supplied.

Both are pinned below. Every response fixture is a verbatim slice of a record
observed on the wire in the staging container on 2026-09-02 (appeal 2026002664,
interference 106130) — the same probe `tests/test_appeal_interference_field_paths.py`
records — with key names and nesting unmodified. Nothing here makes a network call.
"""

import json

import pytest

from src.ptab_mcp.tools.appeals import (
    search_appeals_balanced,
    search_appeals_complete,
    search_appeals_minimal,
)
from src.ptab_mcp.tools.interferences import (
    search_interferences_balanced,
    search_interferences_complete,
    search_interferences_minimal,
)


@pytest.fixture
def appeal_response():
    """Verbatim slice of a live appeals/decisions/search record (2026002664)."""
    return {
        "count": 1,
        "patentAppealDataBag": [{
            "appealNumber": "2026002664",
            "appealDocumentCategory": "Decision",
            "lastModifiedDateTime": "2026-08-14T20:17:05",
            "appealMetaData": {
                "appealFilingDate": "2026-07-08",
                "applicationTypeCategory": "REEXAM",
            },
            "appellantData": {
                "applicationNumberText": "90019821",
                "groupArtUnitNumber": "3993",
                "realPartyInInterestName": "Shenyang Industrai Co., LTD. et al.",
                "technologyCenterNumber": "3900",
            },
            "decisionData": {
                "appealOutcomeCategory": "Reversed",
                "decisionIssueDate": "2026-08-14",
                "decisionTypeCategory": "Decision",
                "issueTypeBag": ["102", "103"],
            },
        }],
    }


@pytest.fixture
def interference_response():
    """Verbatim slice of a live interferences/decisions/search record (106130)."""
    return {
        "count": 1,
        "patentInterferenceDataBag": [{
            "interferenceNumber": "106130",
            "lastModifiedDateTime": "2025-12-12T17:18:56",
            "interferenceMetaData": {
                "declarationDate": "2021-01-26",
                "interferenceStyleName": "LEE M. KAPLAN et al. v. PATRICE CANI et al.",
            },
            "seniorPartyData": {
                "patentOwnerName": "Kaplan",
                "technologyCenterNumber": "1600",
            },
            "juniorPartyData": {"patentOwnerName": "Cani"},
            "documentData": {
                "documentIdentifier": "106130-001",
                "decisionIssueDate": "2021-01-26",
            },
        }],
    }


def _filter_names(call_args):
    return [f["name"] for f in call_args.kwargs["filters"]]


class TestAppealsTools:
    async def test_minimal_forwards_filters_and_shapes_envelope(
            self, mock_api_client, appeal_response):
        mock_api_client.search_appeals.return_value = appeal_response

        result = json.loads(await search_appeals_minimal(art_unit="3993", limit=5))

        assert result["data_type"] == "appeals"
        assert result["field_set"] == "appeals_minimal"
        assert result["results"][0]["appealNumber"] == "2026002664"
        kwargs = mock_api_client.search_appeals.call_args.kwargs
        assert kwargs["pagination"] == {"offset": 0, "limit": 5}
        assert "appellantData.groupArtUnitNumber" in _filter_names(
            mock_api_client.search_appeals.call_args)

    async def test_balanced_forwards_its_extra_filters(
            self, mock_api_client, appeal_response):
        mock_api_client.search_appeals.return_value = appeal_response

        result = json.loads(await search_appeals_balanced(
            technology_center="3900", decision_outcome="Reversed", limit=5))

        assert result["field_set"] == "appeals_balanced"
        names = _filter_names(mock_api_client.search_appeals.call_args)
        assert "appellantData.technologyCenterNumber" in names
        assert "decisionData.appealOutcomeCategory" in names

    async def test_complete_selects_the_complete_field_set(
            self, mock_api_client, appeal_response):
        mock_api_client.search_appeals.return_value = appeal_response

        result = json.loads(await search_appeals_complete(art_unit="3993", limit=5))

        assert result["field_set"] == "appeals_complete"

    @pytest.mark.parametrize("tool,ceiling", [
        (search_appeals_minimal, 100),
        (search_appeals_balanced, 100),
        # The complete tier applies no field filtering, so its ceiling is 50 —
        # the value its docstring promises and the one tools/trials.py:736 uses.
        (search_appeals_complete, 50),
    ])
    async def test_limit_ceiling_matches_the_docstring(
            self, mock_api_client, appeal_response, tool, ceiling):
        mock_api_client.search_appeals.return_value = appeal_response

        accepted = json.loads(await tool(limit=ceiling))
        assert accepted.get("error") is not True

        rejected = json.loads(await tool(limit=ceiling + 1))
        assert rejected["error_type"] == "VALIDATION_ERROR"

    async def test_validation_error_does_not_call_the_api(self, mock_api_client):
        result = json.loads(await search_appeals_minimal(appeal_number="NOT-AN-APPEAL"))

        assert result["error_type"] == "VALIDATION_ERROR"
        mock_api_client.search_appeals.assert_not_called()

    async def test_offset_reaches_the_second_page(self, mock_api_client, appeal_response):
        mock_api_client.search_appeals.return_value = appeal_response

        await search_appeals_minimal(art_unit="3993", limit=10, offset=20)

        kwargs = mock_api_client.search_appeals.call_args.kwargs
        assert kwargs["pagination"] == {"offset": 20, "limit": 10}


class TestInterferencesTools:
    async def test_minimal_forwards_filters_and_shapes_envelope(
            self, mock_api_client, interference_response):
        mock_api_client.search_interferences.return_value = interference_response

        result = json.loads(await search_interferences_minimal(
            interference_number="106130", limit=5))

        assert result["data_type"] == "interferences"
        assert result["field_set"] == "interferences_minimal"
        assert result["results"][0]["interferenceNumber"] == "106130"
        assert "interferenceNumber" in _filter_names(
            mock_api_client.search_interferences.call_args)

    async def test_balanced_forwards_its_extra_filters(
            self, mock_api_client, interference_response):
        mock_api_client.search_interferences.return_value = interference_response

        result = json.loads(await search_interferences_balanced(
            technology_center="1600", junior_party="Cani", limit=5))

        assert result["field_set"] == "interferences_balanced"
        names = _filter_names(mock_api_client.search_interferences.call_args)
        assert "seniorPartyData.technologyCenterNumber" in names
        assert "juniorPartyData.patentOwnerName" in names

    async def test_complete_selects_the_complete_field_set(
            self, mock_api_client, interference_response):
        mock_api_client.search_interferences.return_value = interference_response

        result = json.loads(await search_interferences_complete(
            interference_number="106130", limit=5))

        assert result["field_set"] == "interferences_complete"

    @pytest.mark.parametrize("tool,ceiling", [
        (search_interferences_minimal, 100),
        (search_interferences_balanced, 100),
        (search_interferences_complete, 50),
    ])
    async def test_limit_ceiling_matches_the_docstring(
            self, mock_api_client, interference_response, tool, ceiling):
        mock_api_client.search_interferences.return_value = interference_response

        accepted = json.loads(await tool(limit=ceiling))
        assert accepted.get("error") is not True

        rejected = json.loads(await tool(limit=ceiling + 1))
        assert rejected["error_type"] == "VALIDATION_ERROR"

    async def test_validation_error_does_not_call_the_api(self, mock_api_client):
        result = json.loads(await search_interferences_minimal(patent_number="not-a-patent"))

        assert result["error_type"] == "VALIDATION_ERROR"
        mock_api_client.search_interferences.assert_not_called()

    async def test_party_name_and_senior_party_emit_one_filter_entry(
            self, mock_api_client, interference_response):
        """FilterBuilder APPENDS, so both mapping to SENIOR_PARTY_NAME used to put
        two entries for one field name into a single request. The ODP endpoint's
        handling of a repeated filter name is unspecified (AND that can never
        match, or a silent last-wins discard), so the clause is collapsed at build
        time and the more specific senior_party wins."""
        mock_api_client.search_interferences.return_value = interference_response

        await search_interferences_balanced(
            party_name="Kaplan", senior_party="Cani", limit=5)

        filters = mock_api_client.search_interferences.call_args.kwargs["filters"]
        senior = [f for f in filters if f["name"] == "seniorPartyData.patentOwnerName"]
        assert len(senior) == 1
        assert senior[0]["value"] == ["Cani"]

    async def test_party_name_alone_still_scopes_the_senior_party(
            self, mock_api_client, interference_response):
        mock_api_client.search_interferences.return_value = interference_response

        await search_interferences_minimal(party_name="Kaplan", limit=5)

        filters = mock_api_client.search_interferences.call_args.kwargs["filters"]
        senior = [f for f in filters if f["name"] == "seniorPartyData.patentOwnerName"]
        assert len(senior) == 1
        assert senior[0]["value"] == ["Kaplan"]
