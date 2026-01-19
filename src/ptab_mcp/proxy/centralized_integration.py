"""
Centralized proxy integration for PTAB document registration with PFW.

This module handles registration of PTAB documents with the centralized
USPTO PFW proxy for unified download infrastructure across MCPs.
"""

import httpx
import logging
import os
from typing import Optional, Dict, Any
from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


async def register_with_centralized_proxy(
    identifier: str,
    identifier_type: str,
    document_id: str,
    download_url: str,
    api_key: str,
    patent_number: Optional[str] = None,
    application_number: Optional[str] = None,
    enhanced_filename: Optional[str] = None,
    internal_auth_secret: Optional[str] = None
) -> Optional[str]:
    """
    Register PTAB document with PFW centralized proxy.

    Args:
        identifier: Trial/appeal/interference number (e.g., 'IPR2025-01054')
        identifier_type: One of: trial, appeal, interference
        document_id: Document identifier from API
        download_url: USPTO API download URL (HTTPS)
        api_key: USPTO API key (used to generate access token)
        patent_number: Patent number if available
        application_number: Application number if available
        enhanced_filename: Human-readable filename
        internal_auth_secret: JWT secret for authentication

    Returns:
        Centralized proxy URL if successful, None if registration failed
    """
    try:
        # Check if centralized proxy is configured
        centralized_port_env = os.getenv("CENTRALIZED_PROXY_PORT", "none").lower()

        if centralized_port_env == "none":
            logger.debug("Centralized proxy not configured (CENTRALIZED_PROXY_PORT=none)")
            return None

        # Parse port
        try:
            if centralized_port_env:
                centralized_port = int(centralized_port_env)
            else:
                # Try default PFW port
                centralized_port = 8080
        except ValueError:
            logger.warning(f"Invalid CENTRALIZED_PROXY_PORT: {centralized_port_env}")
            return None

        # Check for internal auth secret
        if not internal_auth_secret:
            logger.warning("No internal auth secret available for centralized registration")
            return None

        # Generate JWT access token
        try:
            from ..shared.internal_auth import mcp_auth
            access_token = mcp_auth.create_service_token(
                target_service="pfw-proxy",
                metadata={"source": "ptab", "document_id": document_id}
            )
        except Exception as e:
            logger.warning(f"Failed to generate access token: {e}")
            return None

        # Map identifier_type to proceeding_type
        # identifier_type: "trial", "appeal", "interference"
        # proceeding_type: "IPR", "PGR", "CBM", "DER", "Appeal"
        proceeding_type = None
        if identifier_type == "trial":
            # Extract type from trial number (IPR2025-01054 -> IPR)
            if identifier.startswith("IPR"):
                proceeding_type = "IPR"
            elif identifier.startswith("PGR"):
                proceeding_type = "PGR"
            elif identifier.startswith("CBM"):
                proceeding_type = "CBM"
            elif identifier.startswith("DER"):
                proceeding_type = "DER"
        elif identifier_type == "appeal":
            proceeding_type = "Appeal"
        # Interference doesn't have a specific type

        # Build registration payload matching PFW's expected format
        registration_payload = {
            "source": "ptab",
            "proceeding_number": identifier,  # PFW expects "proceeding_number" not "identifier"
            "document_identifier": document_id,
            "download_url": download_url,
            "access_token": access_token,  # PFW expects "access_token" not "api_key"
            "patent_number": patent_number,
            "application_number": application_number,
            "proceeding_type": proceeding_type,
            "enhanced_filename": enhanced_filename
        }

        # Remove None values
        registration_payload = {k: v for k, v in registration_payload.items() if v is not None}

        # Build registration URL (PFW uses /register-ptab-document not /register/ptab)
        registration_url = f"http://localhost:{centralized_port}/register-ptab-document"

        # Build headers
        headers = {"Content-Type": "application/json"}

        logger.info(
            f"Attempting centralized registration: {identifier_type} {identifier}, "
            f"doc {document_id} to port {centralized_port}"
        )

        # Attempt registration with timeout
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(
                registration_url,
                json=registration_payload,
                headers=headers
            )

            if response.status_code == 200:
                # Parse response to get download URL
                response_data = response.json()
                proxy_url = response_data.get("download_url")

                if proxy_url:
                    logger.info(f"✅ Centralized registration successful: {proxy_url}")
                    return proxy_url
                else:
                    logger.warning("Registration succeeded but no download URL in response")
                    return None
            else:
                logger.warning(
                    f"Centralized registration failed: HTTP {response.status_code} - {response.text}"
                )
                return None

    except httpx.TimeoutException:
        logger.warning("Centralized proxy registration timed out (3s)")
        return None
    except httpx.ConnectError:
        logger.debug("Centralized proxy not available (connection refused)")
        return None
    except Exception as e:
        logger.warning(f"Centralized registration error: {str(e)}")
        return None


def generate_enhanced_filename(
    identifier: str,
    identifier_type: str,
    document_description: str,
    document_code: Optional[str] = None,
    filing_date: Optional[str] = None,
    patent_number: Optional[str] = None
) -> str:
    """
    Generate enhanced human-readable filename for PTAB documents.

    Format: PTAB-{date}_{identifier}_{patent}_{description}.pdf
    Example: PTAB-2025-01-05_IPR2025-01054_PAT-8524787_FINAL_WRITTEN_DECISION.pdf

    Args:
        identifier: Trial/appeal/interference number
        identifier_type: One of: trial, appeal, interference
        document_description: Document description from API
        document_code: Document code (if available)
        filing_date: Filing date (ISO format)
        patent_number: Patent number (if available)

    Returns:
        Enhanced filename with .pdf extension
    """
    components = []

    # Date component
    if filing_date:
        # Clean date (remove time if present)
        date_clean = filing_date.split("T")[0] if "T" in filing_date else filing_date
        components.append(f"PTAB-{date_clean}")
    else:
        components.append("PTAB-UNKNOWN")

    # Identifier component
    components.append(identifier)

    # Patent number component
    if patent_number:
        components.append(f"PAT-{patent_number}")

    # Description component (sanitized)
    desc_clean = _sanitize_description(document_description, max_length=40)
    if desc_clean:
        components.append(desc_clean)
    elif document_code:
        components.append(document_code)
    else:
        components.append("DOCUMENT")

    filename = "_".join(components) + ".pdf"

    # Ensure filename is valid (no invalid chars, max 255)
    filename = filename[:255]

    return filename


def _sanitize_description(description: str, max_length: int = 40) -> str:
    """
    Sanitize document description for use in filename.

    Args:
        description: Raw document description
        max_length: Maximum length for description component

    Returns:
        Sanitized description (uppercase, safe chars only)
    """
    if not description:
        return ""

    # Convert to uppercase
    clean = description.upper()

    # Replace spaces and special chars with underscores
    clean = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in clean
    )

    # Remove consecutive underscores
    while "__" in clean:
        clean = clean.replace("__", "_")

    # Trim to max length
    clean = clean[:max_length]

    # Remove leading/trailing underscores
    clean = clean.strip("_")

    return clean
