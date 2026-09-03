"""Hermetic unit tests for the PTAB_get_documents response-size backstop
(tools/documents.py `_bound_documents_response`).

claude.ai replaces an oversized tool result with a client-side truncation
error the server never sees, so the guard runs on the dict BEFORE json.dumps:
slim the entries (shedding documentOCRText first), truncate the list only if
that is not enough, and teach the caller how to narrow. Under the threshold it
must be a no-op — the same object back, byte-identical. No network, no API key.

The mechanism now delegates to the vendored shared guard
(shared/response_bounds.py); these tests pin BOTH the shared `_bounds`
vocabulary and the legacy aliases (`documents_note`, `returned_count`,
`count`) that consumers were written against.
"""

import json

from src.ptab_mcp.shared.response_bounds import BOUNDS_KEY
from src.ptab_mcp.tools.documents import (
    _DOCUMENTS_MIN_DOCS,
    _DOCUMENTS_SOFT_CHAR_LIMIT,
    _bound_documents_response,
)

# Decision-heavy trials embed an OCR excerpt of roughly this size per entry.
_OCR_EXCERPT = "Final Written Decision. " * 45


def _doc(index: int) -> dict:
    return {
        "documentIdentifier": f"17114{index:04d}",
        "documentTitleText": "Final Written Decision",
        "documentCategory": "DECISION",
        "filingPartyCategory": "BOARD",
        "documentFilingDate": "2024-05-15",
        "documentOCRText": _OCR_EXCERPT,
    }


def _payload(doc_count: int) -> dict:
    return {
        "data_type": "documents",
        "identifier": "IPR2024-01353",
        "identifier_type": "trial",
        "count": doc_count,
        "documents": [_doc(i) for i in range(doc_count)],
        "total_documents": 250,
        "returned_count": doc_count,
        "offset": 0,
        "limit": doc_count,
        "sort_order": "desc",
    }


def _size(payload: dict) -> int:
    return len(json.dumps(payload, default=str))


def test_small_payload_untouched():
    payload = _payload(5)
    before = json.dumps(payload, default=str)

    bounded = _bound_documents_response(payload)

    assert bounded is payload
    assert json.dumps(bounded, default=str) == before
    assert BOUNDS_KEY not in bounded
    assert "documents_note" not in bounded
    assert bounded["documents"][0]["documentOCRText"] == _OCR_EXCERPT


def test_oversized_payload_drops_ocr_text():
    payload = _payload(50)
    assert _size(payload) > _DOCUMENTS_SOFT_CHAR_LIMIT

    bounded = _bound_documents_response(payload)

    assert _size(bounded) <= _DOCUMENTS_SOFT_CHAR_LIMIT
    # Slimming the entries alone was enough — the full page still ships.
    assert len(bounded["documents"]) == 50
    assert bounded["returned_count"] == 50
    assert all("documentOCRText" not in d for d in bounded["documents"])
    assert bounded["documents"][0]["documentIdentifier"] == "171140000"
    assert bounded["total_documents"] == 250

    bounds = bounded[BOUNDS_KEY]
    assert bounds["applied"] is True
    assert bounds["reason"] == "size"
    assert bounds["stages"] == ["slimmed"]  # halving was not needed
    assert "documentOCRText" in bounds["slimmed_fields"]
    assert bounds["items_returned"] == bounds["items_total"] == 50

    # Legacy alias keys survive alongside the shared vocabulary.
    note = bounded["documents_note"]
    assert note == bounds["note"]
    assert "PTAB_get_document_content" in note
    assert "document_title" in note and "offset" in note


def test_still_oversized_payload_truncated_with_truthful_counts():
    payload = _payload(100)
    for doc in payload["documents"]:
        doc["documentName"] = "x" * 400  # bulk that survives the slim whitelist

    bounded = _bound_documents_response(payload)

    assert _size(bounded) <= _DOCUMENTS_SOFT_CHAR_LIMIT
    kept = len(bounded["documents"])
    assert _DOCUMENTS_MIN_DOCS <= kept < 100
    assert bounded["returned_count"] == kept
    assert bounded["count"] == kept
    assert bounded["total_documents"] == 250

    bounds = bounded[BOUNDS_KEY]
    assert bounds["stages"] == ["slimmed", "truncated"]
    assert bounds["items_total"] == 100
    assert bounds["items_returned"] == kept


def test_empty_document_list_is_still_marked_when_oversized():
    """The pre-delegation guard early-returned on an empty/missing `documents`
    list, so oversized bulk anywhere else in the payload sailed past unbounded.
    Now it is at minimum MARKED, even when nothing configured can shed it."""
    payload = {"documents": [], "returned_count": 0, "blob": "y" * 40_000}

    bounded = _bound_documents_response(payload)

    assert bounded[BOUNDS_KEY]["applied"] is True
    assert bounded["documents_note"]


def test_small_payload_with_no_documents_key_is_a_no_op():
    payload = {"identifier": "IPR2024-01353", "documents": []}
    before = json.dumps(payload, default=str)

    bounded = _bound_documents_response(payload)

    assert bounded is payload
    assert json.dumps(bounded, default=str) == before
    assert BOUNDS_KEY not in bounded
    assert "documents_note" not in bounded


# ---------------------------------------------------------------------------
# Open item #4: keep the excerpt for a filtered result set
# ---------------------------------------------------------------------------
# documentOCRText is the first field the guard sheds, which meant the free
# first-page snippet vanished exactly when `limit` was raised to hunt for a
# paper — the caller then had to spend an extraction to find out whether the
# row they matched was the one they wanted. When a title/category filter has
# already narrowed the list to a handful of rows, the excerpt is the point of
# the call and is kept.


def _payload_with_fat_excerpts(doc_count: int) -> dict:
    """Few rows, but each excerpt long enough to breach the budget on its own."""
    payload = _payload(doc_count)
    for doc in payload["documents"]:
        doc["documentOCRText"] = "Final Written Decision. " * 400
    return payload


def test_ocr_text_is_kept_for_a_filtered_result_set():
    payload = _payload_with_fat_excerpts(6)
    payload["filters_applied"] = {"document_title": "Final Written Decision"}

    bounded = _bound_documents_response(payload, keep_ocr_text=True)

    assert BOUNDS_KEY in bounded, "payload must be over the budget for this test"
    assert all("documentOCRText" in doc for doc in bounded["documents"])
    assert "documentOCRText" not in bounded[BOUNDS_KEY]["slimmed_fields"]


def test_ocr_text_is_still_shed_for_an_unfiltered_page():
    bounded = _bound_documents_response(_payload(60))

    assert BOUNDS_KEY in bounded
    assert all("documentOCRText" not in doc for doc in bounded["documents"])
    assert "documentOCRText" in bounded[BOUNDS_KEY]["slimmed_fields"]


def test_keeping_ocr_text_still_truncates_rather_than_blowing_the_budget():
    """Keeping the excerpt is not a licence to exceed the cap."""
    bounded = _bound_documents_response(_payload(400), keep_ocr_text=True)

    assert len(json.dumps(bounded)) <= _DOCUMENTS_SOFT_CHAR_LIMIT
    assert bounded[BOUNDS_KEY]["items_returned"] >= _DOCUMENTS_MIN_DOCS
