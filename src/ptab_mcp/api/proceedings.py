"""Proceeding-type adapters for trials / appeals / interferences.

One data-driven registry (SOLID-2, dup §2.4) replaces the
`if identifier_type == "trial"/elif "appeal"/elif "interference"` chains that
were previously repeated — with drift — across PTAB_get_documents,
PTAB_get_document_download, PTAB_get_document_content, and the proxy's
download route. Adding a proceeding type becomes one new adapter entry
instead of a four-site edit.

Each adapter bundles, for its proceeding type:
- how to validate the identifier,
- how to fetch its document/decision bag (paged and full variants),
- how to flatten the bag into a plain document list (with optional
  parent-data preservation for enhanced-filename generation),
- how to fetch proceeding-level metadata (patent/application/filing date),
- how to download a document's bytes.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config.filter_field_mapping import TrialDocumentFilterFields
from ..validation.validators import (
    validate_appeal_number,
    validate_interference_number,
    validate_trial_number,
)

# Documents like the Petition are sometimes missing from the POST search
# index; for trials the file URI follows a known path pattern.
_TRIAL_ID_PATTERN = re.compile(r'^([A-Z]+)(\d{4})-(\d+)$')
_PTAB_FILES_BASE = "https://api.uspto.gov/api/v1/patent/ptab-files"


@dataclass(frozen=True)
class ProceedingAdapter:
    """Per-proceeding-type behavior bundle."""

    identifier_type: str
    bag_key: str
    validate_identifier: Callable[[str], str]
    # (parent_item) -> metadata merged into every flattened document
    parent_metadata: Callable[[Dict[str, Any]], Dict[str, Any]]
    # (parent_item) -> extra fields preserved only when preserve_parent=True
    # (underscore-prefixed internals for enhanced-filename generation)
    parent_preserved: Callable[[Dict[str, Any]], Dict[str, Any]] = field(
        default=lambda item: {}
    )

    def flatten_documents(
        self, raw_response: Dict[str, Any], preserve_parent: bool = False
    ) -> List[Dict[str, Any]]:
        """Flatten the proceeding's data bag into a plain document list."""
        documents = []
        for item in raw_response.get(self.bag_key, []) or []:
            doc_data = item.get("documentData")
            if not doc_data:
                continue
            flattened = {**doc_data, **self.parent_metadata(item)}
            if preserve_parent:
                flattened.update(self.parent_preserved(item))
            documents.append(flattened)
        return documents

    async def fetch_documents_page(
        self,
        client,
        identifier: str,
        offset: int = 0,
        limit: int = 25,
        sort_order: str = "desc",
        extra_filters: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """One page of documents. Server-side paging for trials only;
        appeals/interferences use the GET decisions endpoint (no paging).

        `extra_filters` are server-side document filters and apply to trials
        only — the appeals/interferences GET endpoints take no filters, so
        they are silently ignored there and the caller keeps filtering
        client-side.
        """
        if self.identifier_type == "trial":
            return await client.search_trial_documents(
                identifier, offset=offset, limit=limit, sort_order=sort_order,
                extra_filters=extra_filters,
            )
        return await self._fetch_decisions(client, identifier)

    async def walk_documents(
        self,
        client,
        identifier: str,
        sort_order: str = "desc",
        extra_filters: Optional[List[Dict[str, Any]]] = None,
        max_docs: int = 1000,
        page_size: int = 100,
    ) -> Tuple[Dict[str, Any], int]:
        """EVERY page of documents, not just the first.

        Returns (response, pages_fetched). The response mirrors
        fetch_documents_page's shape with the merged bag, plus
        `docket_truncated` markers when `max_docs` cut the walk short — a
        client-side filter applied to a truncated walk is reporting on part
        of a docket, and that has to be visible rather than inferred.

        Appeals and interferences are one non-paginating GET, so their walk
        is a single call and pages_fetched is 1.
        """
        if self.identifier_type != "trial":
            return await self._fetch_decisions(client, identifier), 1

        first = await client.search_trial_documents(
            identifier, offset=0, limit=page_size, sort_order=sort_order,
            extra_filters=extra_filters,
        )
        if first.get("error"):
            return first, 1
        bag = first.get(self.bag_key) or []
        total = first.get("count")
        pages = 1
        offset = len(bag)
        ceiling = min(total, max_docs) if isinstance(total, int) else max_docs
        page_error = None
        while bag and offset < ceiling:
            page = await client.search_trial_documents(
                identifier, offset=offset, limit=page_size,
                sort_order=sort_order, extra_filters=extra_filters,
            )
            if page.get("error"):
                # An upstream failure mid-walk is a PARTIAL read. It used to
                # fall through to the note below, which blames the safety cap
                # for what was really an outage.
                page_error = page.get("error")
                break
            page_bag = page.get(self.bag_key) or []
            pages += 1
            if not page_bag:
                break
            bag.extend(page_bag)
            offset += len(page_bag)
        first[self.bag_key] = bag
        short = isinstance(total, int) and total > len(bag)
        if page_error and short:
            first["docket_partial"] = True
            first["docket_partial_at"] = len(bag)
            first["docket_total"] = total
            first["docket_partial_note"] = (
                f"page_all stopped after {len(bag)} of {total} documents because "
                "a later page failed upstream. Any filter below was applied to "
                "those documents only; the rest of the docket was never read. "
                "Retry shortly."
            )
        elif short:
            first["docket_truncated"] = True
            first["docket_truncated_at"] = len(bag)
            first["docket_total"] = total
            first["docket_truncation_note"] = (
                f"page_all stopped at the {max_docs}-document safety cap after "
                f"{len(bag)} of {total} documents. Any filter below was applied "
                "to those documents only; a later paper is NOT in this set and "
                "its absence here is not evidence it does not exist."
            )
        return first, pages

    async def fetch_all_documents(self, client, identifier: str) -> Dict[str, Any]:
        """Full document set (paginating past the trial API's 100-row cap)."""
        if self.identifier_type == "trial":
            return await client.search_all_trial_documents(identifier)
        return await self._fetch_decisions(client, identifier)

    async def fetch_document_by_id(
        self, client, identifier: str, document_id: str
    ) -> Optional[Dict[str, Any]]:
        """One paper's index entry, fetched by its own identifier.

        Trials only: trials/documents/search takes
        documentData.documentIdentifier as a server-side filter (verified live
        2026-09-03 — IPR2024-01353/171303338 and IPR2023-01035/170603095 each
        return count 1, with the same parent bag an unfiltered page carries),
        so a document's metadata resolves in ONE request no matter where the
        paper sits in the docket. Appeals and interferences have no filterable
        document index — their GET decisions endpoint takes none — so they
        return None and the caller walks the bag as before.

        An id the docket does not hold comes back as the API's HTTP 404
        no-matching-records envelope rather than an empty bag, so the caller
        must treat an error envelope as "not resolved here", not as a failure.
        """
        if self.identifier_type != "trial":
            return None
        return await client.search_trial_documents(
            identifier,
            offset=0,
            limit=1,
            extra_filters=[{
                "name": TrialDocumentFilterFields.DOCUMENT_IDENTIFIER,
                "value": [document_id],
            }],
        )

    async def _fetch_decisions(self, client, identifier: str) -> Dict[str, Any]:
        if self.identifier_type == "appeal":
            return await client.get_appeal_decisions(identifier)
        return await client.get_interference_decisions(identifier)

    async def fetch_proceeding_metadata(
        self, client, identifier: str
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """(patent_number, application_number, filing_date) for the proceeding."""
        if self.identifier_type == "trial":
            response = await client.search_trials(
                filters=[{"name": "trialNumber", "value": [identifier]}],
                pagination={"offset": 0, "limit": 1},
            )
            records = response.get("patentTrialProceedingDataBag", [])
            if not records:
                return None, None, None
            record = records[0]
            # The patent and application numbers live under patentOwnerData.
            # respondentData does NOT exist on a trial record: the payload
            # carries only trialNumber, lastModifiedDateTime, trialMetaData,
            # regularPetitionerData and patentOwnerData (verified live
            # 2026-07-02, config/filter_field_mapping.py:92 and
            # tools/trials.py:598), so reading it returned (None, None, date)
            # for every trial. The dead bag is kept as a fallback so this
            # self-heals if USPTO ever starts populating it.
            owner = record.get("patentOwnerData", {})
            legacy = record.get("respondentData", {})
            return (
                owner.get("patentNumber") or legacy.get("patentNumber"),
                owner.get("applicationNumberText") or legacy.get("applicationNumber"),
                record.get("trialMetaData", {}).get("accordedFilingDate"),
            )
        if self.identifier_type == "appeal":
            response = await client.search_appeals(
                filters=[{"name": "appealNumber", "value": [identifier]}],
                pagination={"offset": 0, "limit": 1},
            )
            records = response.get("patentAppealDataBag", [])
            if not records:
                return None, None, None
            record = records[0]
            # Same defect class as the trial branch above: an appeal record
            # carries no decisionMetaData bag and no root-level
            # applicationNumber (field_configs.yaml:100, and the verbatim wire
            # slice in tests/test_appeal_interference_field_paths.py probed
            # 2026-09-02). The appellant bag is where the serial lives.
            appellant = record.get("appellantData", {})
            legacy = record.get("decisionMetaData", {})
            return (
                appellant.get("patentNumber") or legacy.get("patentNumber"),
                appellant.get("applicationNumberText") or legacy.get("applicationNumber"),
                record.get("decisionData", {}).get("decisionIssueDate"),
            )
        response = await client.search_interferences(
            filters=[{"name": "interferenceNumber", "value": [identifier]}],
            pagination={"offset": 0, "limit": 1},
        )
        records = response.get("patentInterferenceDataBag", [])
        if not records:
            return None, None, None
        # interferenceMetaData carries the declaration date and the style name,
        # not the numbers: an interference record puts those on the senior and
        # junior party bags (config/filter_field_mapping.py SENIOR_PATENT_NUMBER,
        # and the verbatim wire slice probed 2026-09-02). Senior party first,
        # matching the rest of the interference filter surface.
        record = records[0]
        meta = record.get("interferenceMetaData", {})
        senior = record.get("seniorPartyData", {})
        return (
            senior.get("patentNumber") or meta.get("patentNumber"),
            senior.get("applicationNumberText") or meta.get("applicationNumber"),
            meta.get("declarationDate"),
        )

    async def download_document(self, client, file_download_uri: str) -> bytes:
        if self.identifier_type == "trial":
            return await client.download_trial_document(file_download_uri)
        if self.identifier_type == "appeal":
            return await client.download_appeal_document(file_download_uri)
        return await client.download_interference_document(file_download_uri)


PROCEEDING_ADAPTERS: Dict[str, ProceedingAdapter] = {
    "trial": ProceedingAdapter(
        identifier_type="trial",
        bag_key="patentTrialDocumentDataBag",
        validate_identifier=validate_trial_number,
        parent_metadata=lambda item: {
            "trialNumber": item.get("trialNumber"),
            "lastModifiedDateTime": item.get("lastModifiedDateTime"),
        },
        parent_preserved=lambda item: {
            "trialDocumentCategory": item.get("trialDocumentCategory"),
            "_patentOwnerData": item.get("patentOwnerData", {}),
        },
    ),
    "appeal": ProceedingAdapter(
        identifier_type="appeal",
        bag_key="patentAppealDataBag",
        validate_identifier=validate_appeal_number,
        parent_metadata=lambda item: {
            "appealNumber": item.get("appealNumber"),
            "appealOutcomeCategory": item.get("decisionData", {}).get("appealOutcomeCategory"),
            "decisionIssueDate": item.get("decisionData", {}).get("decisionIssueDate"),
        },
        parent_preserved=lambda item: {
            "appealDocumentCategory": item.get("appealDocumentCategory"),
            "_appellantData": item.get("appellantData", {}),
        },
    ),
    "interference": ProceedingAdapter(
        identifier_type="interference",
        bag_key="patentInterferenceDataBag",
        validate_identifier=validate_interference_number,
        parent_metadata=lambda item: {
            "interferenceNumber": item.get("interferenceNumber"),
            "interferenceStyleName": item.get("interferenceMetaData", {}).get("interferenceStyleName"),
            "declarationDate": item.get("interferenceMetaData", {}).get("declarationDate"),
        },
    ),
}


def get_adapter(identifier_type: str) -> ProceedingAdapter:
    """Adapter for a validated identifier_type; raises ValueError otherwise."""
    adapter = PROCEEDING_ADAPTERS.get(identifier_type)
    if adapter is None:
        raise ValueError(f"Unsupported identifier type: {identifier_type}")
    return adapter


def find_document(
    documents: List[Dict[str, Any]], document_id: str
) -> Optional[Dict[str, Any]]:
    """First document whose documentIdentifier matches, else None."""
    for doc in documents:
        if doc.get("documentIdentifier") == document_id:
            return doc
    return None


def find_document_or_fallback_uri(
    documents: List[Dict[str, Any]],
    document_id: str,
    identifier: str,
    identifier_type: str,
) -> Optional[Dict[str, Any]]:
    """Find document_id in `documents`; for trials, fall back to the
    constructed ptab-files/{TYPE}/{YEAR}/{NUM}/{doc_id}.pdf URI when the
    POST index omits the paper (e.g. Petition, Institution Decision)."""
    matching = find_document(documents, document_id)
    if matching is None and identifier_type == "trial":
        m = _TRIAL_ID_PATTERN.match(identifier)
        if m:
            proc_type, year, num = m.groups()
            matching = {
                "documentIdentifier": document_id,
                "fileDownloadURI": (
                    f"{_PTAB_FILES_BASE}/{proc_type}/{year}/{num}/{document_id}.pdf"
                ),
            }
    return matching


def find_in_bag(
    raw_response: Dict[str, Any], identifier_type: str, document_id: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """(documentData, parent_item) for the bag entry matching document_id.

    Used by the proxy download route, which needs the raw parent item for
    filename metadata rather than a flattened document.
    """
    adapter = get_adapter(identifier_type)
    for item in raw_response.get(adapter.bag_key, []) or []:
        doc_data = item.get("documentData", {})
        if doc_data.get("documentIdentifier") == document_id:
            return doc_data, item
    return None, None
