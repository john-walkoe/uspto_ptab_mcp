"""Appeals / interferences minimal- and balanced-tier field paths.

Regression cover for the 2026-09-02 under-return: `PTAB_get_field_configs`
declared 9 fields for `appeals_minimal` and a live response carried 4 of them;
`interferences_minimal` declared 6 and carried 2. The cause was not sparse
upstream data and not the API's field-selection parameter. The configured
dotted paths simply did not exist in the payload, so the client-side filter,
which copies only what it finds, dropped them without a word.

Every fixture below is a verbatim slice of a record observed on the wire in
the staging container on 2026-09-02 (appeal 2026002664, interference 106130),
key names and nesting unmodified. Nothing here makes a network call.
"""

import json
from pathlib import Path

import pytest

from src.ptab_mcp.config.field_manager import FieldManager
from src.ptab_mcp.util.response_formatter import format_proceeding_response

CONFIG_PATH = Path(__file__).parent.parent / "field_configs.yaml"


@pytest.fixture
def field_manager():
    """FieldManager over the SHIPPED field_configs.yaml, not a test double.

    The bug was in that file, so a test against a hand-written config would
    have passed throughout.
    """
    fm = FieldManager(CONFIG_PATH)
    assert not fm.is_fallback(), "shipped field_configs.yaml failed to load"
    return fm


@pytest.fixture
def live_appeal_response():
    """Live appeal decision record (appeal 2026002664, probed 2026-09-02).

    Note what is NOT here: no root-level applicationNumber, no examinerData
    bag, no applicationData bag, and no decisionDate / decisionOutcome /
    decisionTypeCodeDescription under documentData.
    """
    return {
        "count": 164701,
        "patentAppealDataBag": [{
            "appealNumber": "2026002664",
            "appealDocumentCategory": "Decision",
            "lastModifiedDateTime": "2026-08-14T20:17:05",
            "appealMetaData": {
                "appealFilingDate": "2026-07-08",
                "appealLastModifiedDateTime": "2026-08-14T13:10:58",
                "appealLastModifiedDate": "2026-08-14",
                "applicationTypeCategory": "REEXAM",
                "fileDownloadURI": "https://api.uspto.gov/api/v1/patent/ptab-files/APP/2026/002664/2026002664.zip",
            },
            "appellantData": {
                "applicationNumberText": "90019821",
                "counselName": "SHUMAKER, LOOP & KENDRICK, LLP",
                "groupArtUnitNumber": "3993",
                "inventorName": "7503696",
                "realPartyInInterestName": "Shenyang Industrai Co., LTD. et al.",
                "patentOwnerName": "Ha,Jae-Ho et al",
                "technologyCenterNumber": "3900",
            },
            "documentData": {
                "documentFilingDate": "2026-08-14",
                "documentIdentifier": "f82b00cb-96b1-4e53-a4bd-e006cfefaf03",
                "documentName": "Decision_2026002664_08-14-2026.pdf",
                "documentSizeQuantity": 278186,
                "documentOCRText": "a golf club head indicia and methods ...",
                "documentTypeDescriptionText": "Paper",
                "fileDownloadURI": "https://api.uspto.gov/api/v1/patent/ptab-files/APP/2026/002664/f82b00cb.pdf",
            },
            "decisionData": {
                "appealOutcomeCategory": "Reversed",
                "statuteAndRuleBag": ["35 USC 134"],
                "decisionIssueDate": "2026-08-14",
                "decisionTypeCategory": "Decision",
                "issueTypeBag": ["102", "103"],
            },
        }],
    }


@pytest.fixture
def live_interference_response():
    """Live interference record (interference 106130, probed 2026-09-02).

    Note what is NOT here: no partyData bag and no decisionData bag. The
    parties are seniorPartyData / juniorPartyData and the decision fields sit
    inside documentData.
    """
    return {
        "count": 1812,
        "patentInterferenceDataBag": [{
            "interferenceNumber": "106130",
            "lastModifiedDateTime": "2025-12-12T17:18:56",
            "interferenceMetaData": {
                "interferenceLastModifiedDateTime": "2025-11-13T00:00:00",
                "interferenceLastModifiedDate": "2025-11-13",
                "declarationDate": "2021-01-26",
                "interferenceStyleName": (
                    "LEE M. KAPLAN, ALICE P. LIOU, PETER J. TURNBAUGH, and "
                    "JASON L. HARRIS v. PATRICE CANI, AMANDINE EVERARD, "
                    "CLARA BELZER, and WILLEM DE VOS"
                ),
                "fileDownloadURI": "https://api.uspto.gov/api/v1/patent/ptab-files/INTF/106130/106130.zip",
            },
            "seniorPartyData": {
                "applicationNumberText": "14443829",
                "counselName": "ALSTON & BIRD and GEMINI LAW LLP ",
                "groupArtUnitNumber": "1651",
                "inventorName": "Patrice Cani et al",
                "patentOwnerName": "CANI, PATRICE; EVERARD, Amandine; BELZER, Clara; DE VOS Willem",
                "publicationDate": "2015-10-29",
                "publicationNumber": "US20150306152A1",
                "realPartyInInterestName": "UNIVERSITE CATHOLIQUE DE LOUVAIN; WAGENINGEN UNIVERSITEIT",
                "technologyCenterNumber": "1600",
            },
            "juniorPartyData": {
                "applicationNumberText": "14862663",
                "counselName": "ROTHWELL, FIGG, ERNST & MANBECK, P.C. and LATHROP GAGE LLP",
                "grantDate": "2018-12-11",
                "groupArtUnitNumber": "1651",
                "inventorName": "Lee M. Kaplan et al",
                "patentNumber": "10149867",
                "publicationDate": "2016-04-28",
                "publicationNumber": "US20160113971A1",
                "realPartyInInterestName": "Ethicon Endo-Surgery, Inc.; The General Hospital Corporation",
                "technologyCenterNumber": "1600",
            },
            "documentData": {
                "documentIdentifier": "229ba0b8d5f70d2e45cc36b79476f56f3faf51bd26c7ccc977208e7b",
                "documentName": "106130_106130-jd-20250128.pdf",
                "documentSizeQuantity": 97923,
                "documentOCRText": "Microsoft Word - 106,130 Judgment ...",
                "documentTitleText": "Judgment 37 C.F.R. 41.127(a)",
                "interferenceOutcomeCategory": "Judgment",
                "statuteAndRuleBag": ["37 CFR 41.127(a)"],
                "decisionIssueDate": "2025-01-28",
                "decisionTypeCategory": "Decision",
                "fileDownloadURI": "https://api.uspto.gov/api/v1/patent/ptab-files/INTF/106130/Intf508.pdf",
                "documentFilingDate": "2025-01-28",
            },
        }],
    }


# ---------------------------------------------------------------------------
# The configured sets are now satisfiable by the real payload
# ---------------------------------------------------------------------------


def test_appeals_minimal_delivers_every_configured_field(
    field_manager, live_appeal_response
):
    """All 9 configured appeals_minimal fields survive the filter.

    Four of them (application number, decision date, decision type, outcome)
    plus the appellant name were being dropped; the record only ever answered
    appealNumber, TC, art unit and documentFilingDate.
    """
    filtered = field_manager.filter_response(live_appeal_response, "appeals_minimal")
    record = filtered["patentAppealDataBag"][0]

    assert record["appealNumber"] == "2026002664"
    assert record["appellantData"]["applicationNumberText"] == "90019821"
    assert record["appellantData"]["realPartyInInterestName"] == (
        "Shenyang Industrai Co., LTD. et al."
    )
    assert record["appellantData"]["technologyCenterNumber"] == "3900"
    assert record["appellantData"]["groupArtUnitNumber"] == "3993"
    assert record["documentData"]["documentFilingDate"] == "2026-08-14"
    assert record["decisionData"]["decisionIssueDate"] == "2026-08-14"
    assert record["decisionData"]["decisionTypeCategory"] == "Decision"
    assert record["decisionData"]["appealOutcomeCategory"] == "Reversed"

    assert filtered["context_info"]["fields_absent"] == []


def test_interferences_minimal_delivers_party_and_outcome(
    field_manager, live_interference_response
):
    """All 8 configured interferences_minimal fields survive the filter.

    A live response used to carry interferenceNumber and documentFilingDate
    and nothing else: senior party, junior party, decision date and decision
    type all named a non-existent bag.
    """
    filtered = field_manager.filter_response(
        live_interference_response, "interferences_minimal"
    )
    record = filtered["patentInterferenceDataBag"][0]

    assert record["interferenceNumber"] == "106130"
    assert "v. PATRICE CANI" in record["interferenceMetaData"]["interferenceStyleName"]
    assert record["seniorPartyData"]["realPartyInInterestName"].startswith(
        "UNIVERSITE CATHOLIQUE"
    )
    assert record["juniorPartyData"]["realPartyInInterestName"].startswith(
        "Ethicon Endo-Surgery"
    )
    assert record["documentData"]["documentFilingDate"] == "2025-01-28"
    assert record["documentData"]["decisionIssueDate"] == "2025-01-28"
    assert record["documentData"]["decisionTypeCategory"] == "Decision"
    assert record["documentData"]["interferenceOutcomeCategory"] == "Judgment"

    assert filtered["context_info"]["fields_absent"] == []


def test_appeals_balanced_expands_real_bags_only(
    field_manager, live_appeal_response
):
    """appeals_balanced wildcards land on bags that exist.

    examinerData.* expanded to nothing on every record ever returned, which is
    silent by design: an unmatched wildcard prefix has no path to report.
    """
    filtered = field_manager.filter_response(live_appeal_response, "appeals_balanced")
    record = filtered["patentAppealDataBag"][0]

    assert "examinerData" not in record
    assert record["appellantData"]["counselName"].startswith("SHUMAKER")
    assert record["decisionData"]["issueTypeBag"] == ["102", "103"]
    assert record["appealMetaData"]["appealFilingDate"] == "2026-07-08"
    # documentOCRText stays out of the balanced tier
    assert "documentOCRText" not in record["documentData"]


def test_interferences_balanced_expands_both_party_bags(
    field_manager, live_interference_response
):
    """interferences_balanced returns senior AND junior party data."""
    filtered = field_manager.filter_response(
        live_interference_response, "interferences_balanced"
    )
    record = filtered["patentInterferenceDataBag"][0]

    assert "partyData" not in record
    assert "decisionData" not in record
    assert record["seniorPartyData"]["counselName"].startswith("ALSTON & BIRD")
    assert record["juniorPartyData"]["patentNumber"] == "10149867"
    assert record["interferenceMetaData"]["declarationDate"] == "2021-01-26"
    assert "documentOCRText" not in record["documentData"]


# ---------------------------------------------------------------------------
# The dead paths must not come back
# ---------------------------------------------------------------------------

#: Paths that no appeal or interference record has ever carried. Each one
#: shipped in field_configs.yaml and returned nothing.
DEAD_PATHS = (
    "applicationNumber",
    "documentData.decisionDate",
    "documentData.decisionOutcome",
    "documentData.decisionType",
    "documentData.decisionTypeCodeDescription",
    "appellantData.appellantName",
    "examinerData.*",
    "partyData.*",
    "partyData.seniorParty",
    "partyData.juniorParty",
)


@pytest.mark.parametrize(
    "field_set",
    ["appeals_minimal", "appeals_balanced",
     "interferences_minimal", "interferences_balanced"],
)
def test_no_field_set_names_a_dead_path(field_manager, field_set):
    configured = field_manager.get_fields(field_set)
    for dead in DEAD_PATHS:
        assert dead not in configured, f"{field_set} still names {dead}"


def test_emergency_fallback_sets_name_real_paths(
    live_appeal_response, live_interference_response
):
    """The built-in fallback config carried the same fictional paths.

    It is what serves every response when field_configs.yaml fails to load,
    so a corrupt YAML used to compound a narrow response with a wrong one.
    """
    fm = FieldManager(Path("/nonexistent/field_configs.yaml"))
    assert fm.is_fallback()

    appeals = fm.filter_response(live_appeal_response, "appeals_minimal")
    assert appeals["context_info"]["fields_absent"] == []
    assert (
        appeals["patentAppealDataBag"][0]["decisionData"]["appealOutcomeCategory"]
        == "Reversed"
    )

    intf = fm.filter_response(live_interference_response, "interferences_minimal")
    assert intf["context_info"]["fields_absent"] == []
    assert (
        intf["patentInterferenceDataBag"][0]["documentData"][
            "interferenceOutcomeCategory"
        ]
        == "Judgment"
    )


# ---------------------------------------------------------------------------
# A configured-but-absent field is reported, never silently dropped
# ---------------------------------------------------------------------------


def test_absent_fields_names_a_path_no_record_carried(field_manager):
    absent = field_manager.absent_fields(
        ["appealNumber", "decisionData.appealOutcomeCategory", "examinerData.name"],
        [{"appealNumber": "2026002664",
          "decisionData": {"appealOutcomeCategory": "Reversed"}}],
    )
    assert absent == ["examinerData.name"]


def test_absent_fields_skips_wildcards(field_manager):
    """An unmatched wildcard expands to nothing and has no path to name."""
    assert field_manager.absent_fields(
        ["appellantData.*", "examinerData.*"],
        [{"appellantData": {"counselName": "X"}}],
    ) == []


def test_absent_fields_is_empty_when_there_are_no_results(field_manager):
    """A zero-result search makes no claim about which fields the data holds."""
    assert field_manager.absent_fields(["appealNumber", "whatever.path"], []) == []


def test_sparse_party_bag_is_reported_not_silently_dropped(field_manager):
    """seniorPartyData is missing on some interference records (2 of 50 probed).

    That absence is real upstream sparsity rather than a path error, and it
    still has to be visible: the answer to "who was the senior party" is
    "this dataset does not say", not an empty column.
    """
    sparse = {
        "count": 1,
        "patentInterferenceDataBag": [{
            "interferenceNumber": "105999",
            "interferenceMetaData": {"interferenceStyleName": "A v. B"},
            "juniorPartyData": {"realPartyInInterestName": "B Corp"},
            "documentData": {
                "documentFilingDate": "2019-04-01",
                "decisionIssueDate": "2019-04-01",
                "decisionTypeCategory": "Decision",
                "interferenceOutcomeCategory": "Judgment",
            },
        }],
    }
    filtered = field_manager.filter_response(sparse, "interferences_minimal")
    assert filtered["context_info"]["fields_absent"] == [
        "seniorPartyData.realPartyInInterestName"
    ]


def test_response_envelope_surfaces_fields_absent(field_manager):
    payload = json.loads(format_proceeding_response(
        "appeals",
        [{"appealNumber": "2026002664"}],
        query_info={},
        field_set="appeals_minimal",
        context_info={"field_set": "appeals_minimal", "fields_absent":
                      ["decisionData.appealOutcomeCategory"]},
        count=1,
    ))
    assert payload["fields_absent"]["fields"] == [
        "decisionData.appealOutcomeCategory"
    ]
    assert "omits a field entirely" in payload["fields_absent"]["note"]


def test_response_envelope_omits_fields_absent_when_nothing_is_missing():
    """A complete response stays byte-identical to what it was before."""
    payload = json.loads(format_proceeding_response(
        "appeals",
        [{"appealNumber": "2026002664"}],
        query_info={},
        field_set="appeals_minimal",
        context_info={"field_set": "appeals_minimal", "fields_absent": []},
        count=1,
    ))
    assert "fields_absent" not in payload


# ---------------------------------------------------------------------------
# The MCP App cards read the same paths
# ---------------------------------------------------------------------------


def test_search_cards_read_real_appeal_and_interference_paths():
    """The card view resolved dotted paths against the same fiction.

    Outcome, Decided, Decision Type and both party columns rendered blank on
    every appeal and interference card regardless of the search.
    """
    from ptab_mcp.ui import SEARCH_RESULTS_HTML

    for real in (
        "decisionData.appealOutcomeCategory",
        "decisionData.decisionIssueDate",
        "decisionData.decisionTypeCategory",
        "appellantData.realPartyInInterestName",
        "appellantData.applicationNumberText",
        "documentData.interferenceOutcomeCategory",
        "seniorPartyData.realPartyInInterestName",
        "juniorPartyData.realPartyInInterestName",
    ):
        assert real in SEARCH_RESULTS_HTML, f"card view lost {real}"

    for dead in (
        "documentData.decisionOutcome",
        "documentData.decisionTypeCodeDescription",
        "appellantData.appellantName",
        "partyData.seniorParty",
        "partyData.juniorParty",
    ):
        assert dead not in SEARCH_RESULTS_HTML, f"card view still reads {dead}"
