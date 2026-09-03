"""Shared document tools: list, download link, content extraction.

Includes the extraction tier helpers (pypdf -> Mistral -> Docling), the
download delivery resolution (centralized PFW proxy vs local persistent
link), and the recent-downloads registration path.
"""

import json
import os
from typing import Any, Dict, List, Optional, Sequence

from fastmcp import Context
from fastmcp.apps import AppConfig

from ..api.proceedings import (
    find_document,
    find_document_or_fallback_uri,
    get_adapter,
)
from ..app_uris import DOWNLOADS_URI
from ..config.filter_field_mapping import (
    TRIAL_DOCUMENT_CATEGORIES,
    TrialDocumentFilterFields,
)
from ..proxy.centralized_integration import register_with_centralized_proxy
from ..util.document_naming import (
    derive_document_description,
    generate_enhanced_filename,
)
from ..runtime import _client, docling_client, ocr_service, settings
from ..server_bootstrap import _ensure_local_proxy_running, get_local_proxy_port
from ..shared import response_bounds
from ..shared.circuit_breaker import CircuitBreakerOpenError
from ..shared.injection_scan import RETRIEVED_TEXT_NOTE, scan_hits
from ..shared.response_bounds import (
    apply_text_window,
    bound_structured_response,
)
from ..shared.safe_logger import get_safe_logger
from ..util.identity import get_authenticated_identity, get_viewer_key
from ..util.response_formatter import build_document_list, format_error_response
from ..util.search_runner import async_lifecycle_envelope, is_no_matches_error
from ..validation.validators import (
    validate_document_id,
    validate_identifier_type,
)

logger = get_safe_logger(__name__)

# Data-bearing tool responses serialize COMPACTLY (indent=None, default
# separators) because that is exactly what the response guard measures:
# shared/response_bounds.measure_chars() is len(json.dumps(payload)) with no
# indent. Dumping the guarded dict with indent=2 afterwards re-inflated it by
# roughly 25-40% of pure whitespace, so a payload the guard had certified as
# fitting could still exceed the client's cap on the wire — and the whitespace
# bought nothing: every consumer json.loads() the string. Errors and small
# envelopes use the same setting for consistency.
_JSON_INDENT = None

# ==========================================
# SHARED DOCUMENT TOOLS (3 tools - work for all identifier types)
# ==========================================




def _make_progress_cb(ctx):
    """Best-effort MCP progress forwarder; never fails the extraction."""
    async def _progress(progress: float, total: float, message: str) -> None:
        if ctx is not None:
            try:
                await ctx.report_progress(progress=progress, total=total, message=message)
            except Exception:
                pass  # progress is cosmetic; deliberate narrow swallow (EH-10)
    return _progress


def _validate_document_query(limit: int, offset: int, sort_order: str) -> str:
    """Bounds-check the list-query params; returns the normalized sort_order."""
    if limit < 1 or limit > 200:
        raise ValueError("Limit must be between 1 and 200")
    if offset < 0:
        raise ValueError("Offset must be >= 0")
    sort_order = sort_order.lower()
    if sort_order not in ("asc", "desc"):
        raise ValueError("sort_order must be 'asc' or 'desc'")
    return sort_order


def _validate_document_request(identifier: str, identifier_type: str,
                               document_id: str) -> tuple:
    """Shared validation for the download/content tools.

    Returns (identifier_type, adapter, identifier, document_id).
    """
    identifier_type = validate_identifier_type(identifier_type)
    adapter = get_adapter(identifier_type)
    identifier = adapter.validate_identifier(identifier)
    document_id = validate_document_id(document_id)
    return identifier_type, adapter, identifier, document_id


def _not_found_message(
    document_id: str, identifier: str, docs_response: Optional[Dict[str, Any]] = None
) -> str:
    """"Document not found" — but say so honestly when the docket walk was cut
    short, either by api/ptab_client.py's max_docs safety cap or by an upstream
    page failure. A document past the point the walk reached is missing from
    the set we searched, not missing from the docket, and the two used to be
    indistinguishable to the caller."""
    message = f"Document ID '{document_id}' not found in {identifier}"
    if not isinstance(docs_response, dict):
        return message
    if docs_response.get("docket_partial"):
        message += (
            f". NOTE: {docs_response.get('docket_partial_note')} This lookup "
            "searched only the documents fetched before that failure, so the ID "
            "may still be valid."
        )
    elif docs_response.get("docket_truncated"):
        message += (
            f". NOTE: {docs_response.get('docket_truncation_note')} This lookup "
            "searched only the documents fetched before that cap, so the ID may "
            "still be valid."
        )
    return message


#: Filters PTAB_get_documents can push into the trials/documents/search
#: index instead of applying them itself. Server-side means DOCKET-wide:
#: the endpoint's own `count` becomes the number of matching papers on the
#: whole docket, not the number of matches inside one fetched page. The two
#: entries here were verified equivalent to this tool's client-side test on
#: 2026-08-30 (exact match, case-insensitive, on the same field).
_SERVER_SIDE_EXACT_FILTERS = {
    "document_category": TrialDocumentFilterFields.DOCUMENT_CATEGORY,
    "filing_party": TrialDocumentFilterFields.FILING_PARTY,
}


def _server_side_document_filters(
    identifier_type: str,
    document_title: Optional[str],
    document_category: Optional[str],
    filing_party: Optional[str],
    push_title: bool,
) -> tuple:
    """Build the server-side filter list. Returns (filters, pushed_names).

    Trials only — the appeals and interferences document endpoints are
    non-paginating GETs that take no filters at all.

    `document_title` is pushed only when `push_title` is set, because the
    server's title match is NOT this tool's client-side match: the API does a
    case-insensitive PHRASE match (whole words, in order) over
    documentTitleText alone, while the client-side filter is a plain
    substring over documentTitleText OR documentTypeDescriptionText. Pushing
    it is far more accurate for the common case (on IPR2024-00990
    'Petition' returns the petition, where the substring test also matches
    "Petitioner's Reply"), but it can miss a partial-word needle. page_all
    keeps the substring semantics and scans every page instead.
    """
    if identifier_type != "trial":
        return [], []
    filters: List[Dict[str, Any]] = []
    pushed: List[str] = []
    for name, value in (("document_category", document_category),
                        ("filing_party", filing_party)):
        if value:
            filters.append({"name": _SERVER_SIDE_EXACT_FILTERS[name],
                            "value": [value]})
            pushed.append(name)
    if document_title and push_title:
        filters.append({"name": TrialDocumentFilterFields.DOCUMENT_TITLE,
                        "value": [document_title]})
        pushed.append("document_title")
    return filters, pushed


_FWD_PHRASE = "final written decision"


def _fwd_coverage_note(documents: List[Dict[str, Any]]) -> Optional[str]:
    """Say so when the Board's own final written decision is not a docket row.

    On a sealed trial the Board's FWD paper can be absent from the document
    index entirely, and the only Final Written Decision text on the docket is
    a PARTY-filed public/redacted copy sitting in category OTHER. Observed
    live on IPR2024-00864 (2026-08-30): documentCategory='FINAL' returns
    nothing, filing_party='BOARD' never returns an FWD, and the FWD appears
    only as Paper 86 'Final Written Decision (Public)', category OTHER, filed
    by PETITIONER. The Board's Paper 85 is not a row at all. Reported as
    `coverage_note` so a missing FINAL row is never read as "no decision".

    Returns None when a category-FINAL row is present (the normal case) or
    when nothing on the docket mentions a final written decision.
    """
    fwd_rows = [
        doc for doc in documents
        if _FWD_PHRASE in (
            f"{doc.get('documentTitleText') or ''} "
            f"{doc.get('documentTypeDescriptionText') or ''}"
        ).lower()
    ]
    if not fwd_rows:
        return None
    if any((doc.get("documentCategory") or "").upper() == "FINAL"
           for doc in fwd_rows):
        return None
    party_copies = [doc for doc in fwd_rows
                    if (doc.get("documentCategory") or "").upper() == "OTHER"]
    if not party_copies:
        return None
    described = "; ".join(
        f"paper {doc.get('documentNumber')} "
        f"'{doc.get('documentTitleText')}' "
        f"(documentIdentifier {doc.get('documentIdentifier')}, "
        f"category {doc.get('documentCategory')}, filed by "
        f"{doc.get('filingPartyCategory')} on {doc.get('documentFilingDate')})"
        for doc in party_copies[:5]
    )
    return (
        "COVERAGE: this docket carries NO document with documentCategory "
        "'FINAL', so the Board's own final written decision paper is not "
        "exposed as a docket row — which is what a sealed trial looks like "
        "here. The only final-written-decision text on the docket is a "
        f"party-filed copy: {described}. Read that copy for the outcome, and "
        "do not read the absence of a FINAL row as the absence of a "
        "decision. Neither document_category='FINAL' nor filing_party='BOARD' "
        "will find it."
    )


async def _probe_fwd_coverage(api_client, adapter, identifier: str) -> Optional[str]:
    """One extra server-side call, only when a FINAL request came back empty.

    A `document_category='FINAL'` request that returns nothing is exactly the
    case that needs explaining, and there are no rows left to explain it
    with — so ask the index for the docket's final-written-decision papers by
    title and describe what it holds instead.
    """
    try:
        probe = await adapter.fetch_documents_page(
            api_client, identifier, offset=0, limit=10, sort_order="desc",
            extra_filters=[{
                "name": TrialDocumentFilterFields.DOCUMENT_TITLE,
                "value": ["Final Written Decision"],
            }],
        )
    except Exception:  # a coverage note is a courtesy, never a failure path
        return None
    if not isinstance(probe, dict) or probe.get("error"):
        return None
    return _fwd_coverage_note(adapter.flatten_documents(probe))


def _filter_documents(
    documents: List[Dict[str, Any]],
    identifier_type: str,
    document_title: Optional[str],
    document_category: Optional[str],
    filing_party: Optional[str],
    outcome_category: Optional[str],
    already_server_side: Sequence[str] = (),
) -> tuple:
    """Apply the tool's optional document filters. Returns (docs, applied).

    `applied` records every filter the CALLER asked for, whether it ran here
    or server-side; `already_server_side` names the ones the API index
    already applied, which are not re-tested here (the server's title match
    is a phrase match and re-running the substring test could drop rows the
    server legitimately matched).
    """
    requested = {
        "document_title": document_title,
        "document_category": document_category,
        "filing_party": filing_party,
    }
    # Anything the API index already matched is recorded as applied but is
    # NOT re-tested here.
    applied: Dict[str, str] = {
        name: value for name, value in requested.items()
        if value and name in already_server_side
    }
    local = {name: value for name, value in requested.items()
             if value and name not in already_server_side}
    return _apply_local_filters(
        documents, identifier_type, local, outcome_category, applied
    )


def _apply_local_filters(
    documents: List[Dict[str, Any]],
    identifier_type: str,
    local: Dict[str, str],
    outcome_category: Optional[str],
    applied: Dict[str, str],
) -> tuple:
    """The client-side half of _filter_documents. Returns (docs, applied)."""
    filtered = documents
    document_title = local.get("document_title")
    document_category = local.get("document_category")
    filing_party = local.get("filing_party")

    # document_title substring (case-insensitive) — all identifier types
    if document_title:
        needle = document_title.lower()
        filtered = [
            doc for doc in filtered
            if needle in doc.get("documentTypeDescriptionText", "").lower()
            or needle in doc.get("documentTitleText", "").lower()
        ]
        applied["document_title"] = document_title

    if identifier_type == "trial":
        if document_category:
            wanted = document_category.upper()
            filtered = [doc for doc in filtered
                        if doc.get("documentCategory", "").upper() == wanted]
            applied["document_category"] = document_category
        if filing_party:
            wanted = filing_party.upper()
            filtered = [doc for doc in filtered
                        if doc.get("filingPartyCategory", "").upper() == wanted]
            applied["filing_party"] = filing_party
    elif outcome_category:
        wanted = outcome_category.upper()
        outcome_field = ("appealOutcomeCategory" if identifier_type == "appeal"
                         else "interferenceOutcomeCategory")
        filtered = [doc for doc in filtered
                    if doc.get(outcome_field, "").upper() == wanted]
        applied["outcome_category"] = outcome_category

    return filtered, applied


def _sort_and_paginate(
    documents: List[Dict[str, Any]], identifier_type: str,
    sort_order: str, offset: int, limit: int,
    paginate: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Sort (tiebreaker for trials, primary for others) and client-side
    paginate when the fetch itself did not.

    `paginate` defaults to "everything except a trial", because a trial page
    is cut server-side. A page_all walk is the exception: it holds the whole
    docket, so offset/limit have to be applied here or the caller gets
    hundreds of rows regardless of what they asked for.
    """
    def _sort_key(doc):
        return doc.get("documentFilingDate") or doc.get("lastModifiedDateTime") or ""

    documents = sorted(documents, key=_sort_key, reverse=(sort_order == "desc"))
    if paginate is None:
        paginate = identifier_type != "trial"
    if paginate:
        if offset:
            documents = documents[offset:]
        if limit and limit < len(documents):
            documents = documents[:limit]
    return documents


#: Hard cap on a page_all walk. 1000 documents is past the largest PTAB
#: dockets seen in practice (IPR2024-00864 is 305) and is ten 100-row calls
#: at worst; the walk marks `docket_truncated` when it stops here so a
#: partial scan is never mistaken for a complete one.
_PAGE_ALL_MAX_DOCS = 1000


def _filter_semantics_note(
    pushed: Sequence[str], client_side: Sequence[str], page_all: bool
) -> str:
    """Say exactly where each filter ran, because it changes what a count means."""
    parts: List[str] = []
    if pushed:
        parts.append(
            f"{', '.join(sorted(pushed))} ran SERVER-side, across the whole "
            "docket, so `matched_total` and `total_documents` are docket-wide "
            "match counts, not per-page ones. document_category and "
            "filing_party are exact case-insensitive matches; document_title "
            "is a case-insensitive PHRASE match over documentTitleText (whole "
            "words in order, e.g. 'Final Written Decision'), not a substring "
            "and not a search of documentTypeDescriptionText."
        )
    if client_side:
        where = ("every page of the docket (page_all=True)" if page_all
                 else "THIS PAGE ONLY")
        parts.append(
            f"{', '.join(client_side)} ran client-side, over {where}"
            + ("." if page_all else
               " — a match filed later in the docket is not counted here. "
               "Re-call with page_all=True to scan the whole docket.")
        )
    if not page_all and not pushed and not client_side:
        parts.append("No filters applied.")
    return " ".join(parts)


# Soft ceiling for the PTAB_get_documents response. claude.ai replaces any tool
# result much past ~50K chars with a client-side truncation error the server
# never sees, so an oversized response reaches the model as nothing at all. A
# default limit=50 docket lands near 12K, but limit=100 on a decision-heavy
# trial breaches it: entries there carry a documentOCRText excerpt of ~1K each
# (measured 2026-08-16). Drop the excerpts first, truncate second, and always
# say what happened so the model can narrow instead of retrying blind.
#
# The mechanism now lives in shared/response_bounds.py (vendored byte-identical
# across the USPTO MCPs); this constant is the documented default and the live
# ceiling is read from USPTO_MAX_RESPONSE_CHARS on every call.
_DOCUMENTS_SOFT_CHAR_LIMIT = response_bounds.DEFAULT_MAX_RESPONSE_CHARS
_DOCUMENTS_MIN_DOCS = 10

#: USPTO POST document-search hard page cap (api/ptab_client.py clamps to it).
_API_DOCUMENT_PAGE_CAP = 100

#: Stage-1 whitelist for an oversized document list. Everything a follow-up
#: call actually needs survives; documentOCRText (a ~1K bonus excerpt per
#: entry — PTAB_get_document_content returns the FULL text of one document) and
#: any other unlisted blob is what gets shed. `_bounds.slimmed_fields` names
#: every field this drops, so nothing disappears silently.
_DOC_SLIM_FIELDS = (
    "documentIdentifier",
    "documentTitleText",
    "documentTypeDescriptionText",
    "documentCategory",
    "documentName",
    "filingPartyCategory",
    "documentFilingDate",
    "documentSizeQuantity",
    "pageCount",
    "fileDownloadURI",
    "trialNumber",
    "appealNumber",
    "interferenceNumber",
    "appealOutcomeCategory",
    "interferenceOutcomeCategory",
    "interferenceStyleName",
    "decisionIssueDate",
    "declarationDate",
    "lastModifiedDateTime",
)

#: Same whitelist, plus the first-page excerpt. Used when a title/category
#: filter has already narrowed the list to a handful of rows: the excerpt is
#: the whole point of such a call (it is how the caller confirms the paper is
#: the one they wanted before spending an extraction), and shedding it
#: exactly when `limit` was raised to hunt for a paper defeated the search.
#: A slim row is ~350 chars and an excerpt ~1K, so ten rows with excerpts sit
#: near 14K — comfortably inside the 40K budget, and stage 2 still truncates
#: if a docket proves otherwise.
_DOC_SLIM_FIELDS_WITH_OCR = _DOC_SLIM_FIELDS + ("documentOCRText",)

#: Above this many matched rows the excerpts go back to being shed first —
#: a broad filter is browsing, not confirming.
_OCR_KEEP_MAX_DOCS = 10


def _documents_bags(keep_ocr_text: bool = False) -> tuple:
    return (
        {
            "path": ["documents"],
            "keep_fields": (_DOC_SLIM_FIELDS_WITH_OCR if keep_ocr_text
                            else _DOC_SLIM_FIELDS),
            "min_items": _DOCUMENTS_MIN_DOCS,
            "label": "documents",
        },
    )


_DOCUMENTS_BAGS = _documents_bags()

_DOCUMENTS_NOTE = (
    "Response exceeded the client response-size limit, so document entries were "
    "slimmed to essential fields (documentOCRText first — see "
    "`_bounds.slimmed_fields`) and the list truncated if that was not enough. A "
    "larger response would have been replaced by an unrecoverable truncation "
    "error. Get the full text of a single document with "
    "PTAB_get_document_content(identifier=..., document_id=...). To narrow the "
    "list itself, filter with document_title (e.g. 'Final Written Decision'), "
    "document_category, or filing_party, or page through it with offset + a "
    "smaller limit. `_bounds.items_returned` / `items_total` report what this "
    "page held before and after; total_documents still reports the docket total."
)

#: Canonical `_bounds` sub-key -> this repo's pre-existing top-level key, so
#: consumers written against the old vocabulary keep working.
_DOCUMENTS_ALIASES = {
    "items_returned": "returned_count",
    "note": "documents_note",
}

_CONTENT_WINDOW_NOTE = (
    "Extracted text exceeded the content-size limit, so this is one window of "
    "it — nothing was dropped. Re-call PTAB_get_document_content(identifier=..., "
    "document_id=..., char_offset=<_window.next_offset>) to continue from where "
    "this window ended."
)


def _bound_documents_response(
    payload: Dict[str, Any], keep_ocr_text: bool = False
) -> Dict[str, Any]:
    """Keep a PTAB_get_documents payload under the response char budget.

    Applied to the dict BEFORE json.dumps. Delegates to the shared guard:
    stage 1 slims every entry to _DOC_SLIM_FIELDS (shedding documentOCRText),
    stage 2 halves the list until it fits (floor _DOCUMENTS_MIN_DOCS). The
    legacy marker keys (`documents_note`, `returned_count`, `count`) are kept
    as aliases alongside the shared `_bounds` vocabulary. Returns the payload
    object unmodified — no `_bounds` key at all — when it already fits.
    """
    bounded = bound_structured_response(
        payload,
        bags=_documents_bags(keep_ocr_text),
        limit=response_bounds.response_char_budget(),
        note=_DOCUMENTS_NOTE,
        aliases=_DOCUMENTS_ALIASES,
    )
    if response_bounds.BOUNDS_KEY not in bounded:
        return bounded
    # returned_count (set by the alias) and count both mean "documents in this
    # list" — keep them equal to what the caller actually receives.
    kept = len(bounded.get("documents") or [])
    bounded["returned_count"] = kept
    if "count" in bounded:
        bounded["count"] = kept
    return bounded


def _unknown_category_warning(document_category: Optional[str]) -> Optional[str]:
    """Warn when document_category is not a value the API is known to carry.

    An unrecognised category is not an error at the API — it is HTTP 404 "no
    matching records", which is indistinguishable from a genuinely empty
    docket. Naming the vocabulary here is the difference between "there is no
    final written decision" and "DECISION is the institution decision; the
    FWD's category is FINAL".
    """
    if not document_category:
        return None
    wanted = document_category.upper()
    if any(known.upper() == wanted for known in TRIAL_DOCUMENT_CATEGORIES):
        return None
    return (
        f"document_category={document_category!r} is not one of the values "
        "observed on the live PTAB document index, so an empty result here "
        "says nothing about the docket. Known values: "
        + ", ".join(sorted(TRIAL_DOCUMENT_CATEGORIES))
        + ". The final written decision is FINAL; DECISION is the "
        "institution decision. Pre-2023 dockets carry only the legacy "
        "'Paper' and 'Exhibits' values."
    )


async def _fetch_document_rows(
    api_client, adapter, identifier: str, *,
    offset: int, limit: int, sort_order: str,
    server_filters: List[Dict[str, Any]], pushed: Sequence[str],
    page_all: bool,
) -> tuple:
    """Fetch one page, or walk every page. Returns (raw_response, pages).

    A server-side filter that matches nothing comes back as the API's
    no-matching-records HTTP 404, not an empty bag. With a filter pushed down
    that is an empty RESULT, not an error, so it is normalized here rather
    than surfacing to the caller as a failure.
    """
    if page_all:
        raw_response, pages_fetched = await adapter.walk_documents(
            api_client, identifier, sort_order=sort_order,
            extra_filters=server_filters, max_docs=_PAGE_ALL_MAX_DOCS,
        )
    else:
        raw_response = await adapter.fetch_documents_page(
            api_client, identifier, offset=offset, limit=limit,
            sort_order=sort_order, extra_filters=server_filters,
        )
        pages_fetched = 1
    if pushed and is_no_matches_error(raw_response):
        raw_response = {adapter.bag_key: [], "count": 0}
    return raw_response, pages_fetched


def _annotate_documents_envelope(
    formatted_dict: Dict[str, Any], *,
    identifier_type: str,
    total_documents: Optional[int],
    total_is_docket_total: bool,
    returned_count: int,
    filters_applied: Dict[str, str],
    pushed: Sequence[str],
    client_side_names: Sequence[str],
    matched_total: int,
    offset: int,
    limit: int,
    sort_order: str,
    page_all: bool,
    pages_fetched: int,
    docket_truncation_note: Optional[str],
    docket_partial_note: Optional[str],
    category_warning: Optional[str],
) -> Dict[str, Any]:
    """Attach every non-paging annotation to the response envelope."""
    formatted_dict["total_documents"] = total_documents
    formatted_dict["returned_count"] = returned_count
    if not total_is_docket_total:
        formatted_dict["total_documents_note"] = (
            f"total_documents is the number of records this {identifier_type} "
            "response carried, NOT a docket total — the endpoint does not "
            "paginate and reports no count. See `paging.total_source`."
        )
    elif pushed:
        formatted_dict["total_documents_note"] = (
            "total_documents counts the docket's documents matching the "
            f"server-side filters ({', '.join(sorted(pushed))}), not the "
            "docket's document total."
        )
    if filters_applied:
        formatted_dict["filters_applied"] = filters_applied
        if pushed:
            formatted_dict["filters_server_side"] = sorted(pushed)
        if client_side_names:
            formatted_dict["filters_client_side"] = list(client_side_names)
        formatted_dict["matched_total"] = matched_total
        formatted_dict["filter_semantics_note"] = _filter_semantics_note(
            pushed, client_side_names, page_all
        )
    formatted_dict["offset"] = offset
    formatted_dict["limit"] = limit
    formatted_dict["sort_order"] = sort_order
    formatted_dict["page_all"] = page_all
    formatted_dict["pages_fetched"] = pages_fetched
    if docket_partial_note:
        formatted_dict["docket_partial"] = True
        formatted_dict["docket_partial_note"] = docket_partial_note
    if docket_truncation_note:
        formatted_dict["docket_truncated"] = True
        formatted_dict["docket_truncation_note"] = docket_truncation_note
    if category_warning:
        formatted_dict["filter_warning"] = category_warning
    return formatted_dict


def _documents_paging_envelope(
    payload: Dict[str, Any],
    *,
    identifier_type: str,
    limit_requested: int,
    offset: int,
    total_documents: Optional[int],
    total_is_docket_total: bool,
    scanned: Optional[int] = None,
    client_side_filters: Optional[Dict[str, str]] = None,
    pages_fetched: int = 1,
    page_all: bool = False,
    server_side_filters: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Report the limit ACTUALLY applied, plus a paging cursor.

    api/ptab_client.py clamps a trial document page to _API_DOCUMENT_PAGE_CAP
    while this tool accepts up to 200, so a limit=150 request silently
    returned at most 100 while the envelope echoed 150. `limit_applied` is
    what the upstream call really used.

    `total_documents` means "true docket total" only for trials, whose POST
    search endpoint reports a real count. Appeals and interferences come from
    a non-paginating GET, so their total is only what this one response
    carried; `paging.total` is null there and `total_source` says so rather
    than passing a page size off as a docket total.

    `scanned` is the number of server rows this call consumed (the fetched
    page BEFORE document_title / document_category / filing_party /
    outcome_category filtering, which is client-side). When a client-side
    filter is active the cursor must advance by `scanned`, not by `returned`:
    advancing by the matched count re-scanned rows the caller had already
    seen and, on a page with zero matches, produced has_more=true with
    next_offset == offset — an infinite loop (observed on IPR2015-00040,
    document_title='Final Written Decision', limit=3, 2026-08-21).
    """
    if not isinstance(payload, dict):
        return payload
    returned = len(payload.get("documents") or [])
    limit_applied = (
        min(limit_requested, _API_DOCUMENT_PAGE_CAP)
        if identifier_type == "trial"
        else limit_requested
    )
    total = total_documents if total_is_docket_total else None
    filtered = bool(client_side_filters)
    # Rows consumed from the server. Without a client-side filter the cursor
    # follows `returned` so that a response-size truncation (which drops
    # trailing documents) still points at the first document not received.
    consumed = scanned if (filtered and scanned is not None) else returned
    has_more = isinstance(total, int) and (offset + consumed) < total
    if page_all:
        # The walk already consumed the docket (or hit its cap, which the
        # envelope marks separately), so there is no next page to point at.
        has_more = False
    paging: Dict[str, Any] = {
        "limit_requested": limit_requested,
        "limit_applied": limit_applied,
        "offset": offset,
        "returned": returned,
        "scanned": scanned if scanned is not None else returned,
        "total": total,
        "has_more": has_more,
        "next_offset": offset + consumed if has_more else None,
        "total_source": (
            "api_count_filtered" if (total_is_docket_total and server_side_filters)
            else "api_count" if total_is_docket_total else "returned_page"
        ),
        "pages_fetched": pages_fetched,
        "page_all": page_all,
    }
    if server_side_filters:
        paging["server_side_filters"] = list(server_side_filters)
        paging["total_note"] = (
            "`total` counts the documents on this docket matching the "
            f"server-side filters {', '.join(server_side_filters)} — it is "
            "NOT the docket's document total."
        )
    if page_all:
        paging["note"] = (
            "page_all=True: every server page was fetched before filtering, "
            "so `scanned` is the whole docket (or as much of it as the "
            f"{_PAGE_ALL_MAX_DOCS}-document cap allowed — see "
            "`docket_truncated`) and offset/limit were applied client-side "
            "to the complete match set. There is no next page."
        )
    if filtered:
        paging["client_side_filters"] = sorted(client_side_filters)
        paging["filter_note"] = (
            "The filters in client_side_filters are applied by this tool AFTER "
            "the server page is fetched, so `returned` counts matches within the "
            "`scanned` server rows of this page, not the docket-wide match "
            "count. `returned` can be 0 while has_more is true; keep paging "
            "from next_offset (which advances past every scanned row) until "
            "has_more is false."
        )
    if not total_is_docket_total:
        paging["note"] = (
            f"The {identifier_type} documents endpoint is a non-paginating GET, so "
            "total_documents counts only the records this call returned — it is NOT "
            "a docket total and the true total is unknown. limit/offset are applied "
            "client-side to that single response."
        )
    payload["paging"] = paging
    return payload


async def ptab_get_documents(
    identifier: str,
    identifier_type: str = "trial",
    limit: int = 50,
    offset: int = 0,
    sort_order: str = "desc",
    document_title: Optional[str] = None,
    document_category: Optional[str] = None,
    filing_party: Optional[str] = None,
    outcome_category: Optional[str] = None,
    page_all: bool = False
) -> str:
    """Get list of documents for trial, appeal, or interference with SELECTIVE FILTERING.
    Document list, docket, papers, filings, briefs, petitions, exhibits, decisions, orders, motions on a proceeding.

    ⚠️ CRITICAL: For proceedings with 50+ documents, ALWAYS use filtering parameters.
    Requesting all documents without filters can cause massive token usage.

    PREREQUISITE: Must have valid trial/appeal/interference identifier from search results.

    📋 FILTERING PARAMETERS:

    **limit** - Max documents to return (default: 50, max: 100 — API page cap). Applied AFTER filtering.

    **offset** - Skip the first N documents (default: 0).
      For trials: server-side — sent directly to the POST search endpoint.
      Example: sort_order='asc', offset=25, limit=25 → documents 26-50 oldest-first.

    **sort_order** - Sort direction (default: "desc"):
      - "desc": Newest first (default)
      - "asc": Oldest first — surfaces the Petition, POPR, Institution Decision,
               and early exhibits filed at the beginning of the proceeding.
      For trials: sort is server-side (documentData.documentFilingDate), so offset=0
      with sort_order='asc' reliably returns the oldest documents (Petition, etc.).
      For appeals/interferences: sort is client-side on whatever the GET endpoint returns.

    RETRIEVING EARLY DOCUMENTS (Petition, POPR, Institution Decision):
      # Oldest documents first — Petition, POPR, early exhibits
      PTAB_get_documents(identifier='IPR2024-01353', sort_order='asc', limit=25)
      # Skip first 5 oldest, get next 10
      PTAB_get_documents(identifier='IPR2024-01353', sort_order='asc', offset=5, limit=10)

    **document_title** - Title filter, applied SERVER-side across the whole docket
      (case-insensitive PHRASE match on documentTitleText: whole words, in order).
      This is docket-wide, not page-wide: on IPR2024-00990 document_title='Petition'
      returns the petition itself, where a substring test also matches
      "Petitioner's Reply". A partial word ('Instit') will NOT match — use a whole
      phrase, or page_all=True for substring behaviour over documentTitleText AND
      documentTypeDescriptionText.
      More precise than document_category — use it to target a single document type.
      Examples:
        PTAB_get_documents(identifier='IPR2024-01353', document_title='Final Written Decision')
        PTAB_get_documents(identifier='IPR2024-01353', document_title='Institution Decision')
        PTAB_get_documents(identifier='IPR2024-01353', document_title='Petition for Inter Partes')
        PTAB_get_documents(identifier='IPR2024-01353', document_title='Patent Owner Response')
        PTAB_get_documents(identifier='IPR2024-01353', document_title='Oral Hearing')
      Tip: use a short whole word (e.g. 'Institution', 'Oral') to cast a wider net;
           use a longer phrase to target exactly one document.

    📄 PAGINATION (trials only): Uses server-side pagination via POST search endpoint.
    Returns the true total_documents count and a next_offset hint when more pages exist.
    Full docket access example for a 40-paper proceeding:
      # Page 1 — Papers 1-25 oldest first (Petition, POPR, Institution Decision...)
      PTAB_get_documents(identifier='IPR2024-01353', sort_order='asc', offset=0, limit=25)
      # Page 2 — Papers 26-40
      PTAB_get_documents(identifier='IPR2024-01353', sort_order='asc', offset=25, limit=25)
    Appeals/Interferences still use a GET endpoint with no server-side pagination.

    **document_category** - Exact, case-insensitive category match for trials.
      Applied SERVER-side (docket-wide), so the count it returns is a docket count.

      ⚠️ THE FINAL WRITTEN DECISION'S CATEGORY IS **FINAL**, NOT DECISION.
         DECISION is the INSTITUTION decision. Asking for DECISION on a
         concluded trial returns the institution decision and no FWD.

      The full observed vocabulary (probed live 2026-08-30; an unlisted value
      returns nothing, which is indistinguishable from an empty docket):
        Papers filed roughly 2023 onward:
        - PETITION    the petition
        - POPR        patent owner's preliminary response
        - RESPONSE    patent owner response; discretionary-denial briefing
        - REPLY       reply in support of a motion
        - REPLYTOOPP  petitioner's reply to the patent owner response
        - SURREPLY    sur-reply (rare; usually filed as RESPONSE)
        - MOTION      motions, oppositions to Director Review, motions to seal
        - OPPOSITION  opposition to a motion
        - ORDER       Board orders (conduct, panel change, hearing)
        - DECISION    INSTITUTION decision (grant or deny)
        - FINAL       FINAL WRITTEN DECISION
        - REHEARING   rehearing / Director Review decisions and orders
        - REQUEST     requests for rehearing, Director Review, oral argument
        - NOTICE      notices (filing date, deposition, appeal, exhibit lists)
        - TERMINATE   termination decisions (settlement, adverse judgment)
        - PWR ATTY    powers of attorney
        - Exhibit     exhibits — the bulk of any docket
        - OTHER       catch-all, INCLUDING party-filed public/redacted copies
                      of sealed Board papers
        Legacy, dockets up to roughly 2022 — these are the ONLY two values
        such a docket carries, so no per-paper category filter works there:
        - Paper       every non-exhibit paper, whatever it is
        - Exhibits    every exhibit

      SEALED DOCKETS: the Board's own FWD paper can be missing from the index
      entirely. On IPR2024-00864 document_category='FINAL' returns nothing and
      the only FWD row is a PETITIONER-filed public copy in category OTHER.
      When that happens the response carries a `coverage_note` saying so.

    **page_all** - Walk EVERY server page before filtering (default False).
      Filters are otherwise applied to one page. Set page_all=True when a
      filter returns nothing on a large docket and you need certainty rather
      than another guess at offset. Costs one API call per 100 documents, caps
      at 1000 documents (`docket_truncated` marks the cap), and reports
      `pages_fetched`. Under page_all, document_title reverts to a substring
      match over the whole docket.

    **filing_party** - Filter trials by filing party (case-insensitive):
      Key Parties:
        - BOARD: Board documents (orders, decisions)
        - PETITIONER: Petitioner submissions
        - PATENT OWNER: Patent owner submissions

    **outcome_category** - Filter appeals/interferences by outcome (case-insensitive):
      Appeals: "Affirmed", "Reversed", "Rehearing Decision Denied"
      Interferences: "Final Decision", "Judgment", etc.

    📌 EXAMPLES (always use filtering for large proceedings):

    # Final Written Decision only — the category is FINAL, not DECISION
    PTAB_get_documents(identifier='IPR2024-01353', document_category='FINAL', limit=5)

    # Institution decision (that is what DECISION means)
    PTAB_get_documents(identifier='IPR2024-01353', document_category='DECISION', limit=5)

    # A filter came back empty on a big docket and you need certainty
    PTAB_get_documents(identifier='IPR2024-00864', document_title='Preliminary Response',
                       page_all=True, limit=20)

    # All Board orders
    PTAB_get_documents(identifier='IPR2024-01353', filing_party='BOARD', limit=20)

    # Patent owner responses
    PTAB_get_documents(identifier='IPR2024-01353', filing_party='PATENT OWNER')

    # Appeals with specific outcome
    PTAB_get_documents(identifier='2025000943', identifier_type='appeal',
                       outcome_category='Affirmed', limit=10)

    ⚠️ AVOID: PTAB_get_documents(identifier='...', limit=100) without filters
    ✅ DO: Always filter by document_category, filing_party, or outcome_category

    BASIC USAGE:
    - Core Purpose: Retrieve complete document list for any PTAB proceeding
    - Returns: Documents with filtering applied
    - Supports: Trials (IPR/PGR/CBM), Appeals, Interferences (via identifier_type parameter)
    - Typical Volume: 10-100+ documents depending on proceeding complexity

    WHEN TO USE THIS TOOL:
    - Document Discovery: After selecting trial/appeal/interference from search results
    - Selective Download Planning: Review documents before downloading (target only what you need)
    - Multi-Document Workflows: Get all document IDs for batch processing
    - Progressive Disclosure Stage 3: After minimal search → balanced analysis → document operations

    DOCUMENT WORKFLOW:
    1. Use PTAB_search_trials_minimal/balanced to find proceeding - Get trial number
    2. Use PTAB_get_documents (this tool) with filters - Get specific document types
    3. User/LLM selects priority documents based on use case
    4. Use PTAB_get_document_download - Get browser-accessible download links
    5. OR use PTAB_get_document_content - Extract text for LLM analysis (slower for scanned documents)

    PRIORITY DOCUMENTS BY USE CASE:

    IPR Response Strategy:
      PTAB_get_documents(identifier='...', document_category='FINAL')
      - Final Written Decision (outcome analysis). NOTE: no PTAB search tier
        carries claim-level outcomes at any tier, so which claims were
        cancelled or upheld comes only from this document's own text.
      PTAB_get_documents(identifier='...', document_category='DECISION')
      - Institution Decision (claims instituted)

    Prior Art Research:
      PTAB_get_documents(identifier='...', filing_party='PETITIONER')
      - Petition documents (petitioner's case)
      - Petitioner exhibits (cited references)

    Litigation Preparation:
      PTAB_get_documents(identifier='...', filing_party='BOARD', limit=20)
      - All decisions and orders (procedural history)
      - Estoppel analysis documents

    RELATED TOOLS:
    - Next Step: PTAB_get_document_download (browser access) or PTAB_get_document_content (LLM analysis)
    - Previous Step: PTAB_search_trials_minimal/balanced (find trials first)
    - Cross-MCP (prosecution side): PFW_get_oa_rejections (structured rejection
      map) then PFW_get_oa_text (the examiner's words in one call, no document
      bag and no OCR) are the primary path for office actions;
      PFW_get_application_documents + PFW_get_document_content_with_ocr is the
      fallback for non-OA papers, office actions older than roughly 2008, or an
      actual PDF

    GUIDANCE REFERENCES:
    - For document selection strategies: PTAB_get_guidance(section='documents')
    - For multi-document workflows: PTAB_get_guidance(section='documents')
    - For context optimization (targeted extraction): PTAB_get_guidance(section='cost')

    Args:
        identifier: Trial number (IPR2024-01353), appeal number (2024-001234), or interference number
        identifier_type: Type of proceeding - "trial" (default), "appeal", or "interference"
        limit: Max documents to return (default: 50, max: 100 — the API rejects larger pages)
        offset: Skip first N documents (default: 0). Server-side for trials, client-side for appeals/interferences.
        sort_order: Sort direction - "desc" (newest first, default) or "asc" (oldest first).
                    Server-side for trials (by documentFilingDate); client-side for appeals/interferences.
        document_title: Case-insensitive substring match on documentTypeDescriptionText.
                        Use to target specific document types, e.g. 'Final Written Decision',
                        'Institution Decision', 'Petition for Inter Partes', 'Patent Owner Response'.
        document_category: Exact category match for trials, applied server-side.
                        The FINAL WRITTEN DECISION is FINAL; DECISION is the
                        institution decision. Full vocabulary: PETITION, POPR,
                        RESPONSE, REPLY, REPLYTOOPP, SURREPLY, MOTION,
                        OPPOSITION, ORDER, DECISION, FINAL, REHEARING, REQUEST,
                        NOTICE, TERMINATE, PWR ATTY, Exhibit, OTHER — plus the
                        legacy 'Paper' and 'Exhibits', which are the only two
                        values a pre-2023 docket carries.
        filing_party: Filter trials by filing party (BOARD, PETITIONER, PATENT OWNER),
                        applied server-side
        outcome_category: Filter appeals/interferences by outcome (client-side)
        page_all: Walk every server page before filtering (default False). Use
                        when a filter returns nothing on a large docket. Caps at
                        1000 documents; reports `pages_fetched` and marks
                        `docket_truncated` if the cap was hit.

    Returns:
        JSON string with the filtered document list, plus `pages_fetched`,
        `matched_total`, `filters_server_side` / `filters_client_side` and a
        `filter_semantics_note` saying where each filter ran, and a
        `coverage_note` when the Board's own final written decision is absent
        from the docket rows. Oversized responses are automatically slimmed
        (documentOCRText dropped, list truncated if still too large) with a
        `documents_note` saying what was dropped — but the documentOCRText
        first-page excerpt is KEPT for a title/category filter that matched
        10 rows or fewer, since confirming the paper is the point of such a
        call.

    Example:
        {"identifier": "IPR2024-01353",
         "identifier_type": "trial",
         "total_documents": 45,
         "filtered_count": 5,
         "filter_applied": {"document_category": "DECISION"},
         "documents": [
             {"documentIdentifier": "171303338",
              "documentTitleText": "Final Written Decision",
              "documentFilingDate": "2024-05-15",
              "documentSizeQuantity": 97699}
         ]}
    """
    try:
        api_client = _client()

        sort_order = _validate_document_query(limit, offset, sort_order)
        identifier_type = validate_identifier_type(identifier_type)
        adapter = get_adapter(identifier_type)
        identifier = adapter.validate_identifier(identifier)

        # Push what the API index can do itself. document_category and
        # filing_party are exact case-insensitive matches server-side,
        # identical to the client-side test but DOCKET-wide instead of
        # page-wide. document_title is pushed only when we are not walking
        # every page, because the server matches a phrase and the local
        # filter matches a substring.
        server_filters, pushed = _server_side_document_filters(
            identifier_type, document_title, document_category, filing_party,
            push_title=not page_all,
        )

        # Route to the correct API method via the adapter.
        # Trials: POST search endpoint (server-side pagination/sort).
        # Appeals/Interferences: GET convenience endpoints.
        raw_response, pages_fetched = await _fetch_document_rows(
            api_client, adapter, identifier,
            offset=offset, limit=limit, sort_order=sort_order,
            server_filters=server_filters, pushed=pushed, page_all=page_all,
        )

        # Check for API error
        if raw_response.get("error"):
            return json.dumps(raw_response, indent=_JSON_INDENT)

        # Flatten the proceeding's data bag into a plain document list
        documents = adapter.flatten_documents(raw_response)

        # For trials: API returns the true total count (server-side pagination)
        # For appeals/interferences: count what we got (no pagination support),
        # which is a PAGE size, not a docket total — `paging.total_source`
        # and `total_documents_note` say which one this is.
        api_total_count = raw_response.get("count")
        total_is_docket_total = identifier_type == "trial" and api_total_count is not None
        total_documents = api_total_count if total_is_docket_total else len(documents)

        # Apply filtering, then sort/paginate (client-side for non-trials,
        # and for a trial whose pages we walked ourselves)
        filtered_documents, filters_applied = _filter_documents(
            documents, identifier_type,
            document_title, document_category, filing_party, outcome_category,
            already_server_side=pushed,
        )
        client_side_names = sorted(set(filters_applied) - set(pushed))
        matched_total = len(filtered_documents)
        filtered_documents = _sort_and_paginate(
            filtered_documents, identifier_type, sort_order, offset, limit,
            paginate=(identifier_type != "trial") or page_all,
        )

        # Format output with filtering metadata
        formatted_dict = _annotate_documents_envelope(
            build_document_list(
                documents=filtered_documents,
                identifier=identifier,
                identifier_type=identifier_type,
                count=len(filtered_documents),
            ),
            identifier_type=identifier_type,
            total_documents=total_documents,
            total_is_docket_total=total_is_docket_total,
            returned_count=len(filtered_documents),
            filters_applied=filters_applied,
            pushed=pushed,
            client_side_names=client_side_names,
            matched_total=matched_total,
            offset=offset,
            limit=limit,
            sort_order=sort_order,
            page_all=page_all,
            pages_fetched=pages_fetched,
            docket_truncation_note=raw_response.get("docket_truncation_note"),
            docket_partial_note=raw_response.get("docket_partial_note"),
            category_warning=(
                _unknown_category_warning(document_category)
                if identifier_type == "trial" else None
            ),
        )

        # Say so when the Board's own final written decision is not a docket
        # row. Cheap when we have rows to look at; one extra call only when a
        # document_category='FINAL' request came back empty, which is exactly
        # the case that needs the explanation.
        coverage_note = _fwd_coverage_note(documents)
        if (coverage_note is None and identifier_type == "trial"
                and (document_category or "").upper() == "FINAL"
                and not filtered_documents):
            coverage_note = await _probe_fwd_coverage(
                api_client, adapter, identifier
            )
        if coverage_note:
            formatted_dict["coverage_note"] = coverage_note

        # Response-size backstop, applied to the dict before serialization.
        # Runs before next_offset so the paging hint points at the first
        # document the caller did NOT receive (no-op when nothing was dropped).
        formatted_dict = _bound_documents_response(
            formatted_dict,
            keep_ocr_text=(
                bool({"document_title", "document_category"} & set(filters_applied))
                and len(filtered_documents) <= _OCR_KEEP_MAX_DOCS
            ),
        )

        formatted_dict = _documents_paging_envelope(
            formatted_dict,
            identifier_type=identifier_type,
            limit_requested=limit,
            offset=offset,
            total_documents=total_documents,
            total_is_docket_total=total_is_docket_total,
            scanned=len(documents),
            client_side_filters={k: v for k, v in filters_applied.items()
                                 if k in client_side_names},
            pages_fetched=pages_fetched,
            page_all=page_all,
            server_side_filters=sorted(pushed),
        )

        # Legacy top-level cursor: keep it in lockstep with paging.next_offset
        # (it used to advance by matched rows, which stalled under a filter).
        if identifier_type == "trial" and formatted_dict["paging"]["has_more"]:
            formatted_dict["next_offset"] = formatted_dict["paging"]["next_offset"]

        return json.dumps(formatted_dict, indent=_JSON_INDENT)

    except ValueError as e:
        # Error class and tool only, never the rejected value (PT-38).
        logger.warning("Validation rejected in PTAB_get_documents: %s", type(e).__name__)
        return format_error_response(str(e), "VALIDATION_ERROR")
    except RuntimeError as e:
        # Re-raises anything that is not an interpreter shutdown.
        return async_lifecycle_envelope(e, "PTAB_get_documents")
    except Exception as e:
        logger.error(f"Error in PTAB_get_documents: {str(e)}")
        return format_error_response(str(e), "API_ERROR")




async def _resolve_indexed_document(
    api_client,
    adapter,
    identifier: str,
    identifier_type: str,
    document_id: str,
    preserve_parent: bool = False,
) -> tuple:
    """The document's INDEX ENTRY, tried every way before the URI fallback.

    Returns (matching_doc, docs_response) — docs_response only so the caller
    can build an honest not-found message from the walk's own markers.

    The order is the fix for a live defect (prod, 2026-09-03). The document's
    own metadata is what names the file, and the constructed ptab-files URI
    carries NONE of it, so that URI has to be the last resort rather than the
    first miss:

      1. Targeted server-side lookup by documentData.documentIdentifier — one
         row, one request, independent of where the paper sits in the docket,
         of the endpoint's 100-row page cap and of
         api/ptab_client.search_all_trial_documents' 500-document safety cap.
      2. The full docket walk (every page), as before.
      3. Only then the constructed ptab-files URI, for papers the index
         genuinely does not carry (tests/TEST_SUITE.md T9).

    Before step 1 existed there was exactly one path to a paper's metadata,
    and ANY miss on it — an upstream failure of the walk, an open circuit, a
    docket truncated at the safety cap — was indistinguishable from "this
    paper is not indexed", so a fully indexed document was silently renamed
    from its own title and date to the word DOCUMENT and the PROCEEDING's
    filing date. PTAB_get_document_download(IPR2024-01353, 171303338) returned
    PTAB-2024-08-23_IPR2024-01353_PAT-7883848_DOCUMENT.pdf — the trial's
    2024-08-23 accorded filing date — for a Final Written Decision that
    PTAB_get_documents was returning as Paper 40, filed 2026-03-04. The bytes
    were right; only the metadata had fallen through.
    """
    targeted = await adapter.fetch_document_by_id(api_client, identifier, document_id)
    if isinstance(targeted, dict) and not targeted.get("error"):
        found = find_document(
            adapter.flatten_documents(targeted, preserve_parent=preserve_parent),
            document_id,
        )
        if found:
            return found, targeted

    docs_response = await adapter.fetch_all_documents(api_client, identifier)
    documents = adapter.flatten_documents(docs_response, preserve_parent=preserve_parent)
    found = find_document(documents, document_id)
    if found:
        return found, docs_response

    # Trial numbers and document ids are public identifiers — allowed in logs.
    logger.info(
        "Document %s not resolved from the %s index; falling back to the "
        "fileDownloadURI pattern (metadata will be generic)",
        document_id, identifier,
    )
    return (
        find_document_or_fallback_uri(
            documents, document_id, identifier, identifier_type
        ),
        docs_response,
    )


def _derive_document_metadata(
    matching_doc: Dict[str, Any],
    identifier_type: str,
    proceeding_patent_number,
    proceeding_filing_date,
) -> tuple:
    """(description, page_count, document_code, filing_date, patent_number)
    for enhanced-filename generation — field names vary by proceeding type."""
    # Shared with the proxy's download route (D-3). The preserved parent bag is
    # passed so the appeal/trial category is read from the same place on both
    # paths; "Document" stays this call site's own sentinel.
    doc_description = derive_document_description(
        matching_doc,
        matching_doc.get("_patentOwnerData") or matching_doc.get("_appellantData"),
    ) or "Document"

    page_count = matching_doc.get("pageCount", "Unknown")
    document_code = matching_doc.get("documentCategory")

    # Filing date from document (more accurate) or fallback to proceeding
    filing_date = matching_doc.get("documentFilingDate") or proceeding_filing_date or ""

    # Patent number from preserved parent data or fallback to proceeding
    if identifier_type == "trial":
        patent_number = matching_doc.get("_patentOwnerData", {}).get("patentNumber") or proceeding_patent_number
    elif identifier_type == "appeal":
        patent_number = matching_doc.get("_appellantData", {}).get("patentNumber") or proceeding_patent_number
    else:
        patent_number = proceeding_patent_number

    return doc_description, page_count, document_code, filing_date, patent_number


async def _resolve_download_delivery(
    *,
    identifier: str,
    identifier_type: str,
    document_id: str,
    download_url: str,
    patent_number,
    application_number,
    enhanced_filename: str,
) -> tuple:
    """Resolve how a download is delivered (metrics §1.2 helper).

    Tries the PFW centralized proxy first; fails back to a local persistent
    token-in-path link (Lesson 43). Returns
    (final_url, proxy_mode, proxy_note, centralized_available).
    """
    centralized_url = await register_with_centralized_proxy(
        identifier=identifier,
        identifier_type=identifier_type,
        document_id=document_id,
        download_url=download_url,
        api_key=settings.uspto_api_key,
        patent_number=patent_number,
        application_number=application_number,
        enhanced_filename=enhanced_filename,
        internal_auth_secret=settings.internal_auth_secret
    )

    if centralized_url:
        logger.info(f"✅ Using centralized proxy: {centralized_url}")
        return (
            centralized_url,
            "centralized",
            "Unified download through PFW centralized proxy (persistent links, "
            "enhanced rate limiting, cross-MCP sharing)",
            True,
        )

    # Failback - use local PTAB proxy
    local_port = get_local_proxy_port()

    # Ensure local proxy is running (on-demand startup if ENABLE_ALWAYS_ON_PROXY=false)
    proxy_started = await _ensure_local_proxy_running(local_port)
    if not proxy_started:
        logger.warning("Local proxy failed to start - download URL may not work")

    # Persistent token-in-path link (Lesson 43): the hash is the credential,
    # so browser navigation works without headers. The encrypted payload
    # stores the resolved fileDownloadURI, so the proxy streams directly
    # without re-searching the document index.
    from ..proxy.secure_link_cache import get_link_cache
    proxy_base = _get_ptab_proxy_base_url(local_port)
    final_url = get_link_cache().generate_persistent_link(
        identifier_type=identifier_type,
        identifier=identifier,
        document_id=document_id,
        file_download_uri=download_url,
        enhanced_filename=enhanced_filename,
        base_url=proxy_base,
    )
    # Never log the link itself — the hash is the credential (Lesson 43)
    logger.info("ℹ️  Persistent download link generated (local proxy mode)")
    return (
        final_url,
        "local",
        "Local PTAB proxy persistent link (valid 7 days, survives proxy "
        "restarts; automatic failback from centralized proxy)",
        False,
    )


async def ptab_get_document_download(
    document_id: str,
    identifier: str,
    identifier_type: str = "trial",
    ctx: Context = None
) -> str:
    """Generate secure browser-accessible download URLs for PTAB documents (PDFs).
    Download, PDF, file, link, URL, save, open in a browser, get a copy of a paper or exhibit.

    PREREQUISITE: First use PTAB_get_documents to get document_identifier from document list.

    BASIC USAGE:
    - Core Purpose: Create clickable proxy links for browser downloads (handles API authentication)
    - Proxy Integration: Centralized PFW proxy (port 8080) with automatic fallback to local (port 8083)
    - Link Validity: 7-day persistent links (remain valid after proxy restart)
    - Security: Keeps API credentials secure while enabling direct browser access

    WHEN TO USE THIS TOOL:
    - User Download: When user will review document themselves in browser
    - Multi-Document Packages: Generate download links for complete docket
    - Legal Review Workflows: Provide attorneys with browser-accessible PDFs
    - Fast Delivery: Use download (instant link) instead of content extraction (slower for scanned documents)

    DOWNLOAD VS EXTRACT DECISION TREE:

    User needs document → User will read it themselves?
      YES → PTAB_get_document_download (this tool) - instant link
            Returns browser-accessible link
            User downloads and reviews directly

      NO → LLM needs to analyze content?
           YES → PTAB_get_document_content - full text extraction
                 Hybrid extraction (pypdf + OCR)
                 Slower for scanned documents; adds full text to context
                 Limit to 1-3 critical documents

    CRITICAL RESPONSE FORMAT - Always format with BOTH clickable link and raw URL:

    Format: **[Download {DocumentType} ({PageCount} pages)]({proxy_url})** | Raw URL: `{proxy_url}`

    Why both formats?
    - Clickable links work in Claude Desktop and most clients
    - Raw URLs enable copy/paste in Msty and other clients where links aren't clickable
    - Ensures maximum compatibility across different MCP clients

    Example:
      **[Download Final Written Decision (45 pages)](http://localhost:8080/download/...)** | Raw URL: `http://localhost:8080/download/...`

    MULTI-DOCUMENT WORKFLOW:

    Step 1: Get document list
      docs = PTAB_get_documents(identifier='IPR2024-01353', identifier_type='trial')

    Step 2: Filter to priority documents (e.g., Final Written Decisions)
      fwd_docs = [d for d in docs['documents']
                  if 'Final Written Decision' in d.get('description', '')]

    Step 3: Generate download links for all (up to 5-10)
      for doc in fwd_docs[:5]:
          download = PTAB_get_document_download(
              identifier='IPR2024-01353',
              identifier_type='trial',
              document_id=doc['documentIdentifier']
          )

    Step 4: Format with BOTH clickable and raw URL
      link = f"**[Download {doc['description']} ({doc['pageCount']} pages)]({download['proxy_url']})** | Raw URL: `{download['proxy_url']}`"

    PROXY BEHAVIOR:
    - Always-on mode: Set ENABLE_ALWAYS_ON_PROXY=true for immediate access
    - Persistent links: Enabled by default - 7-day encrypted links
    - Centralized proxy detection: Automatic fallback if PFW proxy unavailable
    - Download links work immediately and remain valid for 7 days

    EXPECTED FILENAME FORMATS:
    Pattern: PTAB-{date}_{trial}_{patent}_{description}.pdf

    Examples:
      - PTAB-2024-08-23_IPR2024-01353_PAT-7883848_FINAL_WRITTEN_DECISION.pdf
      - PTAB-2025-07-01_PGR2025-00045_PAT-12102027_INSTITUTION_DECISION.pdf
      - PTAB-2024-08-23_IPR2024-01353_PAT-7883848_PATENT_OWNER_RESPONSE.pdf

    RELATED TOOLS:
    - Previous Step: PTAB_get_documents (get document list and IDs first)
    - Alternative: PTAB_get_document_content (LLM analysis instead of user download)
    - Cross-MCP: PFW_get_document_download (prosecution history documents)

    GUIDANCE REFERENCES:
    - For download link formatting: PTAB_get_guidance(section='documents')
    - For multi-document workflows: PTAB_get_guidance(section='documents')
    - For context optimization: PTAB_get_guidance(section='cost')
    - For cross-MCP integration: PTAB_get_guidance(section='workflows_pfw')

    Args:
        document_id: Document identifier from PTAB_get_documents()
        identifier: Trial/appeal/interference number
        identifier_type: Type of proceeding - "trial" (default), "appeal", or "interference"

    Returns:
        JSON string with download URL, proxy info, and llm_response_guidance

    Example Response:
        {
            "document_id": "171303338",
            "identifier": "IPR2024-01353",
            "proxy_url": "http://localhost:8080/download/IPR2024-01353/171303338",
            "document_description": "Final Written Decision",
            "page_count": 45,
            "enhanced_filename": "PTAB-2024-08-23_IPR2024-01353_PAT-7883848_FINAL_WRITTEN_DECISION.pdf",
            "llm_response_guidance": {
                "format": "**[Download Final Written Decision (45 pages)](http://localhost:8080/download/...)** | Raw URL: `http://localhost:8080/download/...`",
                "critical": "Provide clickable markdown link for browser access AND raw URL for clients like Msty where links aren't clickable",
                "example": "**[Download Final Written Decision (45 pages)](http://localhost:8080/download/IPR2024-01353/171303338)** | Raw URL: `http://localhost:8080/download/IPR2024-01353/171303338`"
            }
        }
    """
    try:
        api_client = _client()

        identifier_type, adapter, identifier, document_id = (
            _validate_document_request(identifier, identifier_type, document_id)
        )

        # Fetch proceeding-level metadata (patent/application/filing date)
        (
            proceeding_patent_number,
            proceeding_application_number,
            proceeding_filing_date,
        ) = await adapter.fetch_proceeding_metadata(api_client, identifier)

        # Resolve the paper's index entry: targeted documentIdentifier lookup,
        # then the full docket walk, and only then the constructed ptab-files
        # URI. Parent data is preserved for enhanced-filename generation.
        matching_doc, docs_response = await _resolve_indexed_document(
            api_client, adapter, identifier, identifier_type, document_id,
            preserve_parent=True,
        )

        if not matching_doc:
            raise ValueError(_not_found_message(document_id, identifier, docs_response))

        # Extract download URL
        download_url = matching_doc.get("fileDownloadURI")

        if not download_url:
            raise ValueError(f"No download URI found for document {document_id}")

        # Derive filename metadata (field names vary by proceeding type)
        (
            doc_description,
            page_count,
            document_code,
            filing_date,
            patent_number,
        ) = _derive_document_metadata(
            matching_doc, identifier_type,
            proceeding_patent_number, proceeding_filing_date,
        )
        application_number = proceeding_application_number

        # Generate enhanced filename
        enhanced_filename = generate_enhanced_filename(
            filing_date=filing_date,
            identifier=identifier,
            patent_number=patent_number,
            document_description=doc_description,
            document_code=document_code
        )

        # Resolve delivery: centralized PFW proxy, else local persistent link
        (
            final_url,
            proxy_mode,
            proxy_note,
            centralized_available,
        ) = await _resolve_download_delivery(
            identifier=identifier,
            identifier_type=identifier_type,
            document_id=document_id,
            download_url=download_url,
            patent_number=patent_number,
            application_number=application_number,
            enhanced_filename=enhanced_filename,
        )

        # Register with the recent-downloads panel/page (best effort).
        # viewer_key scopes the registry entry to this caller (C-1) — the
        # proxy stores only its hash.
        viewer_key = get_viewer_key()
        download_registry_id = await _register_download_via_proxy({
            "download_url": final_url,
            "identifier": identifier,
            "identifier_type": identifier_type,
            "document_id": document_id,
            "document_description": doc_description,
            "enhanced_filename": enhanced_filename,
            "page_count": page_count,
            "filing_date": filing_date,
            "patent_number": patent_number,
            "proxy_mode": proxy_mode,
            "viewer_key": viewer_key,
        })

        response = {
            "document_id": document_id,
            "identifier": identifier,
            "identifier_type": identifier_type,
            "download_url": final_url,
            "document_description": doc_description,
            "page_count": page_count,
            "filing_date": filing_date,
            "patent_number": patent_number,
            "enhanced_filename": enhanced_filename,
            "proxy_info": {
                "mode": proxy_mode,
                "note": proxy_note,
                "centralized_available": centralized_available
            },
            "download_id": download_registry_id,
            # Retained for wire compatibility — the server no longer offers to
            # open the downloads page, so this is always false.
            "downloads_page_opened": False,
            "llm_response_guidance": {
                "format": f"**[Download {doc_description} ({page_count} pages)]({final_url})** | Raw URL: `{final_url}`",
                "critical": "Provide clickable markdown link for browser access AND raw URL for clients like Msty where links aren't clickable",
                "example": f"**[Download {doc_description} ({page_count} pages)]({final_url})** | Raw URL: `{final_url}`"
            }
        }

        return json.dumps(response, indent=_JSON_INDENT)

    except ValueError as e:
        # Error class and tool only, never the rejected value (PT-38).
        logger.warning("Validation rejected in PTAB_get_document_download: %s", type(e).__name__)
        return format_error_response(str(e), "VALIDATION_ERROR")
    except RuntimeError as e:
        # Re-raises anything that is not an interpreter shutdown.
        return async_lifecycle_envelope(e, "PTAB_get_document_download")
    except Exception as e:
        logger.error(f"Error in PTAB_get_document_download: {str(e)}")
        return format_error_response(str(e), "API_ERROR")



# =============================================================================
# EXTRACTION TIERS (pypdf -> Mistral OCR -> Docling) — metrics §1.3
# =============================================================================
# Each tier is a standalone helper walked by PTAB_get_document_content, so the
# tool body is orchestration only. Behavior (logging, thresholds, fallbacks)
# is unchanged from the previous inline implementation.

def _coerce_page_count(raw_page_count) -> Optional[int]:
    """Page count from USPTO document metadata, or None when it is missing.

    This used to DEFAULT a missing/unparseable pageCount to 50, which made the
    OCR tier's `truncated = page_count > max_pages` read `50 > 50` — false. A
    300-page exhibit therefore came back as 50 OCR'd pages labelled
    `page_count: 50` with `truncated: false`, indistinguishable from a
    complete 50-page document. Unknown is now reported as unknown (None) and
    the real count is recovered from the PDF bytes by _resolve_page_count().
    """
    if isinstance(raw_page_count, bool):
        return None
    if isinstance(raw_page_count, int):
        return raw_page_count if raw_page_count > 0 else None
    if isinstance(raw_page_count, str):
        try:
            value = int(raw_page_count.strip())
        except (ValueError, AttributeError):
            return None
        return value if value > 0 else None
    return None


def _pdf_page_count(pdf_bytes: bytes) -> Optional[int]:
    """Best-effort local page count from the already-downloaded PDF bytes.
    Returns None when the bytes can't be parsed (encrypted/damaged/mocked)."""
    try:
        import io

        import pypdf

        return len(pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception as e:
        logger.debug(f"Local page count unavailable ({type(e).__name__})")
        return None


def _resolve_page_count(raw_page_count, pdf_bytes: bytes) -> tuple:
    """(page_count_or_None, source) for one document.

    USPTO document metadata omits pageCount often enough that trusting it
    blindly was the single most misleading behavior in this tool. Order:
    the API's own value, then a local count from the PDF bytes we already
    downloaded, then honestly unknown. `source` is one of
    "metadata" | "pdf_bytes" | "unknown" and is surfaced to the caller.
    """
    resolved = _coerce_page_count(raw_page_count)
    if resolved is not None:
        return resolved, "metadata"
    resolved = _pdf_page_count(pdf_bytes)
    if resolved is not None:
        return resolved, "pdf_bytes"
    return None, "unknown"


#: Free (pypdf) tier page cap. Named to match the paid tier's
#: MISTRAL_OCR_MAX_PAGES so one convention covers every extraction tier
#: (Docling already has DOCLING_MAX_PAGES). Before this, the free tier was the
#: only one with no upper bound at all: a 300-page exhibit ran extract_text()
#: on all 300 pages.
_DEFAULT_PYPDF_MAX_PAGES = 200


def pypdf_max_pages() -> int:
    """PYPDF_MAX_PAGES — per-document free-tier page cap (default 200)."""
    try:
        return max(1, int(os.getenv("PYPDF_MAX_PAGES", str(_DEFAULT_PYPDF_MAX_PAGES))))
    except (TypeError, ValueError):
        logger.warning("Invalid PYPDF_MAX_PAGES; using default 200")
        return _DEFAULT_PYPDF_MAX_PAGES


def _try_pypdf2_extraction(
    pdf_bytes: bytes, status: Optional[Dict[str, Any]] = None
) -> str:
    """Free text-layer extraction, capped at PYPDF_MAX_PAGES.

    Returns "" when the text layer is missing or too thin (<100 chars of real
    text), which signals the caller to escalate to OCR. Whatever WAS extracted
    is preserved in `status["partial_text"]` either way: a sub-100-char result
    used to be discarded outright, so when OCR then also failed the response
    reported `text: ""` and never mentioned that partial text had existed.

    Every page gets an `=== PAGE N ===` header (same format as the Mistral
    tier) so the text-window helper can serve page-unit windows, and a page
    that yields no text keeps its header instead of vanishing.
    """
    status = status if status is not None else {}
    text_parts: list = []
    body_chars = 0
    pages_extracted = 0
    try:
        import io

        import pypdf

        pdf_reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        total_pages = len(pdf_reader.pages)
        cap = pypdf_max_pages()
        truncated = total_pages > cap
        pages_to_extract = pdf_reader.pages[:cap] if truncated else pdf_reader.pages

        for index, page in enumerate(pages_to_extract, start=1):
            page_text = page.extract_text() or ""
            body_chars += len(page_text.strip())
            pages_extracted += 1
            if page_text.strip():
                text_parts.append(f"=== PAGE {index} ===\n{page_text}")
            else:
                text_parts.append(
                    f"=== PAGE {index} ===\n[no text recovered from this page]"
                )

        status["pages_extracted"] = pages_extracted
        status["page_count"] = total_pages
        if truncated:
            status["truncated"] = True
            status["truncation_note"] = (
                f"Document has {total_pages} pages; the free pypdf tier extracted "
                f"the first {cap} (PYPDF_MAX_PAGES limit). The text is incomplete."
            )
    except Exception as e:
        logger.warning(
            f"pypdf extraction failed after {pages_extracted} page(s): {type(e).__name__}"
        )
        status["pages_extracted"] = pages_extracted
        status["extraction_error"] = (
            f"pypdf extraction aborted after {pages_extracted} page(s) "
            f"({type(e).__name__}); any text recovered is partial."
        )

    extracted_text = "\n\n".join(text_parts)
    # Keep whatever was recovered so an all-tiers-failed response can report
    # it instead of pretending nothing was extracted.
    status["partial_text"] = extracted_text
    status["body_chars"] = body_chars

    if body_chars >= 100 and not status.get("extraction_error"):
        logger.info(f"pypdf extraction successful: {len(extracted_text)} chars")
        return extracted_text
    logger.warning(f"pypdf extraction yielded only {body_chars} chars of text")
    return ""


#: OCR failures that say nothing about the provider's health: a missing key,
#: a rejected key, an exhausted account, or OUR OWN per-caller throttle. They
#: are permanent or self-inflicted, so counting them would open the breaker
#: with no outage in sight.
_OCR_BREAKER_EXEMPT_ERRORS = frozenset({
    "MISTRAL_API_KEY not configured",
    "Rate limit exceeded",
    "Authentication failed",
    "Payment required",
})


class _OCRProviderUnavailable(Exception):
    """Marks an OCR failure as a provider outage so the circuit breaker counts
    it. Carries the original result so the caller returns it unchanged."""

    def __init__(self, result: dict):
        self.result = result
        super().__init__(str(result.get("error", "OCR failed")))


async def _try_mistral_extraction(
    pdf_bytes: bytes, page_count: Optional[int], identifier: str, document_id: str,
    progress_cb
) -> dict:
    """Mistral OCR tier — returns the raw ocr_result dict (success or not).

    Bulkhead (RF-6): acquires the client's Mistral concurrency semaphore so
    the declared limit actually holds. Throttled per identity (M-4).

    Runs through the client's OCR circuit breaker, which was constructed and
    reported on the health route but never actually invoked: the OCR service
    returns an error ENVELOPE rather than raising, so nothing ever reached
    the breaker and it could not open. Outage-shaped failures are re-raised
    here so the breaker counts them.
    """
    client = _client()
    breaker = client.mistral_circuit_breaker

    async def _extract() -> dict:
        async with client.mistral_semaphore:
            result = await ocr_service.extract_document_content(
                pdf_content=pdf_bytes,
                page_count=page_count,
                identifier=identifier,
                document_id=document_id,
                progress_cb=progress_cb,
                caller_id=get_authenticated_identity() or "local-process"
            )
        if (not result.get("success")
                and result.get("error") not in _OCR_BREAKER_EXEMPT_ERRORS):
            raise _OCRProviderUnavailable(result)
        return result

    try:
        return await breaker.call(_extract)
    except _OCRProviderUnavailable as e:
        return e.result
    except CircuitBreakerOpenError:
        logger.warning("OCR circuit OPEN - skipping the OCR tier")
        return {
            "success": False,
            "error": "OCR temporarily unavailable",
            "message": (
                "The OCR extraction service is temporarily unavailable after "
                "repeated failures. Try again shortly."
            ),
        }


async def _try_docling_extraction(
    pdf_bytes: bytes, page_count: Optional[int], document_id: str, progress_cb
) -> str:
    """Docling tier (self-hosted, free) — short docs only. Returns "" when
    unavailable, page-gated, or failed.

    Page gate (Lesson 19): EasyOCR takes ~10-30s/page; anything over
    DOCLING_MAX_PAGES would blow the MCP tool call timeout.
    """
    if not docling_client.is_available():
        return ""
    if page_count is None:
        # Page count unresolvable (metadata missing AND the PDF bytes would
        # not parse). Skipping is the conservative read: EasyOCR at
        # ~10-30s/page blows the tool-call timeout on anything large, and an
        # unknown-length document cannot be shown to be small.
        logger.info(
            "Skipping Docling: page count unknown, cannot verify it is within "
            f"DOCLING_MAX_PAGES={docling_client.max_pages}"
        )
        return ""
    if not docling_client.within_page_limit(page_count):
        logger.info(
            f"Skipping Docling: {page_count} pages exceeds "
            f"DOCLING_MAX_PAGES={docling_client.max_pages} — use Mistral for large docs"
        )
        return ""
    await progress_cb(
        75, 100,
        f"Mistral unavailable — trying Docling OCR ({page_count} pages, "
        f"may take {page_count * 15}s)..."
    )
    try:
        extracted_text = await docling_client.extract(
            pdf_bytes, filename=f"{document_id}.pdf"
        )
        logger.info(f"Docling extraction successful: {len(extracted_text)} chars")
        return extracted_text
    except Exception as docling_error:
        logger.warning(f"Docling extraction failed: {docling_error}")
        return ""



def _mark_page_cap(
    extra: Dict[str, Any],
    text: str,
    pages_processed: Optional[int],
    total_pages: Optional[int],
    note: str,
) -> None:
    """Attach the shared `_bounds` marker for a PAGE cap.

    Pages that were never extracted are not text this server holds, so the
    contract is `_bounds` with reason "window" — `_window`'s counters are
    contractually CHARACTERS of text actually in hand. `items_returned` /
    `items_total` count PAGES here; `items_total` is null when the document's
    true page count could not be determined.
    """
    extra["truncated"] = True
    extra["truncation_note"] = note
    extra[response_bounds.BOUNDS_KEY] = {
        "applied": True,
        "reason": response_bounds.REASON_WINDOW,
        "size_chars": len(text or ""),
        "size_limit": response_bounds.content_char_budget(),
        "stages": [response_bounds.STAGE_TRUNCATED],
        "slimmed_fields": [],
        "items_returned": pages_processed,
        "items_total": total_pages,
        "note": note,
    }


async def _run_extraction_tiers(
    pdf_bytes: bytes, page_count: Optional[int], identifier: str, document_id: str,
    use_ocr: bool, progress_cb, pypdf_status: Optional[Dict[str, Any]] = None,
) -> tuple:
    """Walk the pypdf -> Mistral -> Docling waterfall.

    Returns (text, method, cost, extra); empty text means every tier failed
    and the caller should return _all_tiers_failed_response(). `extra` carries
    the metadata the caller surfaces to the client (page truncation markers,
    pages_processed). `pypdf_status` is an out-dict recording what the free
    tier managed before it gave up, so a total failure can still report the
    partial text instead of an empty string.
    """
    extracted_text = ""
    extraction_method = "pypdf2"
    ocr_cost_usd = 0.00
    extra: Dict[str, Any] = {}
    pypdf_status = pypdf_status if pypdf_status is not None else {}

    if not use_ocr:
        await progress_cb(40, 100, "Extracting text with pypdf...")
        extracted_text = _try_pypdf2_extraction(pdf_bytes, pypdf_status)
        if extracted_text:
            extra["pages_extracted"] = pypdf_status.get("pages_extracted")
            if pypdf_status.get("page_count"):
                extra["page_count"] = pypdf_status["page_count"]
            if pypdf_status.get("truncated"):
                _mark_page_cap(
                    extra,
                    extracted_text,
                    pypdf_status.get("pages_extracted"),
                    pypdf_status.get("page_count"),
                    pypdf_status["truncation_note"],
                )

    if not extracted_text or use_ocr:
        extraction_method = "mistral_ocr"
        ocr_result = await _try_mistral_extraction(
            pdf_bytes, page_count, identifier, document_id, progress_cb
        )

        if ocr_result.get("success"):
            extracted_text = ocr_result.get("extracted_content", "")
            ocr_cost_usd = ocr_result.get("processing_cost_usd", 0.0)
            # Surface OCR truncation + page accounting (SD-6) so the caller
            # knows when only the first MISTRAL_OCR_MAX_PAGES were processed
            for key in ("truncated", "truncation_note", "pages_processed"):
                if ocr_result.get(key) is not None:
                    extra[key] = ocr_result[key]
            if ocr_result.get("truncated"):
                # Same page-cap vocabulary as the free tier: `_bounds` with
                # reason "window", counting PAGES, items_total null when the
                # document's real length is unknown.
                _mark_page_cap(
                    extra,
                    extracted_text,
                    ocr_result.get("pages_requested") or ocr_result.get("pages_processed"),
                    ocr_result.get("page_count"),
                    ocr_result.get("truncation_note", ""),
                )
            logger.info(f"Mistral OCR extraction successful: {len(extracted_text)} chars, "
                       f"${ocr_cost_usd:.4f} cost")
        else:
            logger.error(f"Mistral OCR extraction failed: {ocr_result.get('message', 'Unknown OCR error')}")
            ocr_cost_usd = 0.00
            # The reason used to reach the log and stop there, so an OCR
            # outage, an expired key and a billing lapse all came back to the
            # caller as "this document is a scanned image" — a confident wrong
            # diagnosis. An agent handles "the exhibit is a scan, configure
            # OCR" and "OCR is down, retry in a minute" in opposite ways.
            extra.setdefault("tier_failures", []).append({
                "tier": "mistral_ocr",
                "error": ocr_result.get("error"),
                "message": ocr_result.get("message"),
            })

            extracted_text = await _try_docling_extraction(
                pdf_bytes, page_count, document_id, progress_cb
            )
            extraction_method = "docling" if extracted_text else extraction_method

    return extracted_text, extraction_method, ocr_cost_usd, extra


def _all_tiers_failed_response(
    document_id: str, identifier: str,
    pypdf_status: Optional[Dict[str, Any]] = None,
    tier_failures: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Enhanced error with LLM guidance when every extraction tier fails.

    The pypdf tier discards its output below 100 characters of real text, so
    when OCR then also failed this response used to report `text: ""` and
    never mention that partial text had been recovered at all. Whatever the
    free tier managed is now returned, marked as partial.
    """
    pypdf_status = pypdf_status or {}
    partial_text = pypdf_status.get("partial_text") or ""
    body_chars = pypdf_status.get("body_chars") or 0
    response: Dict[str, Any] = {
        "document_id": document_id,
        "identifier": identifier,
        "text": partial_text,
        "extraction_method": "pypdf (insufficient)",
        "error": "Document appears to be scanned/image-based. pypdf could not extract meaningful text.",
        "mistral_api_key_missing": not ocr_service.mistral_api_key,
        "docling_configured": docling_client.is_available(),
        "llm_guidance": {
            "explain_to_user": "Many USPTO PTAB documents are scanned images rather than text-based PDFs. "
                              "pypdf can only extract text from text-based PDFs - it cannot read scanned images.",
            "recommended_solution": "Configure Mistral API for OCR capability (sign up at https://console.mistral.ai/)",
            "setup_instructions": "Set MISTRAL_API_KEY environment variable after obtaining key from Mistral console",
            "docling_alternative": "For short documents (<= 20 pages), a self-hosted docling-serve instance "
                                   "can perform OCR - set DOCLING_SERVE_URL to enable"
        }
    }
    if partial_text:
        response["partial_text"] = True
        response["character_count"] = len(partial_text)
        response["pages_extracted"] = pypdf_status.get("pages_extracted")
        response["extraction_note"] = (
            f"Every extraction tier failed, but pypdf did recover {body_chars} "
            f"character(s) of text across {pypdf_status.get('pages_extracted')} "
            "page(s) — below the 100-character usability threshold that triggers "
            "the OCR escalation. It is returned above as `text` so nothing is "
            "silently discarded; treat it as PARTIAL and unreliable."
        )
    if pypdf_status.get("extraction_error"):
        response["extraction_error"] = pypdf_status["extraction_error"]
    if tier_failures:
        # An OCR tier reported WHY it failed. Say so instead of asserting a
        # property of the document, and correct the top-level error text —
        # "configure a Mistral API key" is wrong advice when the key is fine
        # and the service is down.
        response["tier_failures"] = tier_failures
        response["error"] = (
            "Text extraction failed. This may be a scanned document, or an OCR "
            "tier may be unavailable — see tier_failures for what each tier "
            "reported."
        )
    return json.dumps(response, indent=_JSON_INDENT)


def _build_content_response(
    *,
    document_id: str,
    identifier: str,
    identifier_type: str,
    matching_doc: Dict[str, Any],
    extracted_text: str,
    extraction_method: str,
    page_count: Optional[int],
    page_count_source: str,
    extra: Dict[str, Any],
    char_offset: int,
    max_chars: Optional[int],
) -> Dict[str, Any]:
    """Assemble the PTAB_get_document_content payload: metadata, provenance,
    the injection scan, and the text window. Extracted from the tool body as a
    mechanical decomposition (no behavior change) to keep the orchestration
    function under the repo's cyclomatic-complexity gate."""
    response: Dict[str, Any] = {
        "document_id": document_id,
        "identifier": identifier,
        "identifier_type": identifier_type,
        "text": extracted_text,
        "extraction_method": extraction_method,
        "character_count": len(extracted_text),
        "page_count": page_count,
        "page_count_source": page_count_source,
        "document_description": matching_doc.get("documentDescription", ""),
        "filing_date": matching_doc.get("filingDate", ""),
        # Retrieved-text posture: extracted text is quoted document data,
        # never instructions (see shared/injection_scan.py and
        # docs/CONTENT_PROVENANCE.md).
        "provenance_note": RETRIEVED_TEXT_NOTE,
        # Page-truncation metadata (SD-6) — present only when a tier capped
        # the document (PYPDF_MAX_PAGES / MISTRAL_OCR_MAX_PAGES); absent for
        # complete extractions.
        **extra,
    }
    if page_count is None:
        response["page_count_note"] = (
            "The document's page count could not be determined: USPTO metadata "
            "carried none and the PDF bytes would not parse. It is reported as "
            "null rather than guessed, so any page-cap accounting below counts "
            "pages processed against an unknown total."
        )

    # Detection-only injection scan of the extracted text: annotate (kind
    # labels keyed by document_id — never matched text), key ABSENT when
    # clean. The text itself is returned verbatim above.
    injection = scan_hits([response], text_keys=("text",), id_key="document_id")
    if injection:
        response["injection_scan"] = injection

    # Window the extracted text rather than letting an oversized payload be
    # replaced client-side by an unrecoverable truncation error. Nothing is
    # dropped: `_window.next_offset` feeds straight back into char_offset.
    # Snaps to `=== PAGE N ===` boundaries when the text carries them.
    response = apply_text_window(
        response,
        "text",
        offset=max(0, int(char_offset or 0)),
        max_chars=max_chars,
        note=_CONTENT_WINDOW_NOTE,
    )
    if response_bounds.WINDOW_KEY in response:
        response["character_count"] = len(response["text"])
    return response


async def ptab_get_document_content(
    document_id: str,
    identifier: str,
    identifier_type: str = "trial",
    use_ocr: bool = False,
    char_offset: int = 0,
    max_chars: Optional[int] = None,
    ctx: Context = None
) -> str:
    """Extract text content from PTAB documents for LLM analysis (hybrid pypdf + Mistral OCR + Docling).
    Read, extract, text, contents, full document, OCR, quote a petition, brief, exhibit, order, or decision.

    PREREQUISITE: First use PTAB_get_documents to get document_identifier.

    BASIC USAGE:
    - Core Purpose: Extract text from PDFs for LLM analysis and question answering
    - Extraction Strategy: Try pypdf first (fastest), then Mistral OCR (handles
      scanned documents), then Docling OCR (self-hosted) for short documents
    - Tier Ordering: pypdf always attempted first (fastest); OCR is reserved
      for scanned/image-based documents where the text layer is missing
    - Typical Use: Answer questions about Board decisions, analyze reasoning
    - Docling gate: only documents <= DOCLING_MAX_PAGES (default 20) go to
      Docling — PTAB petitions (60p), responses (80p) and exhibits (100-300p)
      are too slow for EasyOCR and should use Mistral instead

    WHEN TO USE THIS TOOL:
    - LLM Analysis: When LLM needs to answer questions about document content
    - Text Extraction: For semantic search, RAG, or text mining workflows
    - Decision Analysis: Understanding Board's claim construction or reasoning
    - Selective Extraction: Only for 1-3 critical documents (keeps context manageable)

    HYBRID EXTRACTION STRATEGY:

    Step 1: Download PDF from USPTO
    Step 2: Try pypdf text extraction (fast)
    Step 3: If < 100 chars, use Mistral OCR (slower, handles scanned documents)
    Step 4: If Mistral unavailable/fails and document <= DOCLING_MAX_PAGES,
            use Docling OCR (self-hosted docling-serve, slower)
    Step 5: Return extracted text with metadata

    Docling env vars: DOCLING_SERVE_URL (enables the tier), DOCLING_TIMEOUT
    (default 300s), DOCLING_MAX_PAGES (default 20).

    EXTRACTION WORKFLOW:

    User needs document → LLM will analyze?
      YES → How many documents?
            - 1-3 documents: PTAB_get_document_content
            - 5+ documents: Use PTAB_get_document_download instead
                            → User reviews and selects 1-3 for extraction

      NO → PTAB_get_document_download (user downloads directly)

    RELATED TOOLS:
    - Alternative: PTAB_get_document_download (user download, no extraction step)
    - Previous Step: PTAB_get_documents (get document list first)
    - Cross-MCP: PFW_get_document_content (prosecution history text extraction)

    GUIDANCE REFERENCES:
    - For context optimization strategies: PTAB_get_guidance(section='cost')
    - For download vs extract decision tree: PTAB_get_guidance(section='documents')

    PAGING LONG DOCUMENTS (char_offset / max_chars):
      Extracted text is WINDOWED, never silently dropped. When a document is
      longer than the content budget the response carries a `_window` block:
        {"unit": "char", "edges": "page", "offset": 0, "returned": 120000,
         "total": 310000, "has_more": true, "next_offset": 120000}
      Feed `_window.next_offset` straight back as char_offset to continue:
        PTAB_get_document_content(identifier='IPR2024-01353',
                                  document_id='171303338', char_offset=120000)
      All four counters are CHARACTER offsets, which is what `unit` reports —
      it always reads "char". `edges` is the separate question of whether the
      window boundaries snapped to `=== PAGE N ===` markers ("page") or are a
      raw character slice ("char"). Both extraction tiers emit page markers,
      so windows normally land on whole page boundaries.

    PAGE COUNTS AND CAPS:
      `page_count` is the document's real page count when it is knowable —
      taken from USPTO metadata, else counted locally from the PDF bytes. When
      neither works it is null with `page_count_source: "unknown"`; it is
      never guessed. If an extraction tier processed only part of the document
      (PYPDF_MAX_PAGES / MISTRAL_OCR_MAX_PAGES), `truncated`, `truncation_note`
      and a `_bounds` block (reason "window", counting PAGES) say so.

    Args:
        document_id: Document identifier from PTAB_get_documents()
        identifier: Trial/appeal/interference number
        identifier_type: Type of proceeding - "trial" (default), "appeal", or "interference"
        use_ocr: Force Mistral OCR even if pypdf succeeds (for better quality)
        char_offset: Character offset to start the text window at (default 0).
                     Pass `_window.next_offset` from a previous call to continue.
        max_chars: Maximum characters of text to return in this window
                   (default: the server's USPTO_MAX_CONTENT_CHARS budget).

    Returns:
        JSON string with extracted text, method used, and metadata

    Example Response:
        {
            "text": "UNITED STATES PATENT AND TRADEMARK OFFICE...",
            "extraction_method": "pypdf2",
            "character_count": 25000,
            "page_count": 45,
            "note": "pypdf extraction successful (text layer present)"
        }

    Example Response (OCR used):
        {
            "text": "UNITED STATES PATENT AND TRADEMARK OFFICE...",
            "extraction_method": "mistral_ocr",
            "character_count": 25000,
            "page_count": 45,
            "note": "Mistral OCR used (pypdf failed for scanned PDF)"
        }
    """
    try:
        _progress = _make_progress_cb(ctx)

        api_client = _client()

        identifier_type, adapter, identifier, document_id = (
            _validate_document_request(identifier, identifier_type, document_id)
        )

        # Resolve the paper's index entry (targeted lookup -> docket walk ->
        # ptab-files URI fallback); same ordering as the download tool, so the
        # two agree on what a document's metadata is.
        matching_doc, docs_response = await _resolve_indexed_document(
            api_client, adapter, identifier, identifier_type, document_id,
        )

        if not matching_doc:
            raise ValueError(_not_found_message(document_id, identifier, docs_response))

        # Extract download URL
        download_url = matching_doc.get("fileDownloadURI")

        if not download_url:
            raise ValueError(f"No download URI found for document {document_id}")

        await _progress(25, 100, f"Downloading PDF for {identifier} document {document_id}...")

        # Download PDF via the adapter
        pdf_bytes = await adapter.download_document(api_client, download_url)

        # Real page count or an honest null — never the old default of 50,
        # which made `truncated = 50 > 50` false and disguised a capped
        # 300-page exhibit as a complete 50-page document.
        page_count, page_count_source = _resolve_page_count(
            matching_doc.get("pageCount"), pdf_bytes
        )

        # Walk the extraction waterfall (pypdf -> Mistral -> Docling).
        # The cost figure stays server-side (logged in _run_extraction_tiers)
        # and is never surfaced in the tool response.
        pypdf_status: Dict[str, Any] = {}
        extracted_text, extraction_method, _ocr_cost_usd, ocr_extra = await _run_extraction_tiers(
            pdf_bytes, page_count, identifier, document_id, use_ocr, _progress,
            pypdf_status,
        )
        if not extracted_text:
            return _all_tiers_failed_response(
                document_id, identifier, pypdf_status,
                tier_failures=ocr_extra.get("tier_failures"),
            )

        await _progress(100, 100, f"Extraction complete ({extraction_method}, {len(extracted_text)} chars)")

        return json.dumps(
            _build_content_response(
                document_id=document_id,
                identifier=identifier,
                identifier_type=identifier_type,
                matching_doc=matching_doc,
                extracted_text=extracted_text,
                extraction_method=extraction_method,
                page_count=page_count,
                page_count_source=page_count_source,
                extra=ocr_extra,
                char_offset=char_offset,
                max_chars=max_chars,
            ),
            indent=_JSON_INDENT,
        )

    except ValueError as e:
        # Error class and tool only, never the rejected value (PT-38).
        logger.warning("Validation rejected in PTAB_get_document_content: %s", type(e).__name__)
        return format_error_response(str(e), "VALIDATION_ERROR")
    except RuntimeError as e:
        # Re-raises anything that is not an interpreter shutdown.
        return async_lifecycle_envelope(e, "PTAB_get_document_content")
    except Exception as e:
        logger.error(f"Error in PTAB_get_document_content: {str(e)}")
        return format_error_response(str(e), "API_ERROR")


def _get_ptab_proxy_base_url(port: int) -> str:
    """
    Externally reachable base URL of the PTAB download proxy.

    Every layer that emits a download URL must honor PTAB_PROXY_BASE_URL
    (Lesson 31) so links work behind Docker / reverse proxies.
    """
    return (os.getenv("PTAB_PROXY_BASE_URL", "").strip().rstrip("/")
            or f"http://localhost:{port}")


async def _register_download_via_proxy(payload: dict) -> Optional[str]:
    """
    Register a generated download with the proxy's recent-downloads registry.

    Best effort — download links work even if registration fails. Uses the
    proxy token imported from the proxy module (Lesson 40: never regenerate
    it in the caller; the proxy runs in this same process). Registration goes
    over HTTP so it also works when the proxy runs in a separate process
    with a shared PROXY_TOKEN (Lesson 25).

    Returns:
        The registry download_id, or None if registration failed.
    """
    try:
        import httpx
        from ..proxy.server import _get_proxy_token

        local_port = get_local_proxy_port()
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.post(
                f"http://localhost:{local_port}/api/register-download",
                json=payload,
                headers={"X-Proxy-Token": _get_proxy_token()},
            )
            resp.raise_for_status()
            return resp.json().get("download_id")
    except Exception as e:
        # Warning, not debug: a missing PROXY_TOKEN degrades to a per-process
        # random value that can never match (correct — it fails closed), and at
        # debug level that misconfiguration was completely invisible. The
        # downloads panel just silently stayed empty (PT-33/PT-37).
        logger.warning(
            "Recent-downloads registration failed: %s "
            "(is PROXY_TOKEN set consistently across processes?)",
            type(e).__name__,
        )
        return None


def register(mcp) -> None:
    """Register the three document tools (schemas unchanged; PTAB_ display names)."""
    mcp.tool(name="PTAB_get_documents",
             annotations={"defer_loading": False, "readOnlyHint": True})(ptab_get_documents)
    mcp.tool(name="PTAB_get_document_download", app=AppConfig(resource_uri=DOWNLOADS_URI),
             annotations={"defer_loading": True, "readOnlyHint": True})(ptab_get_document_download)
    mcp.tool(name="PTAB_get_document_content",
             annotations={"defer_loading": True, "readOnlyHint": True})(ptab_get_document_content)
