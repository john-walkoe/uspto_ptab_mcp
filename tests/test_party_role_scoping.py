"""Party-name role scoping on the trials search tools.

Two live defects, reproduced 2026-08-30 against the USPTO ODP API and fixed
here (see util/party_scope.py for the probe record):

1. A `filters` entry naming a party field is NOT role-scoped. Asking for
   petitioner_name='WIZ' returned 17 proceedings, five of which
   (IPR2025-01083..-01087) have Orca Security as the PETITIONER and Wiz as the
   patent owner. "Trials X filed" silently became "trials mentioning X".
2. patent_owner_name mapped to patentOwnerData.patentOwnerName, which the live
   payload never populates — the name is in patentOwnerData.
   realPartyInInterestName. Every patent_owner_name search returned zero, which
   reads as "never challenged".

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
from src.ptab_mcp.util.party_scope import (
    build_party_scope_query,
    field_clause,
    strip_scoped_filters,
)

PET = "regularPetitionerData.realPartyInInterestName"
OWNER = "patentOwnerData.realPartyInInterestName"
OWNER_DEAD = "patentOwnerData.patentOwnerName"


def _bag(trial="IPR2024-00864"):
    return {
        "count": 1,
        "patentTrialProceedingDataBag": [
            {
                "trialNumber": trial,
                "regularPetitionerData": {"realPartyInInterestName": "WIZ, Inc."},
                "patentOwnerData": {"realPartyInInterestName": "Orca Security Ltd."},
            }
        ],
    }


# ---------------------------------------------------------------------------
# The clause builder
# ---------------------------------------------------------------------------

class TestPartyScopeQuery:
    def test_single_token_clause(self):
        assert field_clause([PET], "WIZ") == f'{PET}:("WIZ")'

    def test_and_joined_value_becomes_quoted_tokens(self):
        # build_and_query has already turned "Apple Inc." into "Apple AND Inc."
        assert field_clause([PET], "Apple AND Inc.") == f'{PET}:("Apple" AND "Inc.")'

    def test_several_fields_or_together(self):
        assert field_clause([OWNER, OWNER_DEAD], "Orca") == (
            f'({OWNER}:("Orca") OR {OWNER_DEAD}:("Orca"))'
        )

    def test_two_party_clauses_and_together(self):
        q = build_party_scope_query((([PET], "WIZ"), ([OWNER], "Orca")))
        assert q == f'{PET}:("WIZ") AND {OWNER}:("Orca")'

    def test_no_values_means_no_query(self):
        assert build_party_scope_query((([PET], None), ([OWNER], ""))) is None

    @pytest.mark.parametrize(
        "hostile",
        [
            'WIZ" OR patentOwnerData.realPartyInInterestName:"Orca',
            "WIZ\\",
            'WIZ OR "*"',
        ],
    )
    def test_quotes_and_operators_cannot_escape_the_phrase(self, hostile):
        """validate_party_name already rejects these; the builder is the
        second line, so a future caller that skips validation cannot inject
        a clause."""
        clause = field_clause([PET], hostile)

        # Exactly one quoted phrase per token, no stray quote or backslash.
        assert clause.startswith(f"{PET}:(")
        assert clause.endswith(")")
        body = clause[len(PET) + 2:-1]
        assert body.count('"') % 2 == 0
        assert "\\" not in clause
        # No bare operator survived into a token position.
        assert '"OR"' not in clause and '"AND"' not in clause

    def test_strip_scoped_filters_leaves_everything_else(self):
        filters = [
            {"name": "trialNumber", "value": ["IPR2024-00864"]},
            {"name": PET, "value": ["WIZ"]},
            {"name": "trialMetaData.trialTypeCode", "value": ["IPR"]},
        ]

        assert strip_scoped_filters(filters, [PET]) == [
            {"name": "trialNumber", "value": ["IPR2024-00864"]},
            {"name": "trialMetaData.trialTypeCode", "value": ["IPR"]},
        ]


# ---------------------------------------------------------------------------
# Defect 1 — petitioner_name is scoped to the petitioner side
# ---------------------------------------------------------------------------

class TestPetitionerRoleScoping:
    async def test_petitioner_name_is_sent_as_a_scoped_query(self, mock_api_client):
        mock_api_client.search_trials.return_value = _bag()

        await search_trials_minimal(petitioner_name="WIZ", limit=5)

        kwargs = mock_api_client.search_trials.call_args.kwargs
        assert kwargs["q"] == f'{PET}:("WIZ")'
        # The unscoped filter must NOT also go up: it would re-admit the
        # patent-owner-side matches the q clause exists to exclude.
        assert not any(f["name"] == PET for f in (kwargs["filters"] or []))

    async def test_ledger_still_names_the_field(self, mock_api_client):
        """query_info stays the provenance record — a caller can still see
        which API field petitioner_name resolved to, and the AND-join is
        still visible in the value."""
        mock_api_client.search_trials.return_value = _bag()

        result = json.loads(
            await search_trials_minimal(petitioner_name="WIZ, Inc.", limit=3)
        )

        assert result["query_info"]["filters"][0]["name"] == PET
        assert result["query_info"]["filters"][0]["value"] == ["WIZ, AND Inc."]
        assert result["query_info"]["party_role_scoped"] == [PET]
        assert "EITHER party" in result["query_info"]["party_role_scope_note"]

    async def test_other_filters_still_travel_as_filters(self, mock_api_client):
        mock_api_client.search_trials.return_value = _bag()

        await search_trials_minimal(
            petitioner_name="WIZ", trial_type="IPR", limit=5
        )

        kwargs = mock_api_client.search_trials.call_args.kwargs
        assert kwargs["q"] == f'{PET}:("WIZ")'
        assert [f["name"] for f in kwargs["filters"]] == [
            "trialMetaData.trialTypeCode"
        ]

    async def test_no_party_filter_sends_no_query_at_all(self, mock_api_client):
        """A search that names no party must be byte-identical to what it was
        before role scoping existed."""
        mock_api_client.search_trials.return_value = _bag()

        result = json.loads(await search_trials_minimal(trial_type="IPR", limit=5))

        kwargs = mock_api_client.search_trials.call_args.kwargs
        assert "q" not in kwargs
        assert "party_role_scoped" not in result["query_info"]

    @pytest.mark.parametrize(
        "tool", [search_trials_minimal, search_trials_balanced, search_trials_complete]
    )
    async def test_every_tier_scopes(self, mock_api_client, tool):
        mock_api_client.search_trials.return_value = _bag()

        await tool(petitioner_name="WIZ", limit=3)

        kwargs = mock_api_client.search_trials.call_args.kwargs
        assert kwargs["q"] == f'{PET}:("WIZ")'
        assert not any(f["name"] == PET for f in (kwargs["filters"] or []))

    async def test_bulk_trial_number_chunks_carry_the_scope(self, mock_api_client):
        """The >100-entry chunking path builds its own filter list per chunk
        and must strip and re-scope there too."""
        mock_api_client.search_trials.return_value = _bag()

        await search_trials_minimal(
            trial_number=[f"IPR2024-{i:05d}" for i in range(1, 120)],
            petitioner_name="WIZ",
        )

        for call in mock_api_client.search_trials.call_args_list:
            kwargs = call.kwargs
            assert kwargs["q"] == f'{PET}:("WIZ")'
            assert not any(f["name"] == PET for f in (kwargs["filters"] or []))


# ---------------------------------------------------------------------------
# Defect 2 — patent_owner_name points at the populated field
# ---------------------------------------------------------------------------

class TestPatentOwnerField:
    def test_constant_points_at_the_populated_field(self):
        assert TrialFilterFields.PATENT_OWNER_NAME == OWNER
        assert TrialFilterFields.PATENT_OWNER_NAME_LEGACY == OWNER_DEAD

    async def test_patent_owner_name_queries_the_populated_field(self, mock_api_client):
        mock_api_client.search_trials.return_value = _bag()

        result = json.loads(
            await search_trials_minimal(patent_owner_name="Orca", limit=5)
        )

        kwargs = mock_api_client.search_trials.call_args.kwargs
        assert kwargs["q"] == f'({OWNER}:("Orca") OR {OWNER_DEAD}:("Orca"))'
        assert result["query_info"]["filters"][0]["name"] == OWNER

    async def test_the_dead_field_survives_only_as_a_fallback(self, mock_api_client):
        """patentOwnerData.patentOwnerName is unpopulated today. It is OR-ed
        in so the search self-heals if USPTO ever fills it, but it must never
        be the field the query depends on."""
        mock_api_client.search_trials.return_value = _bag()

        await search_trials_minimal(patent_owner_name="Orca Security", limit=5)

        q = mock_api_client.search_trials.call_args.kwargs["q"]
        assert q.index(OWNER + ":") < q.index(OWNER_DEAD + ":")
        assert q.startswith("(") and " OR " in q

    def test_the_minimal_field_set_asks_for_the_populated_field(self):
        """The response side of the same defect: trials_minimal used to
        request patentOwnerData.patentOwnerName, so a patent-owner search
        returned rows with no patent owner name on them."""
        from src.ptab_mcp.runtime import field_manager

        fields = field_manager.get_fields("trials_minimal")

        assert OWNER in fields
        assert OWNER_DEAD not in fields

    async def test_both_parties_intersect(self, mock_api_client):
        mock_api_client.search_trials.return_value = _bag()

        await search_trials_minimal(
            petitioner_name="WIZ", patent_owner_name="Orca", limit=5
        )

        q = mock_api_client.search_trials.call_args.kwargs["q"]
        assert q == (
            f'{PET}:("WIZ") AND ({OWNER}:("Orca") OR {OWNER_DEAD}:("Orca"))'
        )
