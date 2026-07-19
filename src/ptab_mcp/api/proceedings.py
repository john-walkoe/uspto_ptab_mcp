"""Proceeding-type adapters for trials / appeals / interferences.

One data-driven registry (SOLID-2, dup §2.4) replaces the
`if identifier_type == "trial"/elif "appeal"/elif "interference"` chains that
were previously repeated — with drift — across ptab_get_documents,
ptab_get_document_download, ptab_get_document_content, and the proxy's
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
    ) -> Dict[str, Any]:
        """One page of documents. Server-side paging for trials only;
        appeals/interferences use the GET decisions endpoint (no paging)."""
        if self.identifier_type == "trial":
            return await client.search_trial_documents(
                identifier, offset=offset, limit=limit, sort_order=sort_order
            )
        return await self._fetch_decisions(client, identifier)

    async def fetch_all_documents(self, client, identifier: str) -> Dict[str, Any]:
        """Full document set (paginating past the trial API's 100-row cap)."""
        if self.identifier_type == "trial":
            return await client.search_all_trial_documents(identifier)
        return await self._fetch_decisions(client, identifier)

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
            respondent = record.get("respondentData", {})
            return (
                respondent.get("patentNumber"),
                respondent.get("applicationNumber"),
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
            meta = record.get("decisionMetaData", {})
            return (
                meta.get("patentNumber"),
                meta.get("applicationNumber"),
                record.get("decisionData", {}).get("decisionIssueDate"),
            )
        response = await client.search_interferences(
            filters=[{"name": "interferenceNumber", "value": [identifier]}],
            pagination={"offset": 0, "limit": 1},
        )
        records = response.get("patentInterferenceDataBag", [])
        if not records:
            return None, None, None
        meta = records[0].get("interferenceMetaData", {})
        return (
            meta.get("patentNumber"),
            meta.get("applicationNumber"),
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
