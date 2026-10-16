"""PTAB_get_documents never pages past a matched document the size guard dropped.

The tool's own response-size guard runs BEFORE it builds `paging`, so the
returned count was always right; the cursor was not. Two modes apply offset
and limit to the filtered match list rather than to server rows (page_all on
a trial, and the non-paginating appeal / interference GET), and both reported
`has_more: false, next_offset: null` whatever the guard dropped, so a caller
paging by the cursor stopped with those documents unseen. On a server-paged
trial page with a client-side filter the cursor advanced past every scanned
row, which would skip them too (2026-09-11).

Hermetic: a mocked PTABClient, no network.
"""

import json

import pytest

from src.ptab_mcp.main import ptab_get_documents
from src.ptab_mcp.tools.documents import _documents_paging_envelope, _guard_dropped


def _trial_docket(n: int):
    """A trial docket of `n` documents, every third one a Response. Titles are
    long so a full page overflows a small budget and the guard has to drop
    whole documents, not just slim them."""
    bag = []
    for k in range(n):
        title = ("Patent Owner Response " if k % 3 == 0 else "Exhibit ") + "t" * 500
        bag.append({
            "trialNumber": "IPR2024-01353",
            "lastModifiedDateTime": "2024-05-16T10:00:00",
            "patentOwnerData": {"patentNumber": "7883848"},
            "documentData": {
                "documentIdentifier": str(171000000 + k),
                "documentTitleText": title,
                "documentTypeDescriptionText": "Paper",
                "documentCategory": "OTHER",
                "filingPartyCategory": "PATENT OWNER",
                "documentFilingDate": f"2024-{1 + k // 28:02d}-{1 + k % 28:02d}T{k % 24:02d}:00:00",
            },
        })
    return bag


def _serve(bag):
    """search_trial_documents stand-in: server filters, sort, offset/limit."""
    async def _call(trial_number, offset=0, limit=25, sort_order="desc", extra_filters=None):
        rows = list(bag)
        for spec in extra_filters or []:
            field = spec["name"].split(".")[-1]
            wanted = [v.lower() for v in spec["value"]]
            rows = [r for r in rows if (r["documentData"].get(field) or "").lower() in wanted]
        rows.sort(key=lambda r: r["documentData"]["documentFilingDate"],
                  reverse=(sort_order == "desc"))
        return {"count": len(rows), "patentTrialDocumentDataBag": rows[offset:offset + limit]}

    return _call


async def _walk(**call):
    """Page a PTAB_get_documents call by `paging.next_offset` until has_more
    is false. Returns (identifiers seen in order, pages the guard trimmed)."""
    seen, trimmed, offset = [], 0, 0
    for _ in range(200):  # a loop guard, never reached
        page = json.loads(await ptab_get_documents(offset=offset, **call))
        docs = page["documents"]
        assert page["paging"]["returned"] == len(docs) == page["returned_count"]
        if "_bounds" in page:
            trimmed += 1
        seen.extend(d["documentIdentifier"] for d in docs)
        if not page["paging"]["has_more"]:
            assert page["paging"]["next_offset"] is None
            return seen, trimmed
        assert page["paging"]["next_offset"] > offset  # it always moves
        offset = page["paging"]["next_offset"]
    raise AssertionError("the walk did not terminate")


async def test_page_all_walk_visits_every_matched_document_once(mock_api_client, monkeypatch):
    monkeypatch.setenv("USPTO_MAX_RESPONSE_CHARS", "15000")
    bag = _trial_docket(270)
    mock_api_client.search_trial_documents.side_effect = _serve(bag)

    seen, trimmed = await _walk(
        identifier="IPR2024-01353", identifier_type="trial",
        document_title="response", page_all=True, limit=100,
    )

    matched = sorted(
        (r["documentData"] for r in bag if "Response" in r["documentData"]["documentTitleText"]),
        key=lambda d: d["documentFilingDate"], reverse=True,
    )
    assert trimmed > 0  # the guard really did drop documents on the way
    assert seen == [d["documentIdentifier"] for d in matched]


async def test_filtered_appeal_walk_visits_every_matched_document_once(
    mock_api_client, monkeypatch
):
    monkeypatch.setenv("USPTO_MAX_RESPONSE_CHARS", "15000")
    bag = []
    for k in range(120):
        bag.append({
            "appealNumber": "2025000943",
            "appellantData": {"applicationNumberText": "12/950,321"},
            "decisionData": {
                "appealOutcomeCategory": "Affirmed" if k % 4 else "Reversed",
                "decisionIssueDate": "2025-04-01",
            },
            "documentData": {
                "documentIdentifier": str(200000000 + k),
                "documentTitleText": "Decision on Appeal " + "t" * 500,
                "documentTypeDescriptionText": "Decision on Appeal",
                "documentFilingDate": f"2025-{1 + k // 28:02d}-{1 + k % 28:02d}",
            },
        })
    mock_api_client.get_appeal_decisions.return_value = {"count": len(bag), "patentAppealDataBag": bag}

    seen, trimmed = await _walk(
        identifier="2025000943", identifier_type="appeal",
        outcome_category="affirmed", limit=100,
    )

    affirmed = sorted(
        (r["documentData"] for r in bag if r["decisionData"]["appealOutcomeCategory"] == "Affirmed"),
        key=lambda d: d["documentFilingDate"], reverse=True,
    )
    assert trimmed > 0
    assert seen == [d["documentIdentifier"] for d in affirmed]


async def test_page_all_page_the_guard_did_not_trim_is_unchanged(mock_api_client):
    """No trim, no change: a page_all page still has no next page."""
    mock_api_client.search_trial_documents.side_effect = _serve(_trial_docket(9))

    page = json.loads(await ptab_get_documents(
        identifier="IPR2024-01353", identifier_type="trial",
        document_title="response", page_all=True, limit=100,
    ))

    assert "_bounds" not in page
    assert page["paging"]["has_more"] is False
    assert page["paging"]["next_offset"] is None
    assert page["paging"]["note"].endswith("There is no next page.")


class TestServerPagedWithAClientSideFilter:
    """The tool pushes every trial filter server-side unless page_all, so this
    path is exercised on the envelope builder directly, as the existing
    stall test in test_document_tools.py does."""

    def _envelope(self, **kw):
        return _documents_paging_envelope(
            {"documents": [{}] * kw.pop("returned")},
            identifier_type="trial",
            limit_requested=10,
            offset=40,
            total_documents=305,
            total_is_docket_total=True,
            scanned=10,
            client_side_filters={"document_title": "response"},
            **kw,
        )["paging"]

    def test_without_a_trim_the_cursor_passes_every_scanned_row(self):
        paging = self._envelope(returned=4)
        assert paging["next_offset"] == 50

    def test_a_trim_stops_the_cursor_at_the_first_dropped_match(self):
        # 6 matches on the page, the guard kept 4; the earliest dropped match
        # sat on server row 7 of the 10 scanned.
        paging = self._envelope(returned=4, guard_dropped=2, resume_row=7)
        assert paging["has_more"] is True
        assert paging["next_offset"] == 47


def test_guard_dropped_finds_the_earliest_dropped_row():
    rows = [{"id": k} for k in range(10)]
    matched = [rows[1], rows[3], rows[8], rows[5]]  # sorted order differs from row order
    bounded = {"documents": [dict(rows[1]), dict(rows[3])]}  # slimmed copies

    assert _guard_dropped(rows, matched, bounded) == (2, 5)
    assert _guard_dropped(rows, matched, {"documents": [{}] * 4}) == (0, None)


@pytest.mark.parametrize("identifier_type", ["appeal", "interference"])
def test_client_paged_envelope_reports_the_dropped_documents(identifier_type):
    paging = _documents_paging_envelope(
        {"documents": [{}] * 12},
        identifier_type=identifier_type,
        limit_requested=100,
        offset=24,
        total_documents=90,
        total_is_docket_total=False,
        scanned=90,
        client_side_filters={"outcome_category": "affirmed"},
        guard_dropped=30,
    )["paging"]

    assert paging["has_more"] is True
    assert paging["next_offset"] == 36
    assert paging["total"] is None


async def test_server_filtered_trial_page_reports_the_docket_wide_matched_total(mock_api_client):
    """A category filter pushed to USPTO: the rows are one page, the API count is
    every match. matched_total used to count the page (10 against 22 on
    IPR2024-01353 NOTICE, 2026-10-07) while the served note called it
    docket-wide."""
    bag = _trial_docket(30)
    for k, row in enumerate(bag):
        row["documentData"]["documentCategory"] = "NOTICE" if k < 22 else "OTHER"
    mock_api_client.search_trial_documents.side_effect = _serve(bag)

    page = json.loads(await ptab_get_documents(
        identifier="IPR2024-01353", identifier_type="trial",
        document_category="NOTICE", limit=10,
    ))
    assert page["returned_count"] <= 10
    assert page["matched_total"] == 22
    assert page["paging"]["total"] == 22
