"""`ProceedingAdapter.fetch_proceeding_metadata` reads live bags, not dead ones.

`api/proceedings.py` had no direct test. All three branches read a bag the
payload does not carry, so the function returned `(None, None, date)` for every
proceeding in production while the test fixtures fabricated the missing bag and
kept it green:

  * trial: `respondentData` — a trial record has only trialNumber,
    lastModifiedDateTime, trialMetaData, regularPetitionerData and
    patentOwnerData (config/filter_field_mapping.py:92, verified 2026-07-02)
  * appeal: `decisionMetaData` and a root-level applicationNumber — neither
    exists; the serial is appellantData.applicationNumberText
    (field_configs.yaml:100)
  * interference: `interferenceMetaData.patentNumber` — the numbers are on
    seniorPartyData / juniorPartyData

The records below use the live bag names. Every fixture is shaped to the wire
slices probed 2026-09-02 and recorded in
tests/test_appeal_interference_field_paths.py. No network call.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from src.ptab_mcp.api.proceedings import get_adapter


@pytest.fixture
def client():
    c = Mock()
    for method in ("search_trials", "search_appeals", "search_interferences"):
        setattr(c, method, AsyncMock(return_value={}))
    return c


class TestTrialMetadata:
    async def test_reads_patent_and_application_from_patent_owner_data(self, client):
        client.search_trials.return_value = {
            "patentTrialProceedingDataBag": [{
                "trialNumber": "IPR2024-01353",
                "trialMetaData": {"accordedFilingDate": "2024-01-15"},
                "patentOwnerData": {
                    "patentNumber": "7883848",
                    "applicationNumberText": "13/456,789",
                },
            }],
        }

        patent, application, filing = await get_adapter("trial").fetch_proceeding_metadata(
            client, "IPR2024-01353")

        assert patent == "7883848"
        assert application == "13/456,789"
        assert filing == "2024-01-15"

    async def test_a_record_without_the_dead_bag_is_not_all_none(self, client):
        """The pre-fix read produced (None, None, date) against this exact record,
        which is the shape every live trial has."""
        client.search_trials.return_value = {
            "patentTrialProceedingDataBag": [{
                "trialNumber": "IPR2024-01353",
                "lastModifiedDateTime": "2024-05-16T10:00:00",
                "trialMetaData": {"accordedFilingDate": "2024-01-15"},
                "regularPetitionerData": {"realPartyInInterestName": "Apple Inc."},
                "patentOwnerData": {
                    "realPartyInInterestName": "Samsung Electronics",
                    "patentNumber": "7883848",
                },
            }],
        }

        patent, _, _ = await get_adapter("trial").fetch_proceeding_metadata(
            client, "IPR2024-01353")

        assert patent == "7883848"

    async def test_empty_result_returns_all_none(self, client):
        client.search_trials.return_value = {"patentTrialProceedingDataBag": []}

        assert await get_adapter("trial").fetch_proceeding_metadata(
            client, "IPR2024-01353") == (None, None, None)


class TestAppealMetadata:
    async def test_reads_the_serial_from_appellant_data(self, client):
        client.search_appeals.return_value = {
            "patentAppealDataBag": [{
                "appealNumber": "2026002664",
                "appellantData": {
                    "applicationNumberText": "90019821",
                    "groupArtUnitNumber": "3993",
                },
                "decisionData": {"decisionIssueDate": "2026-08-14"},
            }],
        }

        patent, application, decided = await get_adapter("appeal").fetch_proceeding_metadata(
            client, "2026002664")

        assert application == "90019821"
        assert decided == "2026-08-14"
        assert patent is None  # the appeals payload carries no patent number


class TestInterferenceMetadata:
    async def test_reads_the_numbers_from_the_senior_party_bag(self, client):
        client.search_interferences.return_value = {
            "patentInterferenceDataBag": [{
                "interferenceNumber": "106130",
                "interferenceMetaData": {"declarationDate": "2021-01-26"},
                "seniorPartyData": {
                    "patentNumber": "9012345",
                    "applicationNumberText": "14/987,654",
                },
            }],
        }

        patent, application, declared = await get_adapter(
            "interference").fetch_proceeding_metadata(client, "106130")

        assert patent == "9012345"
        assert application == "14/987,654"
        assert declared == "2021-01-26"
