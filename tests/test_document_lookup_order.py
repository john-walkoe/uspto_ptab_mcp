"""The download tool must exhaust the document INDEX before the URI fallback.

Live defect, prod 2026-09-03: PTAB_get_document_download(IPR2024-01353,
171303338) returned `document_description: "Document"`, `page_count:
"Unknown"` and the PROCEEDING's accorded filing date 2024-08-23, so the file
was named PTAB-2024-08-23_IPR2024-01353_PAT-7883848_DOCUMENT.pdf — while
PTAB_get_documents returned the same paper as "IPR2024-01353 Final Written
Decision.pdf", Paper 40, filed 2026-03-04. The bytes were right; the metadata
had fallen through to the fileDownloadURI-pattern fallback that TEST_SUITE.md
T9 documents for papers the index does NOT carry.

The lookup had exactly one chance at the metadata — a whole-docket walk — so
ANY miss on it (an upstream failure of a page, an open circuit, a docket
truncated at the 500-document safety cap, a paper past the walk's reach) was
indistinguishable from "not indexed" and silently produced a generic name.
These tests pin the ordering that fixes it: targeted documentIdentifier lookup,
then the full walk (every page), and only then the URI pattern.
"""

import json

import pytest

from src.ptab_mcp.api.ptab_client import PTABClient
from src.ptab_mcp.main import ptab_get_document_download

TRIAL = "IPR2024-01353"
DOC_ID = "171303338"

#: The paper as the live index carries it (probed 2026-09-03).
FWD_ROW = {
    "trialNumber": TRIAL,
    "lastModifiedDateTime": "2026-03-04T18:56:35",
    "trialDocumentCategory": "Decision",
    "patentOwnerData": {"patentNumber": "7883848"},
    "documentData": {
        "documentIdentifier": DOC_ID,
        "documentTitleText": "Final Written Decision",
        "documentTypeDescriptionText": "Final Written Decision:  original",
        "documentCategory": "FINAL",
        "documentNumber": 40,
        "filingPartyCategory": "BOARD",
        "documentFilingDate": "2026-03-04",
        "documentSizeQuantity": 700143,
        "fileDownloadURI": (
            "https://api.uspto.gov/api/v1/patent/ptab-files/IPR/2024/01353/"
            f"{DOC_ID}.pdf"
        ),
    },
}

#: The API's own envelope for "no rows" — a 404, not an empty bag.
NO_MATCHING_RECORDS = {
    "error": 'API error: {"code":"404","message":"Not Found"}',
    "status_code": 404,
}


def _filler(n, start=171100000):
    """n unrelated docket rows, none of them the paper under test."""
    return [
        {
            "trialNumber": TRIAL,
            "lastModifiedDateTime": "2025-01-01T00:00:00",
            "trialDocumentCategory": "Document",
            "patentOwnerData": {"patentNumber": "7883848"},
            "documentData": {
                "documentIdentifier": str(start + i),
                "documentTitleText": f"Exhibit {i}",
                "documentCategory": "Exhibit",
                "documentFilingDate": "2025-01-01",
                "fileDownloadURI": f"https://api.uspto.gov/x/{start + i}.pdf",
            },
        }
        for i in range(n)
    ]


class FakeIndex:
    """A trials/documents/search stand-in with a controllable index.

    `pages` are served by offset exactly as the live endpoint does, and
    `targeted` decides whether the documentData.documentIdentifier filter is
    answered or comes back as the 404 no-matching-records envelope.
    """

    def __init__(self, rows, targeted=True, page_size=100, walk_error=None):
        self.rows = rows
        self.targeted = targeted
        self.page_size = page_size
        self.walk_error = walk_error
        self.calls = []

    async def search_trial_documents(self, trial_number, offset=0, limit=25,
                                     sort_order="desc", extra_filters=None):
        self.calls.append({"offset": offset, "limit": limit,
                           "extra_filters": extra_filters})
        wanted_id = None
        for spec in extra_filters or []:
            if spec["name"] == "documentData.documentIdentifier":
                wanted_id = spec["value"][0]
        if wanted_id is not None:
            if not self.targeted:
                return dict(NO_MATCHING_RECORDS)
            hit = [r for r in self.rows
                   if r["documentData"]["documentIdentifier"] == wanted_id]
            if not hit:
                return dict(NO_MATCHING_RECORDS)
            return {"count": len(hit), "patentTrialDocumentDataBag": hit}
        if self.walk_error and offset > 0:
            return dict(self.walk_error)
        page = self.rows[offset:offset + min(limit, self.page_size)]
        if not page and offset:
            return dict(NO_MATCHING_RECORDS)
        return {"count": len(self.rows), "patentTrialDocumentDataBag": page}

    async def search_all_trial_documents(self, trial_number, max_docs=500):
        # The REAL walk, so the paging fix is exercised rather than mocked.
        return await PTABClient.search_all_trial_documents(
            self, trial_number, max_docs=max_docs
        )


@pytest.fixture
def download_client(mock_api_client, monkeypatch):
    """mock_api_client with the proxy/registry side effects stubbed out.

    Delivery (centralized proxy, local proxy startup, persistent-link cache)
    is not under test here; the filename is.
    """
    from src.ptab_mcp.tools import documents as doc_tools

    async def _delivery(**kwargs):
        return ("http://localhost:8083/download/persistent/deadbeef",
                "local", "test", False)

    async def _register(payload):
        return None

    monkeypatch.setattr(doc_tools, "_resolve_download_delivery", _delivery)
    monkeypatch.setattr(doc_tools, "_register_download_via_proxy", _register)
    mock_api_client.search_trials.return_value = {
        "patentTrialProceedingDataBag": [{
            "trialNumber": TRIAL,
            "patentOwnerData": {"patentNumber": "7883848",
                                "applicationNumberText": "12345678"},
            # The PROCEEDING's date — the value the defect leaked into the name.
            "trialMetaData": {"accordedFilingDate": "2024-08-23"},
        }]
    }
    return mock_api_client


def _wire(mock_client, index):
    mock_client.search_trial_documents = index.search_trial_documents
    mock_client.search_all_trial_documents = index.search_all_trial_documents


async def _download(document_id=DOC_ID):
    return json.loads(await ptab_get_document_download(
        document_id=document_id, identifier=TRIAL, identifier_type="trial"))


class TestIndexBeforeUriFallback:
    async def test_document_on_page_two_is_named_from_its_own_metadata(
        self, download_client
    ):
        """The paper sits past the first 100-row page of a 108-document docket.

        It must still be named from ITS date and ITS type, not from the trial's
        accorded filing date and the word DOCUMENT.
        """
        index = FakeIndex(_filler(107) + [FWD_ROW], targeted=False)
        _wire(download_client, index)

        result = await _download()

        assert result["filing_date"] == "2026-03-04"
        assert result["document_description"] == "Final Written Decision"
        assert result["enhanced_filename"] == (
            "PTAB-2026-03-04_IPR2024-01353_PAT-7883848_FINAL_WRITTEN_DECISION.pdf"
        )
        # The walk really paged: page 1 (offset 0) then page 2 (offset 100).
        walk_offsets = [c["offset"] for c in index.calls if not c["extra_filters"]]
        assert walk_offsets == [0, 100]

    async def test_targeted_lookup_resolves_without_walking_the_docket(
        self, download_client
    ):
        """One request by documentIdentifier, no whole-docket walk."""
        index = FakeIndex(_filler(107) + [FWD_ROW], targeted=True)
        _wire(download_client, index)

        result = await _download()

        assert result["enhanced_filename"] == (
            "PTAB-2026-03-04_IPR2024-01353_PAT-7883848_FINAL_WRITTEN_DECISION.pdf"
        )
        assert len(index.calls) == 1
        assert index.calls[0]["extra_filters"] == [
            {"name": "documentData.documentIdentifier", "value": [DOC_ID]}
        ]

    async def test_walk_failure_no_longer_degrades_an_indexed_document(
        self, download_client
    ):
        """The prod symptom: the docket walk fails, the paper IS indexed.

        The targeted lookup answers, so the filename keeps the document's own
        date and type instead of collapsing to the proceeding's date and
        DOCUMENT.
        """
        index = FakeIndex(
            _filler(107) + [FWD_ROW], targeted=True,
            walk_error={"error": "Request timeout after 3 attempts",
                        "status_code": 408},
        )
        _wire(download_client, index)

        result = await _download()

        assert result["enhanced_filename"] != (
            "PTAB-2024-08-23_IPR2024-01353_PAT-7883848_DOCUMENT.pdf"
        )
        assert result["enhanced_filename"] == (
            "PTAB-2026-03-04_IPR2024-01353_PAT-7883848_FINAL_WRITTEN_DECISION.pdf"
        )

    async def test_uri_pattern_fallback_survives_for_unindexed_documents(
        self, download_client
    ):
        """T9: a paper the index does not carry still gets a link.

        Neither the targeted lookup nor the walk can find it, so the
        constructed ptab-files URI — and the generic metadata that comes with
        it — is still the right answer.
        """
        index = FakeIndex(_filler(10), targeted=True)
        _wire(download_client, index)

        result = await _download(document_id="171303339")

        assert result["document_description"] == "Document"
        assert result["page_count"] == "Unknown"
        assert result["filing_date"] == "2024-08-23"
        assert result["enhanced_filename"] == (
            "PTAB-2024-08-23_IPR2024-01353_PAT-7883848_DOCUMENT.pdf"
        )
        assert result["download_url"].startswith("http")
        # Tried the index both ways first: targeted, then the walk.
        assert any(c["extra_filters"] for c in index.calls)
        assert any(not c["extra_filters"] for c in index.calls)
