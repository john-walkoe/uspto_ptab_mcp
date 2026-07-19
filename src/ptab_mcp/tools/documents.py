"""Shared document tools: list, download link, content extraction.

Includes the extraction tier helpers (PyPDF2 -> Mistral -> Docling), the
download delivery resolution (centralized PFW proxy vs local persistent
link), and the recent-downloads registration path.
"""

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

from fastmcp import Context
from fastmcp.apps import AppConfig

from ..api.proceedings import find_document_or_fallback_uri, get_adapter
from ..app_uris import DOWNLOADS_URI
from ..proxy.centralized_integration import register_with_centralized_proxy
from ..proxy.server import generate_enhanced_filename
from ..runtime import _client, docling_client, ocr_service, settings
from ..server_bootstrap import _ensure_local_proxy_running, get_local_proxy_port
from ..shared.error_utils import sanitize_error_message
from ..shared.injection_scan import RETRIEVED_TEXT_NOTE, scan_hits
from ..shared.safe_logger import get_safe_logger
from ..util.identity import get_authenticated_identity, get_viewer_key
from ..util.response_formatter import format_document_list, format_error_response
from ..validation.validators import (
    validate_document_id,
    validate_identifier_type,
)

logger = get_safe_logger(__name__)

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


def _filter_documents(
    documents: List[Dict[str, Any]],
    identifier_type: str,
    document_title: Optional[str],
    document_category: Optional[str],
    filing_party: Optional[str],
    outcome_category: Optional[str],
) -> tuple:
    """Apply the tool's optional document filters. Returns (docs, applied)."""
    filtered = documents
    applied: Dict[str, str] = {}

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
) -> List[Dict[str, Any]]:
    """Sort (tiebreaker for trials, primary for others) and client-side
    paginate for appeals/interferences (trials paginate server-side)."""
    def _sort_key(doc):
        return doc.get("documentFilingDate") or doc.get("lastModifiedDateTime") or ""

    documents = sorted(documents, key=_sort_key, reverse=(sort_order == "desc"))
    if identifier_type != "trial":
        if offset:
            documents = documents[offset:]
        if limit and limit < len(documents):
            documents = documents[:limit]
    return documents


async def ptab_get_documents(
    identifier: str,
    identifier_type: str = "trial",
    limit: int = 50,
    offset: int = 0,
    sort_order: str = "desc",
    document_title: Optional[str] = None,
    document_category: Optional[str] = None,
    filing_party: Optional[str] = None,
    outcome_category: Optional[str] = None
) -> str:
    """Get list of documents for trial, appeal, or interference with SELECTIVE FILTERING.

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
      ptab_get_documents(identifier='IPR2024-01353', sort_order='asc', limit=25)
      # Skip first 5 oldest, get next 10
      ptab_get_documents(identifier='IPR2024-01353', sort_order='asc', offset=5, limit=10)

    **document_title** - Case-insensitive substring filter on documentTypeDescriptionText.
      The API returns a plain-text description for each document (e.g. "Final Written Decision",
      "Institution Decision on Petition", "Petition for Inter Partes Review"). This filter
      matches any document whose description contains the supplied string.
      More precise than document_category — use it to target a single document type.
      Examples:
        ptab_get_documents(identifier='IPR2024-01353', document_title='Final Written Decision')
        ptab_get_documents(identifier='IPR2024-01353', document_title='Institution Decision')
        ptab_get_documents(identifier='IPR2024-01353', document_title='Petition for Inter Partes')
        ptab_get_documents(identifier='IPR2024-01353', document_title='Patent Owner Response')
        ptab_get_documents(identifier='IPR2024-01353', document_title='Oral Hearing')
      Tip: use a short substring (e.g. 'Institution', 'Oral') to cast a wider net;
           use a longer phrase to target exactly one document.

    📄 PAGINATION (trials only): Uses server-side pagination via POST search endpoint.
    Returns the true total_documents count and a next_offset hint when more pages exist.
    Full docket access example for a 40-paper proceeding:
      # Page 1 — Papers 1-25 oldest first (Petition, POPR, Institution Decision...)
      ptab_get_documents(identifier='IPR2024-01353', sort_order='asc', offset=0, limit=25)
      # Page 2 — Papers 26-40
      ptab_get_documents(identifier='IPR2024-01353', sort_order='asc', offset=25, limit=25)
    Appeals/Interferences still use a GET endpoint with no server-side pagination.

    **document_category** - Coarser filter for trials by document category (case-insensitive).
      Use document_title for precision; use document_category when browsing by broad type.
      Key Categories:
        - PETITION: Petition documents
        - RESPONSE: Patent owner responses
        - ORDER: Board orders
        - DECISION: Board decisions (Institution, Final Written Decision)
        - MOTION: Motions and exhibits

    **filing_party** - Filter trials by filing party (case-insensitive):
      Key Parties:
        - BOARD: Board documents (orders, decisions)
        - PETITIONER: Petitioner submissions
        - PATENT OWNER: Patent owner submissions

    **outcome_category** - Filter appeals/interferences by outcome (case-insensitive):
      Appeals: "Affirmed", "Reversed", "Rehearing Decision Denied"
      Interferences: "Final Decision", "Judgment", etc.

    📌 EXAMPLES (always use filtering for large proceedings):

    # Final Written Decision only
    ptab_get_documents(identifier='IPR2024-00123', document_category='DECISION', limit=5)

    # All Board orders
    ptab_get_documents(identifier='IPR2024-00123', filing_party='BOARD', limit=20)

    # Patent owner responses
    ptab_get_documents(identifier='IPR2024-00123', filing_party='PATENT OWNER')

    # Appeals with specific outcome
    ptab_get_documents(identifier='2025000943', identifier_type='appeal',
                       outcome_category='Affirmed', limit=10)

    ⚠️ AVOID: ptab_get_documents(identifier='...', limit=100) without filters
    ✅ DO: Always filter by document_category, filing_party, or outcome_category

    BASIC USAGE:
    - Core Purpose: Retrieve complete document list for any PTAB proceeding
    - Returns: Documents with filtering applied
    - Supports: Trials (IPR/PGR/CBM), Appeals, Interferences (via identifier_type parameter)
    - Typical Volume: 10-100+ documents depending on proceeding complexity

    WHEN TO USE THIS TOOL:
    - Document Discovery: After selecting trial/appeal/interference from search results
    - Selective Download Planning: Review documents before downloading (avoid unnecessary OCR costs)
    - Multi-Document Workflows: Get all document IDs for batch processing
    - Progressive Disclosure Stage 3: After minimal search → balanced analysis → document operations

    DOCUMENT WORKFLOW:
    1. Use search_trials_minimal/balanced to find proceeding - Get trial number
    2. Use ptab_get_documents (this tool) with filters - Get specific document types
    3. User/LLM selects priority documents based on use case
    4. Use ptab_get_document_download - Get browser-accessible download links
    5. OR use ptab_get_document_content - Extract text for LLM analysis (OCR costs apply)

    PRIORITY DOCUMENTS BY USE CASE:

    IPR Response Strategy:
      ptab_get_documents(identifier='...', document_category='DECISION')
      - Final Written Decision (outcome analysis)
      - Institution Decision (claims instituted)

    Prior Art Research:
      ptab_get_documents(identifier='...', filing_party='PETITIONER')
      - Petition documents (petitioner's case)
      - Petitioner exhibits (cited references)

    Litigation Preparation:
      ptab_get_documents(identifier='...', filing_party='BOARD', limit=20)
      - All decisions and orders (procedural history)
      - Estoppel analysis documents

    RELATED TOOLS:
    - Next Step: ptab_get_document_download (browser access) or ptab_get_document_content (LLM analysis)
    - Previous Step: search_trials_minimal/balanced (find trials first)
    - Cross-MCP: pfw_get_application_documents (prosecution history documents)

    GUIDANCE REFERENCES:
    - For document selection strategies: ptab_get_guidance(section='documents')
    - For multi-document workflows: ptab_get_guidance(section='documents')
    - For cost optimization (avoid unnecessary OCR): ptab_get_guidance(section='cost')

    Args:
        identifier: Trial number (IPR2024-00123), appeal number (2024-001234), or interference number
        identifier_type: Type of proceeding - "trial" (default), "appeal", or "interference"
        limit: Max documents to return (default: 50, max: 100 — the API rejects larger pages)
        offset: Skip first N documents (default: 0). Server-side for trials, client-side for appeals/interferences.
        sort_order: Sort direction - "desc" (newest first, default) or "asc" (oldest first).
                    Server-side for trials (by documentFilingDate); client-side for appeals/interferences.
        document_title: Case-insensitive substring match on documentTypeDescriptionText.
                        Use to target specific document types, e.g. 'Final Written Decision',
                        'Institution Decision', 'Petition for Inter Partes', 'Patent Owner Response'.
        document_category: Coarser filter for trials by document category (PETITION, RESPONSE, ORDER, DECISION, MOTION)
        filing_party: Filter trials by filing party (BOARD, PETITIONER, PATENT OWNER)
        outcome_category: Filter appeals/interferences by outcome

    Returns:
        JSON string with filtered document list

    Example:
        {"identifier": "IPR2024-00123",
         "identifier_type": "trial",
         "total_documents": 45,
         "filtered_count": 5,
         "filter_applied": {"document_category": "DECISION"},
         "documents": [
             {"documentIdentifier": "171141394",
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

        # Route to the correct API method via the adapter.
        # Trials: POST search endpoint (server-side pagination/sort).
        # Appeals/Interferences: GET convenience endpoints.
        raw_response = await adapter.fetch_documents_page(
            api_client, identifier, offset=offset, limit=limit, sort_order=sort_order
        )

        # Check for API error
        if raw_response.get("error"):
            return json.dumps(raw_response, indent=2)

        # Flatten the proceeding's data bag into a plain document list
        documents = adapter.flatten_documents(raw_response)

        # For trials: API returns the true total count (server-side pagination)
        # For appeals/interferences: count what we got (no pagination support)
        api_total_count = raw_response.get("count")
        total_documents = api_total_count if (identifier_type == "trial" and api_total_count is not None) else len(documents)

        # Apply filtering, then sort/paginate (client-side for non-trials)
        filtered_documents, filters_applied = _filter_documents(
            documents, identifier_type,
            document_title, document_category, filing_party, outcome_category,
        )
        filtered_documents = _sort_and_paginate(
            filtered_documents, identifier_type, sort_order, offset, limit
        )

        # Format output with filtering metadata
        formatted = format_document_list(
            documents=filtered_documents,
            identifier=identifier,
            identifier_type=identifier_type,
            count=len(filtered_documents)
        )

        # Parse formatted JSON to add filtering metadata
        formatted_dict = json.loads(formatted)
        formatted_dict["total_documents"] = total_documents
        formatted_dict["returned_count"] = len(filtered_documents)
        if filters_applied:
            formatted_dict["filters_applied"] = filters_applied
        formatted_dict["offset"] = offset
        formatted_dict["limit"] = limit
        formatted_dict["sort_order"] = sort_order
        if identifier_type == "trial" and total_documents and total_documents > offset + len(filtered_documents):
            formatted_dict["next_offset"] = offset + len(filtered_documents)

        return json.dumps(formatted_dict, indent=2)

    except ValueError as e:
        return format_error_response(str(e), "VALIDATION_ERROR")
    except RuntimeError as e:
        # Catch async lifecycle errors specifically
        error_msg = str(e)
        if "cannot schedule new futures" in error_msg or "interpreter shutdown" in error_msg:
            logger.error(f"Async lifecycle error in ptab_get_documents: {error_msg}")
            return json.dumps({
                "error": True,
                "message": "Operation failed due to async runtime issue. Try restarting the MCP server.",
                "technical_details": sanitize_error_message(error_msg)
            }, indent=2)
        else:
            raise  # Re-raise other RuntimeErrors
    except Exception as e:
        logger.error(f"Error in ptab_get_documents: {str(e)}")
        return format_error_response(str(e), "API_ERROR")




def _derive_document_metadata(
    matching_doc: Dict[str, Any],
    identifier_type: str,
    proceeding_patent_number,
    proceeding_filing_date,
) -> tuple:
    """(description, page_count, document_code, filing_date, patent_number)
    for enhanced-filename generation — field names vary by proceeding type."""
    doc_description = (
        matching_doc.get("documentTitleText") or  # Trials (most specific)
        matching_doc.get("appealDocumentCategory") or  # Appeals: "Decision"
        matching_doc.get("trialDocumentCategory") or  # Trials: "PETITION", etc.
        matching_doc.get("documentCategory") or
        matching_doc.get("documentTypeDescriptionText") or  # Fallback: "Paper"
        "Document"
    )
    # Use documentName as final fallback
    if doc_description == "Document" and matching_doc.get("documentName"):
        doc_name = matching_doc.get("documentName", "")
        if doc_name.endswith(".pdf"):
            doc_name = doc_name[:-4]
        doc_description = doc_name.split("_")[0] if "_" in doc_name else doc_name

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

    PREREQUISITE: First use ptab_get_documents to get document_identifier from document list.

    BASIC USAGE:
    - Core Purpose: Create clickable proxy links for browser downloads (handles API authentication)
    - Proxy Integration: Centralized PFW proxy (port 8080) with automatic fallback to local (port 8083)
    - Link Validity: 7-day persistent links (remain valid after proxy restart)
    - Security: Keeps API credentials secure while enabling direct browser access

    WHEN TO USE THIS TOOL:
    - User Download: When user will review document themselves in browser
    - Multi-Document Packages: Generate download links for complete docket
    - Legal Review Workflows: Provide attorneys with browser-accessible PDFs
    - Cost Avoidance: Use download (free) instead of content extraction (OCR costs $)

    DOWNLOAD VS EXTRACT DECISION TREE:

    User needs document → User will read it themselves?
      YES → ptab_get_document_download (this tool) - FREE
            Returns browser-accessible link
            User downloads and reviews directly

      NO → LLM needs to analyze content?
           YES → ptab_get_document_content - PAID
                 Hybrid extraction (PyPDF2 + Mistral OCR)
                 Cost: ~$0.15 per 1M tokens (Mistral OCR)
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
      docs = ptab_get_documents(identifier='IPR2024-00123', identifier_type='trial')

    Step 2: Filter to priority documents (e.g., Final Written Decisions)
      fwd_docs = [d for d in docs['documents']
                  if 'Final Written Decision' in d.get('description', '')]

    Step 3: Generate download links for all (up to 5-10)
      for doc in fwd_docs[:5]:
          download = ptab_get_document_download(
              identifier='IPR2024-00123',
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
      - PTAB-2024-05-15_IPR2024-00123_PAT-8524787_FINAL_WRITTEN_DECISION.pdf
      - PTAB-2024-03-20_PGR2025-00045_PAT-9876543_INSTITUTION_DECISION.pdf
      - PTAB-2024-01-10_IPR2024-00123_PAT-8524787_PATENT_OWNER_RESPONSE.pdf

    RELATED TOOLS:
    - Previous Step: ptab_get_documents (get document list and IDs first)
    - Alternative: ptab_get_document_content (LLM analysis instead of user download)
    - Cross-MCP: pfw_get_document_download (prosecution history documents)

    GUIDANCE REFERENCES:
    - For download link formatting: ptab_get_guidance(section='documents')
    - For multi-document workflows: ptab_get_guidance(section='documents')
    - For cost optimization: ptab_get_guidance(section='cost')
    - For cross-MCP integration: ptab_get_guidance(section='workflows_pfw')

    Args:
        document_id: Document identifier from ptab_get_documents()
        identifier: Trial/appeal/interference number
        identifier_type: Type of proceeding - "trial" (default), "appeal", or "interference"

    Returns:
        JSON string with download URL, proxy info, and llm_response_guidance

    Example Response:
        {
            "document_id": "171141394",
            "identifier": "IPR2024-00123",
            "proxy_url": "http://localhost:8080/download/IPR2024-00123/171141394",
            "document_description": "Final Written Decision",
            "page_count": 45,
            "enhanced_filename": "PTAB-2024-05-15_IPR2024-00123_PAT-8524787_FINAL_WRITTEN_DECISION.pdf",
            "llm_response_guidance": {
                "format": "**[Download Final Written Decision (45 pages)](http://localhost:8080/download/...)** | Raw URL: `http://localhost:8080/download/...`",
                "critical": "Provide clickable markdown link for browser access AND raw URL for clients like Msty where links aren't clickable",
                "example": "**[Download Final Written Decision (45 pages)](http://localhost:8080/download/IPR2024-00123/171141394)** | Raw URL: `http://localhost:8080/download/IPR2024-00123/171141394`"
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

        # Get document metadata to extract fileDownloadURI.
        # Trials use the POST search endpoint (paginating past the 100-row
        # cap); the GET convenience endpoint only returns ~25 documents.
        docs_response = await adapter.fetch_all_documents(api_client, identifier)

        # Flatten with parent data preserved for enhanced-filename generation
        documents = adapter.flatten_documents(docs_response, preserve_parent=True)

        # Find document by ID; for trials, fall back to the constructed
        # ptab-files URI when the POST index omits the paper (Petition, etc.)
        matching_doc = find_document_or_fallback_uri(
            documents, document_id, identifier, identifier_type
        )

        if not matching_doc:
            raise ValueError(f"Document ID '{document_id}' not found in {identifier}")

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

        # URL-mode elicitation: offer to open the downloads page in the
        # browser. STRICTLY optional UX sugar — Issue A in the FOR-CLAUDE-FABLE
        # heads-up doc: clients that don't support URL elicitation (claude.ai's
        # connector) never answer the server→client elicitation/create request,
        # so an un-timed await parks this coroutine forever and the client
        # surfaces "generic tool-execution error". The try/except cannot catch
        # a hang. So: capability-gate on the client's advertised
        # elicitation.url, and bound with a timeout as belt-and-braces. The
        # JSON response below is returned regardless.
        elicitation_action = None
        if ctx is not None and download_registry_id and _client_supports_url_elicitation(ctx):
            try:
                downloads_page_url = (
                    f"{_get_ptab_proxy_base_url(get_local_proxy_port())}"
                    f"/downloads?highlight={download_registry_id}&s={viewer_key}"
                )
                elicit_result = await asyncio.wait_for(
                    ctx.session.elicit_url(
                        message=(
                            f"Download link ready: {enhanced_filename}. "
                            "Open the PTAB downloads page in your browser?"
                        ),
                        url=downloads_page_url,
                        elicitation_id=download_registry_id,
                    ),
                    timeout=30.0,
                )
                elicitation_action = getattr(elicit_result, "action", None)
            except Exception as elicit_error:
                logger.debug(f"URL elicitation skipped (client support): {type(elicit_error).__name__}")

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
            "downloads_page_opened": elicitation_action == "accept",
            "llm_response_guidance": {
                "format": f"**[Download {doc_description} ({page_count} pages)]({final_url})** | Raw URL: `{final_url}`",
                "critical": "Provide clickable markdown link for browser access AND raw URL for clients like Msty where links aren't clickable",
                "example": f"**[Download {doc_description} ({page_count} pages)]({final_url})** | Raw URL: `{final_url}`"
            }
        }

        return json.dumps(response, indent=2)

    except ValueError as e:
        return format_error_response(str(e), "VALIDATION_ERROR")
    except RuntimeError as e:
        # Catch async lifecycle errors specifically
        error_msg = str(e)
        if "cannot schedule new futures" in error_msg or "interpreter shutdown" in error_msg:
            logger.error(f"Async lifecycle error in ptab_get_document_download: {error_msg}")
            return json.dumps({
                "error": True,
                "message": "Operation failed due to async runtime issue. Try restarting the MCP server.",
                "technical_details": sanitize_error_message(error_msg)
            }, indent=2)
        else:
            raise  # Re-raise other RuntimeErrors
    except Exception as e:
        logger.error(f"Error in ptab_get_document_download: {str(e)}")
        return format_error_response(str(e), "API_ERROR")



# =============================================================================
# EXTRACTION TIERS (PyPDF2 -> Mistral OCR -> Docling) — metrics §1.3
# =============================================================================
# Each tier is a standalone helper walked by ptab_get_document_content, so the
# tool body is orchestration only. Behavior (logging, thresholds, fallbacks)
# is unchanged from the previous inline implementation.

def _coerce_page_count(raw_page_count) -> int:
    """Page count for the OCR cost estimate and the Docling page gate."""
    if isinstance(raw_page_count, str):
        try:
            return int(raw_page_count)
        except ValueError:
            return 50
    return raw_page_count if isinstance(raw_page_count, int) else 50


def _try_pypdf2_extraction(pdf_bytes: bytes) -> str:
    """Free text-layer extraction. Returns "" when the text layer is missing
    or too thin (<100 chars), which signals the caller to escalate to OCR."""
    try:
        import io
        import PyPDF2

        pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        extracted_text = "\n".join(page.extract_text() for page in pdf_reader.pages)

        if len(extracted_text.strip()) >= 100:
            logger.info(f"PyPDF2 extraction successful: {len(extracted_text)} chars")
            return extracted_text
        logger.warning(f"PyPDF2 extraction yielded only {len(extracted_text)} chars")
        return ""
    except Exception as e:
        logger.warning(f"PyPDF2 extraction failed: {str(e)}")
        return ""


async def _try_mistral_extraction(
    pdf_bytes: bytes, page_count: int, identifier: str, document_id: str, progress_cb
) -> dict:
    """Mistral OCR tier — returns the raw ocr_result dict (success or not).

    Bulkhead (RF-6): acquires the client's Mistral concurrency semaphore so
    the declared limit actually holds. Throttled per identity (M-4).
    """
    async with _client().mistral_semaphore:
        return await ocr_service.extract_document_content(
            pdf_content=pdf_bytes,
            page_count=page_count,
            identifier=identifier,
            document_id=document_id,
            progress_cb=progress_cb,
            caller_id=get_authenticated_identity() or "local-process"
        )


async def _try_docling_extraction(
    pdf_bytes: bytes, page_count: int, document_id: str, progress_cb
) -> str:
    """Docling tier (self-hosted, free) — short docs only. Returns "" when
    unavailable, page-gated, or failed.

    Page gate (Lesson 19): EasyOCR takes ~10-30s/page; anything over
    DOCLING_MAX_PAGES would blow the MCP tool call timeout.
    """
    if not docling_client.is_available():
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



async def _run_extraction_tiers(
    pdf_bytes: bytes, page_count: int, identifier: str, document_id: str,
    use_ocr: bool, progress_cb,
) -> tuple:
    """Walk the PyPDF2 -> Mistral -> Docling waterfall.

    Returns (text, method, cost, extra); empty text means every tier failed
    and the caller should return _all_tiers_failed_response(). `extra` carries
    OCR metadata the caller surfaces to the client (SD-6: page truncation,
    pages_processed) — empty for the PyPDF2/Docling tiers.
    """
    extracted_text = ""
    extraction_method = "pypdf2"
    ocr_cost_usd = 0.00
    extra: Dict[str, Any] = {}

    if not use_ocr:
        await progress_cb(40, 100, "Extracting text with PyPDF2 (free)...")
        extracted_text = _try_pypdf2_extraction(pdf_bytes)

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
            logger.info(f"Mistral OCR extraction successful: {len(extracted_text)} chars, "
                       f"${ocr_cost_usd:.4f} cost")
        else:
            logger.error(f"Mistral OCR extraction failed: {ocr_result.get('message', 'Unknown OCR error')}")
            ocr_cost_usd = 0.00

            extracted_text = await _try_docling_extraction(
                pdf_bytes, page_count, document_id, progress_cb
            )
            extraction_method = "docling" if extracted_text else extraction_method

    return extracted_text, extraction_method, ocr_cost_usd, extra


def _all_tiers_failed_response(document_id: str, identifier: str) -> str:
    """Enhanced error with LLM guidance when every extraction tier fails."""
    return json.dumps({
        "document_id": document_id,
        "identifier": identifier,
        "text": "",
        "extraction_method": "PyPDF2 (insufficient)",
        "error": "Document appears to be scanned/image-based. PyPDF2 could not extract meaningful text.",
        "mistral_api_key_missing": not ocr_service.mistral_api_key,
        "docling_configured": docling_client.is_available(),
        "llm_guidance": {
            "explain_to_user": "Many USPTO PTAB documents are scanned images rather than text-based PDFs. "
                              "PyPDF2 can only extract text from text-based PDFs - it cannot read scanned images.",
            "recommended_solution": "Configure Mistral API for OCR capability (~$0.001/page, with free tier available)",
            "free_tier_info": "Mistral offers a generous free tier - sign up at https://console.mistral.ai/",
            "setup_instructions": "Set MISTRAL_API_KEY environment variable after obtaining key from Mistral console",
            "docling_alternative": "For short documents (<= 20 pages), a self-hosted docling-serve instance "
                                   "can OCR for free - set DOCLING_SERVE_URL to enable"
        }
    }, indent=2)


async def ptab_get_document_content(
    document_id: str,
    identifier: str,
    identifier_type: str = "trial",
    use_ocr: bool = False,
    ctx: Context = None
) -> str:
    """Extract text content from PTAB documents for LLM analysis (hybrid PyPDF2 + Mistral OCR + Docling).

    PREREQUISITE: First use ptab_get_documents to get document_identifier.

    BASIC USAGE:
    - Core Purpose: Extract text from PDFs for LLM analysis and question answering
    - Extraction Strategy: Try PyPDF2 first (free), then Mistral OCR (costs $),
      then Docling OCR (self-hosted, free) for short documents
    - Cost Management: PyPDF2 always attempted first to avoid OCR charges
    - Typical Use: Answer questions about Board decisions, analyze reasoning
    - Docling gate: only documents <= DOCLING_MAX_PAGES (default 20) go to
      Docling — PTAB petitions (60p), responses (80p) and exhibits (100-300p)
      are too slow for EasyOCR and should use Mistral instead

    WHEN TO USE THIS TOOL:
    - LLM Analysis: When LLM needs to answer questions about document content
    - Text Extraction: For semantic search, RAG, or text mining workflows
    - Decision Analysis: Understanding Board's claim construction or reasoning
    - Selective Extraction: Only for 1-3 critical documents (avoid cost explosion)

    HYBRID EXTRACTION STRATEGY:

    Step 1: Download PDF from USPTO
    Step 2: Try PyPDF2 text extraction (fast, free)
    Step 3: If < 100 chars, use Mistral OCR (slower, costs $)
    Step 4: If Mistral unavailable/fails and document <= DOCLING_MAX_PAGES,
            use Docling OCR (self-hosted docling-serve, free but slower)
    Step 5: Return extracted text with metadata

    Docling env vars: DOCLING_SERVE_URL (enables the tier), DOCLING_TIMEOUT
    (default 300s), DOCLING_MAX_PAGES (default 20).

    Cost Calculation:
    - PyPDF2 extraction: FREE (always tried first)
    - Mistral OCR: ~$0.15 per 1M input tokens
      - Final Written Decision (45 pages): ~$0.01-0.02
      - Petition (100 pages): ~$0.02-0.04
      - Complete docket (500 pages): ~$0.10-0.15

    COST OPTIMIZATION WORKFLOW:

    User needs document → LLM will analyze?
      YES → How many documents?
            - 1-3 documents: ptab_get_document_content (acceptable cost)
            - 5+ documents: Use ptab_get_document_download instead
                            → User reviews and selects 1-3 for extraction

      NO → ptab_get_document_download (user downloads, FREE)

    RELATED TOOLS:
    - Alternative: ptab_get_document_download (user download, no OCR costs)
    - Previous Step: ptab_get_documents (get document list first)
    - Cross-MCP: pfw_get_document_content (prosecution history text extraction)

    GUIDANCE REFERENCES:
    - For cost optimization strategies: ptab_get_guidance(section='cost')
    - For download vs extract decision tree: ptab_get_guidance(section='documents')
    - For OCR cost calculations: ptab_get_guidance(section='cost')

    Args:
        document_id: Document identifier from ptab_get_documents()
        identifier: Trial/appeal/interference number
        identifier_type: Type of proceeding - "trial" (default), "appeal", or "interference"
        use_ocr: Force Mistral OCR even if PyPDF2 succeeds (for better quality)

    Returns:
        JSON string with extracted text, method used, cost estimate

    Example Response:
        {
            "text": "UNITED STATES PATENT AND TRADEMARK OFFICE...",
            "extraction_method": "pypdf2",
            "character_count": 25000,
            "page_count": 45,
            "ocr_cost_usd": 0.00,
            "note": "PyPDF2 extraction successful (no OCR charges)"
        }

    Example Response (OCR used):
        {
            "text": "UNITED STATES PATENT AND TRADEMARK OFFICE...",
            "extraction_method": "mistral_ocr",
            "character_count": 25000,
            "page_count": 45,
            "ocr_cost_usd": 0.015,
            "note": "Mistral OCR used (PyPDF2 failed for scanned PDF)"
        }
    """
    try:
        _progress = _make_progress_cb(ctx)

        api_client = _client()

        identifier_type, adapter, identifier, document_id = (
            _validate_document_request(identifier, identifier_type, document_id)
        )

        # Get document metadata via the adapter (POST search for trials,
        # GET decisions for appeals/interferences) and flatten the bag
        docs_response = await adapter.fetch_all_documents(api_client, identifier)
        documents = adapter.flatten_documents(docs_response)

        # Find document by ID (with trial ptab-files URI fallback)
        matching_doc = find_document_or_fallback_uri(
            documents, document_id, identifier, identifier_type
        )

        if not matching_doc:
            raise ValueError(f"Document ID '{document_id}' not found in {identifier}")

        # Extract download URL
        download_url = matching_doc.get("fileDownloadURI")

        if not download_url:
            raise ValueError(f"No download URI found for document {document_id}")

        await _progress(25, 100, f"Downloading PDF for {identifier} document {document_id}...")

        # Download PDF via the adapter
        pdf_bytes = await adapter.download_document(api_client, download_url)

        page_count = _coerce_page_count(matching_doc.get("pageCount", 50))

        # Walk the extraction waterfall (PyPDF2 -> Mistral -> Docling)
        extracted_text, extraction_method, ocr_cost_usd, ocr_extra = await _run_extraction_tiers(
            pdf_bytes, page_count, identifier, document_id, use_ocr, _progress
        )
        if not extracted_text:
            return _all_tiers_failed_response(document_id, identifier)

        await _progress(100, 100, f"Extraction complete ({extraction_method}, {len(extracted_text)} chars)")

        # Return result
        response = {
            "document_id": document_id,
            "identifier": identifier,
            "identifier_type": identifier_type,
            "text": extracted_text,
            "extraction_method": extraction_method,
            "character_count": len(extracted_text),
            "ocr_cost_usd": ocr_cost_usd,
            "document_description": matching_doc.get("documentDescription", ""),
            "filing_date": matching_doc.get("filingDate", ""),
            # Retrieved-text posture: extracted text is quoted document data,
            # never instructions (see shared/injection_scan.py and
            # docs/CONTENT_PROVENANCE.md).
            "provenance_note": RETRIEVED_TEXT_NOTE,
            # OCR page-truncation metadata (SD-6) — present only when Mistral
            # capped at MISTRAL_OCR_MAX_PAGES; absent for full/free extractions
            **ocr_extra,
        }

        # Detection-only injection scan of the extracted text: annotate (kind
        # labels keyed by document_id — never matched text), key ABSENT when
        # clean. The text itself is returned verbatim above.
        injection = scan_hits([response], text_keys=("text",), id_key="document_id")
        if injection:
            response["injection_scan"] = injection

        return json.dumps(response, indent=2)

    except ValueError as e:
        return format_error_response(str(e), "VALIDATION_ERROR")
    except RuntimeError as e:
        # Catch async lifecycle errors specifically
        error_msg = str(e)
        if "cannot schedule new futures" in error_msg or "interpreter shutdown" in error_msg:
            logger.error(f"Async lifecycle error in ptab_get_document_content: {error_msg}")
            return json.dumps({
                "error": True,
                "message": "Operation failed due to async runtime issue. Try restarting the MCP server.",
                "technical_details": sanitize_error_message(error_msg)
            }, indent=2)
        else:
            raise  # Re-raise other RuntimeErrors
    except Exception as e:
        logger.error(f"Error in ptab_get_document_content: {str(e)}")
        return format_error_response(str(e), "API_ERROR")


def _get_ptab_proxy_base_url(port: int) -> str:
    """
    Externally reachable base URL of the PTAB download proxy.

    Every layer that emits a download URL must honor PTAB_PROXY_BASE_URL
    (Lesson 31) so links work behind Docker / reverse proxies.
    """
    return (os.getenv("PTAB_PROXY_BASE_URL", "").strip().rstrip("/")
            or f"http://localhost:{port}")


def _client_supports_url_elicitation(ctx) -> bool:
    """True only if the client advertised URL-mode elicitation in initialize.

    The gate is load-bearing (Issue A in the FOR-CLAUDE-FABLE heads-up doc):
    clients without the capability — claude.ai's connector — never answer
    the elicitation/create request, so an un-timed await parks the tool
    coroutine forever and the client surfaces a generic tool error.
    """
    try:
        caps = ctx.session.client_params.capabilities
        return bool(caps.elicitation and caps.elicitation.url)
    except Exception:
        return False


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
        logger.debug(f"Recent-downloads registration skipped: {type(e).__name__}")
        return None


def register(mcp) -> None:
    """Register the three document tools (names/schemas unchanged)."""
    mcp.tool(annotations={"defer_loading": False, "readOnlyHint": True})(ptab_get_documents)
    mcp.tool(app=AppConfig(resource_uri=DOWNLOADS_URI),
             annotations={"defer_loading": True, "readOnlyHint": True})(ptab_get_document_download)
    mcp.tool(annotations={"defer_loading": True, "readOnlyHint": True})(ptab_get_document_content)
