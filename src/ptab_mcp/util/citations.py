"""PTAB row -> `cite_as` markdown links.

The mechanism (number normalization, the two verified URL forms, the
delivery-link refusal, `CITATION_NOTE`) lives in `shared/citations.py`, which
is vendored byte-identical into the sibling USPTO MCPs. THIS module holds the
PTAB-specific half: which bag on a trial / appeal / interference record
carries the patent number and the application serial, and how a proceeding is
labelled.

WHAT THE TARGET IS, PER PROCEEDING TYPE
---------------------------------------
- Trials (IPR/PGR/CBM): the Google Patents page for the CHALLENGED patent
  (`patentOwnerData.patentNumber`). There is no verified public per-proceeding
  URL, because P-TACTS is a JavaScript application whose deep-link shape is
  unknown and a guessed URL is worse than none, so the patent it attacks
  is the record a reader can actually open. When the record carries no patent
  number the fall-back is Patent Center on the application serial.
- Appeals: Patent Center on the application (`appellantData
  .applicationNumberText`). An ex parte appeal is about an application, and
  most appeal records carry no patent number at all. A reexam appeal that does
  carry one falls back to Google Patents when the serial is missing.
- Interferences: the senior party's patent, then the junior party's, then
  either party's application. An interference record puts the numbers on the
  party bags, never on interferenceMetaData.

A record carrying neither a usable patent number nor a usable serial gets NO
`cite_as` key. That is deliberate: an absent citation is honest, a fabricated
link is not.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..shared.citations import (
    CITATION_NOTE,
    cite_as_link,
    format_application_display,
    format_patent_display,
    google_patents_url,
    patent_center_url,
)

__all__ = [
    "CITATION_NOTE",
    "CITE_AS_KEY",
    "attach_search_cite_as",
    "documents_cite_as",
    "proceeding_cite_as",
]

#: The per-row key. Named once so the response-bounds whitelists, the tests
#: and the attach points cannot drift apart.
CITE_AS_KEY = "cite_as"

#: Proceeding types whose record is an APPLICATION matter first: cite Patent
#: Center before Google Patents.
_APPLICATION_FIRST = frozenset({"appeals", "appeal"})

#: PTAB_get_documents' identifier_type -> the search-tool proceeding name.
_KIND_BY_IDENTIFIER_TYPE = {
    "trial": "trials",
    "appeal": "appeals",
    "interference": "interferences",
}


def _first(*values: Any) -> Optional[Any]:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _bag(record: Dict[str, Any], name: str) -> Dict[str, Any]:
    value = record.get(name)
    return value if isinstance(value, dict) else {}


def _trial_parts(record: Dict[str, Any]) -> Tuple[Any, Any, Any]:
    # respondentData does not exist on a live trial record; it is kept as a
    # fallback for the same reason api/proceedings.py keeps it, so this
    # self-heals if USPTO ever populates it.
    owner = _bag(record, "patentOwnerData")
    legacy = _bag(record, "respondentData")
    return (
        record.get("trialNumber"),
        _first(owner.get("patentNumber"), legacy.get("patentNumber")),
        _first(
            owner.get("applicationNumberText"), legacy.get("applicationNumber")
        ),
    )


def _appeal_parts(record: Dict[str, Any]) -> Tuple[Any, Any, Any]:
    appellant = _bag(record, "appellantData")
    legacy = _bag(record, "decisionMetaData")
    return (
        record.get("appealNumber"),
        _first(appellant.get("patentNumber"), legacy.get("patentNumber")),
        _first(
            appellant.get("applicationNumberText"),
            legacy.get("applicationNumber"),
        ),
    )


def _interference_parts(record: Dict[str, Any]) -> Tuple[Any, Any, Any]:
    senior = _bag(record, "seniorPartyData")
    junior = _bag(record, "juniorPartyData")
    meta = _bag(record, "interferenceMetaData")
    return (
        record.get("interferenceNumber"),
        _first(
            senior.get("patentNumber"),
            junior.get("patentNumber"),
            meta.get("patentNumber"),
        ),
        _first(
            senior.get("applicationNumberText"),
            junior.get("applicationNumberText"),
            meta.get("applicationNumber"),
        ),
    )


_PARTS_BY_KIND = {
    "trials": _trial_parts,
    "appeals": _appeal_parts,
    "interferences": _interference_parts,
}

#: What to call a proceeding whose own identifier did not survive a caller's
#: field projection.
_FALLBACK_LABEL = {
    "trials": "PTAB trial",
    "appeals": "PTAB appeal",
    "interferences": "PTAB interference",
}


def proceeding_cite_as(
    kind: str,
    number: Any,
    patent_number: Any = None,
    application_number: Any = None,
) -> Optional[str]:
    """The markdown `cite_as` for one proceeding, or None when nothing is
    citable.

    `kind` is "trials" | "appeals" | "interferences". The label always leads
    with the proceeding number and then names whatever the link actually
    opens, so a reader can see before clicking whether they are being sent to
    the patent or to the application.
    """
    patent_url = google_patents_url(patent_number)
    application_url = patent_center_url(application_number)
    if kind in _APPLICATION_FIRST:
        url = application_url or patent_url
    else:
        url = patent_url or application_url
    if not url:
        return None

    label = str(number or "").strip() or _FALLBACK_LABEL.get(kind, "PTAB proceeding")
    if url == patent_url:
        display = format_patent_display(patent_number)
        if display:
            label = f"{label}, {display}"
    else:
        display = format_application_display(application_number)
        if display:
            label = f"{label}, application {display}"
    return cite_as_link(label, url)


def attach_search_cite_as(
    kind: str,
    rows: Any,
    source_rows: Any = None,
) -> Any:
    """Stamp `cite_as` on every row of a proceeding search result, in place.

    `rows` are the rows as the caller will see them (tier- or custom-field
    filtered). `source_rows` are the SAME records before field filtering, when
    the caller has them: a `fields=` projection can drop the patent number the
    link is built from, and the citation must not disappear because the caller
    asked for fewer columns. Falls back to the projected row when the two
    lists do not line up.

    An existing `cite_as` is never overwritten, and a row for which no target
    resolves is left without the key.
    """
    parts = _PARTS_BY_KIND.get(kind)
    if parts is None or not isinstance(rows, list):
        return rows
    sources = (
        source_rows
        if isinstance(source_rows, list) and len(source_rows) == len(rows)
        else None
    )
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get(CITE_AS_KEY) is not None:
            continue
        source = sources[index] if sources else row
        if not isinstance(source, dict):
            source = row
        number, patent, application = parts(source)
        if number in (None, ""):
            number = parts(row)[0]
        link = proceeding_cite_as(kind, number, patent, application)
        if link:
            row[CITE_AS_KEY] = link
    return rows


def documents_cite_as(
    identifier_type: str,
    identifier: Any,
    bag_items: Optional[Sequence[Any]] = None,
) -> Optional[str]:
    """The one proceeding-level `cite_as` every row of a PTAB_get_documents
    envelope carries.

    A document row's own delivery link is NOT a citation (the persistent-link
    hash is a credential), and there is no public per-paper URL, so every
    paper on a docket cites the proceeding's patent or application. The
    numbers are read out of the document bag the tool already fetched (the
    parent item of each document carries the party bag), so this costs no
    extra API call. Returns None when the bag carries neither number.
    """
    kind = _KIND_BY_IDENTIFIER_TYPE.get(identifier_type)
    if kind is None:
        return None
    parts = _PARTS_BY_KIND[kind]
    patent: Any = None
    application: Any = None
    for item in bag_items or ():
        if not isinstance(item, dict):
            continue
        _number, item_patent, item_application = parts(item)
        patent = patent or item_patent
        application = application or item_application
        if patent and application:
            break
    return proceeding_cite_as(kind, identifier, patent, application)


def attach_document_cite_as(
    documents: Any, cite_as: Optional[str]
) -> Any:
    """Stamp one proceeding-level `cite_as` onto every document row."""
    if not cite_as or not isinstance(documents, list):
        return documents
    for row in documents:
        if isinstance(row, dict) and row.get(CITE_AS_KEY) is None:
            row[CITE_AS_KEY] = cite_as
    return documents


def cite_as_list(rows: Any) -> List[str]:
    """Every distinct `cite_as` in a row list, in order. Used by tests."""
    seen: List[str] = []
    for row in rows or ():
        if isinstance(row, dict):
            value = row.get(CITE_AS_KEY)
            if isinstance(value, str) and value not in seen:
                seen.append(value)
    return seen
