"""Hermetic tests for `cite_as`: "citations are links".

Every trial / appeal / interference row and every document row leaves this
server with a markdown link the model can paste into an answer. These pin:

- the two verified URL forms (Google Patents, Patent Center) and nothing else,
- which of them each proceeding type points at,
- that a caller's `fields=` projection cannot cost a row its citation,
- that `cite_as` survives the response-size guard's stage-1 slimming,
- and the hard rule that a download-proxy persistent link is NEVER a citation
  target (a static scan over the source, plus a unit test of the refusal).

No live USPTO calls: every response is a fixture.
"""

import json
import pathlib
import re

import pytest

from src.ptab_mcp.main import (
    ptab_get_documents,
    search_appeals_minimal,
    search_interferences_minimal,
    search_trials_minimal,
)
from src.ptab_mcp.shared import citations as shared_citations
from src.ptab_mcp.util import citations as ptab_citations


# ---------------------------------------------------------------------------
# The shared mechanism
# ---------------------------------------------------------------------------

class TestUrlBuilders:
    def test_google_patents_accepts_the_shapes_uspto_sends(self):
        for value in ("8539047", "8,539,047", "US8539047", "us 8539047"):
            assert (shared_citations.google_patents_url(value)
                    == "https://patents.google.com/patent/US8539047")

    def test_google_patents_reissue_and_publication(self):
        assert (shared_citations.google_patents_url("RE45123")
                == "https://patents.google.com/patent/USRE45123")
        assert (shared_citations.google_patents_url("20010056539")
                == "https://patents.google.com/patent/US20010056539")

    def test_google_patents_refuses_what_it_cannot_resolve(self):
        for value in (None, "", "n/a", "12345", "EP1234567"):
            assert shared_citations.google_patents_url(value) is None

    def test_patent_center_needs_eight_digits(self):
        for value in ("12950321", "12/950,321", "12 950 321"):
            assert (shared_citations.patent_center_url(value)
                    == "https://patentcenter.uspto.gov/applications/12950321")
        for value in (None, "", "950321", "PCT/US2011/001234"):
            assert shared_citations.patent_center_url(value) is None

    def test_display_forms(self):
        assert shared_citations.format_patent_display("8539047") == "US 8,539,047"
        assert shared_citations.format_patent_display("RE45123") == "US RE45123"
        assert shared_citations.format_application_display("12950321") == "12/950,321"
        # Leading zeros after the series code are part of the serial.
        assert shared_citations.format_application_display("19058716") == "19/058,716"
        assert shared_citations.format_application_display("17007001") == "17/007,001"

    def test_cite_as_link_escapes_brackets(self):
        link = shared_citations.cite_as_link("A [bracketed] label", "https://example.test/x")
        assert link == "[A (bracketed) label](https://example.test/x)"

    def test_cite_as_link_refuses_a_delivery_link(self):
        """The persistent-link hash IS the credential (Lesson 43), so it can
        never become a citation, whatever label is handed in."""
        for url in (
            "http://localhost:8083/download/persistent/deadbeef",
            "https://proxy.example.test/document/persistent/deadbeef",
        ):
            assert shared_citations.is_delivery_link(url) is True
            assert shared_citations.cite_as_link("Final Written Decision", url) is None


# ---------------------------------------------------------------------------
# Per-proceeding targets
# ---------------------------------------------------------------------------

class TestProceedingTargets:
    def test_a_trial_cites_the_challenged_patent(self):
        assert ptab_citations.proceeding_cite_as(
            "trials", "IPR2019-00416", "8539047", "12950321"
        ) == ("[IPR2019-00416, US 8,539,047]"
              "(https://patents.google.com/patent/US8539047)")

    def test_a_trial_without_a_patent_falls_back_to_patent_center(self):
        assert ptab_citations.proceeding_cite_as(
            "trials", "IPR2019-00416", None, "12950321"
        ) == ("[IPR2019-00416, application 12/950,321]"
              "(https://patentcenter.uspto.gov/applications/12950321)")

    def test_an_appeal_cites_the_application(self):
        """An ex parte appeal is about an application, so Patent Center wins
        even when the record also carries a patent number."""
        assert ptab_citations.proceeding_cite_as(
            "appeals", "2025000943", "8539047", "12950321"
        ) == ("[2025000943, application 12/950,321]"
              "(https://patentcenter.uspto.gov/applications/12950321)")

    def test_nothing_citable_means_no_link(self):
        assert ptab_citations.proceeding_cite_as("trials", "IPR2019-00416") is None
        assert ptab_citations.proceeding_cite_as("appeals", "2025000943", None, None) is None


# ---------------------------------------------------------------------------
# The search tools
# ---------------------------------------------------------------------------

class TestSearchCitations:
    async def test_trials_row_and_envelope(self, mock_api_client, mock_trial_search_response):
        mock_api_client.search_trials.return_value = mock_trial_search_response

        result = json.loads(await search_trials_minimal(trial_type="IPR", limit=5))

        assert result["results"][0]["cite_as"] == (
            "[IPR2024-01353, US 7,883,848]"
            "(https://patents.google.com/patent/US7883848)"
        )
        assert result["citation_note"] == shared_citations.CITATION_NOTE

    async def test_projection_cannot_cost_a_row_its_citation(
        self, mock_api_client, mock_trial_search_response
    ):
        """`fields=['trialNumber']` drops patentOwnerData from the row, so the
        link has to be built from the record BEFORE filtering."""
        mock_api_client.search_trials.return_value = mock_trial_search_response

        result = json.loads(await search_trials_minimal(
            trial_type="IPR", fields=["trialNumber"], limit=5))

        row = result["results"][0]
        assert "patentOwnerData" not in row
        assert row["cite_as"].endswith("(https://patents.google.com/patent/US7883848)")

    async def test_appeals_row_targets_patent_center(self, mock_api_client):
        mock_api_client.search_appeals.return_value = {
            "count": 1,
            "patentAppealDataBag": [{
                "appealNumber": "2025000943",
                "appellantData": {
                    "applicationNumberText": "12/950,321",
                    "realPartyInInterestName": "Acme Corp",
                },
                "decisionData": {"appealOutcomeCategory": "Affirmed"},
            }],
        }

        result = json.loads(await search_appeals_minimal(limit=5))

        assert result["results"][0]["cite_as"] == (
            "[2025000943, application 12/950,321]"
            "(https://patentcenter.uspto.gov/applications/12950321)"
        )

    async def test_interference_row_uses_the_senior_party_patent(self, mock_api_client):
        mock_api_client.search_interferences.return_value = {
            "count": 1,
            "patentInterferenceDataBag": [{
                "interferenceNumber": "106,123",
                "interferenceMetaData": {"interferenceStyleName": "SENIOR v. JUNIOR"},
                "seniorPartyData": {"patentNumber": "8539047"},
                "juniorPartyData": {"applicationNumberText": "12/950,321"},
            }],
        }

        result = json.loads(await search_interferences_minimal(limit=5))

        assert result["results"][0]["cite_as"] == (
            "[106,123, US 8,539,047]"
            "(https://patents.google.com/patent/US8539047)"
        )

    async def test_a_row_with_no_numbers_gets_no_cite_as(self, mock_api_client):
        """An absent citation is honest; an invented link is not."""
        mock_api_client.search_trials.return_value = {
            "count": 1,
            "patentTrialProceedingDataBag": [{
                "trialNumber": "IPR2024-00001",
                "trialMetaData": {"trialTypeCode": "IPR"},
            }],
        }

        result = json.loads(await search_trials_minimal(trial_type="IPR", limit=5))

        assert "cite_as" not in result["results"][0]

    async def test_empty_result_still_carries_the_note(self, mock_api_client):
        mock_api_client.search_trials.return_value = {
            "count": 0, "patentTrialProceedingDataBag": [],
        }

        result = json.loads(await search_trials_minimal(trial_type="IPR", limit=5))

        assert result["results"] == []
        assert result["citation_note"] == shared_citations.CITATION_NOTE


# ---------------------------------------------------------------------------
# PTAB_get_documents
# ---------------------------------------------------------------------------

class TestDocumentCitations:
    async def test_every_row_cites_the_proceeding(
        self, mock_api_client, mock_trial_documents_response
    ):
        mock_api_client.search_trial_documents.return_value = mock_trial_documents_response

        result = json.loads(await ptab_get_documents(identifier="IPR2024-01353"))

        expected = ("[IPR2024-01353, US 7,883,848]"
                    "(https://patents.google.com/patent/US7883848)")
        assert result["cite_as"] == expected
        assert result["documents"]
        assert all(doc["cite_as"] == expected for doc in result["documents"])
        assert result["citation_note"] == shared_citations.CITATION_NOTE

    async def test_appeal_documents_cite_patent_center(
        self, mock_api_client, mock_appeal_decisions_response
    ):
        mock_api_client.get_appeal_decisions.return_value = mock_appeal_decisions_response

        result = json.loads(await ptab_get_documents(
            identifier="2025000943", identifier_type="appeal"))

        expected = ("[2025000943, application 12/950,321]"
                    "(https://patentcenter.uspto.gov/applications/12950321)")
        assert all(doc["cite_as"] == expected for doc in result["documents"])

    async def test_no_document_row_cites_a_delivery_link(
        self, mock_api_client, mock_trial_documents_response
    ):
        """fileDownloadURI and the proxy's persistent links are delivery, not
        citation. Nothing that looks like one may appear inside a cite_as."""
        mock_api_client.search_trial_documents.return_value = mock_trial_documents_response

        raw = await ptab_get_documents(identifier="IPR2024-01353")
        result = json.loads(raw)

        for doc in result["documents"]:
            assert "/persistent/" not in doc["cite_as"]
            assert "api.uspto.gov" not in doc["cite_as"]

    async def test_cite_as_survives_stage_one_slimming(
        self, mock_api_client, mock_trial_documents_response
    ):
        """The response guard slims a document row to a whitelist; a slimmed
        page still has to be citable, so `cite_as` is on that whitelist."""
        from src.ptab_mcp.tools import documents as doc_tools

        assert ptab_citations.CITE_AS_KEY in doc_tools._DOC_SLIM_FIELDS

        mock_api_client.search_trial_documents.return_value = mock_trial_documents_response
        result = json.loads(await ptab_get_documents(identifier="IPR2024-01353"))
        row = dict(result["documents"][0])
        slimmed = {k: row[k] for k in doc_tools._DOC_SLIM_FIELDS if k in row}
        assert slimmed["cite_as"] == result["cite_as"]


# ---------------------------------------------------------------------------
# Static guarantee
# ---------------------------------------------------------------------------

#: Every source file that can build a citation target.
_CITATION_SOURCES = (
    "src/ptab_mcp/shared/citations.py",
    "src/ptab_mcp/util/citations.py",
)

#: The only two URL forms this server may ever emit as a citation target,
#: both probed live on 2026-09-05 (see shared/citations.py). A third form
#: needs its own probe before it is added here.
_ALLOWED_TARGET_PREFIXES = (
    "https://patents.google.com/patent/",
    "https://patentcenter.uspto.gov/applications/",
)

_URL_LITERAL_RE = re.compile(r"https?://[^\s\"'`)]+")


def test_no_citation_target_is_a_proxy_delivery_link():
    """A static scan, not only a behavioural one: no URL written into the
    citation modules may be a download-proxy path. The hash in those URLs is
    the credential (Lesson 43), so a citation built on one publishes it."""
    root = pathlib.Path(__file__).resolve().parents[1]
    for relative in _CITATION_SOURCES:
        text = (root / relative).read_text(encoding="utf-8")
        for url in _URL_LITERAL_RE.findall(text):
            assert "/document/persistent/" not in url, f"{relative}: {url}"
            assert "/download/persistent/" not in url, f"{relative}: {url}"


def test_only_the_two_verified_url_forms_are_ever_emitted():
    """No third URL form. Anything else needs a live probe first (see the
    shared module's docstring)."""
    assert shared_citations.GOOGLE_PATENTS_BASE == "https://patents.google.com/patent/US"
    assert shared_citations.PATENT_CENTER_BASE == "https://patentcenter.uspto.gov/applications/"

    root = pathlib.Path(__file__).resolve().parents[1]
    for relative in _CITATION_SOURCES:
        text = (root / relative).read_text(encoding="utf-8")
        # Docstrings quote the two forms as examples; both are allowed
        # prefixes, so one rule covers code and prose alike.
        for url in _URL_LITERAL_RE.findall(text):
            assert url.startswith(_ALLOWED_TARGET_PREFIXES), f"{relative}: {url}"


# --- the lettered series (added 2026-09-20) ----------------------------------
# A design or plant number used to match nothing and produce NO cite_as at all:
# the safe failure, but a hole in a promise that says every row carries a link,
# and design patents are cited as prior art constantly in design prosecution.
# Every arm below was probed against Google Patents on 2026-09-20 and answered
# 200. AI is excluded on the same evidence: USAI00001 answers 404.

@pytest.mark.parametrize("value,expected", [
    ("D618677", "https://patents.google.com/patent/USD618677"),
    ("D618,677", "https://patents.google.com/patent/USD618677"),
    ("USD618677", "https://patents.google.com/patent/USD618677"),
    ("D618677S1", "https://patents.google.com/patent/USD618677"),
    ("PP12345", "https://patents.google.com/patent/USPP12345"),
    ("PP12345P2", "https://patents.google.com/patent/USPP12345"),
    ("H1234", "https://patents.google.com/patent/USH1234"),
    ("T100001", "https://patents.google.com/patent/UST100001"),
    ("RE45123", "https://patents.google.com/patent/USRE45123"),
    ("8539047", "https://patents.google.com/patent/US8539047"),
])
def test_lettered_series_get_a_google_patents_link(value, expected):
    assert shared_citations.google_patents_url(value) == expected


def test_additional_improvement_series_is_not_linked():
    """USAI00001 answers 404, so a link for it would be the dead citation this
    module exists to avoid. None is the correct answer, not a guess."""
    assert shared_citations.google_patents_url("AI00001") is None
