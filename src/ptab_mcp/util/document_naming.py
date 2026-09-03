"""Document filename and description derivation, shared by both consumers.

`generate_enhanced_filename` used to live in `proxy/server.py`, so
`tools/documents.py` imported a pure string function out of an ASGI server
module — dragging FastAPI, uvicorn plumbing and module-level proxy state into
every tool import, including under stdio where the proxy may never run — and
inverting the layering to tool -> proxy -> api (Q-6). It also blocked the fix
for the duplicated description logic, because the proxy cannot import back from
`tools`.

`derive_document_description` is that duplicate, single-sourced (D-3). The two
copies had already drifted on the substantive point: the proxy read the appeal
category off the PARENT bag item while the tool read it off the FLATTENED
document, so the same appeal paper downloaded through
PTAB_get_document_download and through /download/{type}/{id}/{doc} could come
back with two different filenames.
"""

import re
from typing import Any, Dict, Optional


def derive_document_description(
    doc: Dict[str, Any], parent: Optional[Dict[str, Any]] = None
) -> str:
    """Human-readable description for one document, for filename generation.

    Field names vary by proceeding type:
      - trials: documentTitleText, trialDocumentCategory
      - appeals: appealDocumentCategory
      - interferences: documentName

    The category is read from the parent bag item FIRST and the flattened
    document second, so both call sites agree regardless of which shape they
    hold. Returns "" when nothing matches; callers decide their own sentinel.
    """
    parent = parent or {}
    description = (
        doc.get("documentTitleText")                       # trials (most specific)
        or parent.get("appealDocumentCategory")            # appeals: "Decision"
        or doc.get("appealDocumentCategory")
        or parent.get("trialDocumentCategory")             # trials: "PETITION", etc.
        or doc.get("trialDocumentCategory")
        or doc.get("documentCategory")
        or doc.get("documentTypeDescriptionText")          # fallback: "Paper"
        or ""
    )
    if not description and doc.get("documentName"):
        # e.g. "Decision_2025000943_09-18-2025.pdf" -> "Decision"
        stem = doc["documentName"]
        if stem.endswith(".pdf"):
            stem = stem[:-4]
        description = stem.split("_")[0] if "_" in stem else stem
    return description


def sanitize_description(description: str, max_length: int = 40) -> str:
    """
    Sanitize document description for filename.

    Args:
        description: Raw document description from API
        max_length: Maximum characters (default 40)

    Returns:
        Sanitized description safe for filenames
    """
    if not description:
        return "DOCUMENT"

    # Convert to uppercase
    clean = description.upper()

    # Replace spaces with underscores
    clean = clean.replace(' ', '_')

    # Remove special characters except underscore and hyphen
    clean = re.sub(r'[^A-Z0-9_-]', '', clean)

    # Remove duplicate underscores
    clean = re.sub(r'_+', '_', clean)

    # Truncate to max length
    clean = clean[:max_length]

    # Remove trailing underscores/hyphens
    clean = clean.rstrip('_-')

    return clean


def generate_enhanced_filename(
    filing_date: Optional[str],
    identifier: str,
    patent_number: Optional[str],
    document_description: str,
    document_code: Optional[str] = None,
    max_desc_length: int = 40
) -> str:
    """
    Generate enhanced filename for PTAB documents.

    Format: PTAB-{date}_{identifier}_{patent}_{description}.pdf
    Example: PTAB-2024-08-23_IPR2024-01353_PAT-7883848_FINAL_WRITTEN_DECISION.pdf

    Args:
        filing_date: Filing/proceeding date (YYYY-MM-DD format)
        identifier: Trial/appeal/interference number
        patent_number: Patent number (if granted, else None)
        document_description: Document description from API
        document_code: Document code (fallback)
        max_desc_length: Max chars for description (default 40)

    Returns:
        Safe filename for download
    """
    components = []

    # Add date prefix if available
    if filing_date and filing_date.strip():
        # Extract just the date portion (handles ISO format with time)
        date_part = filing_date.split('T')[0] if 'T' in filing_date else filing_date
        components.append(f"PTAB-{date_part}")
    else:
        components.append("PTAB-UNKNOWN")

    # Add identifier (trial/appeal/interference number)
    components.append(identifier or "UNKNOWN")

    # Add patent number if available
    if patent_number and patent_number.strip():
        components.append(f"PAT-{patent_number}")

    # Sanitize description (use document_code as fallback)
    desc = document_description or document_code or "DOCUMENT"
    desc_clean = sanitize_description(desc, max_desc_length)
    components.append(desc_clean)

    # Join and add extension. Sanitize the ASSEMBLED name, not just the
    # description component: filing_date and patent_number are interpolated
    # from API data and land in Content-Disposition and X-Enhanced-Filename,
    # where a CR/LF or a quote is header injection (CWE-93/CWE-116).
    filename = re.sub(r"[^A-Za-z0-9._-]", "", "_".join(components))

    return (filename or "PTAB-DOCUMENT") + ".pdf"
