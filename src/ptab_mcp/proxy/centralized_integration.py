"""
Centralized proxy integration for PTAB document registration with PFW.

This module handles registration of PTAB documents with the centralized
USPTO PFW proxy for unified download infrastructure across MCPs.
"""

import httpx
import os
import re
from typing import Optional
from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


def get_centralized_base_url() -> Optional[str]:
    """
    Resolve the base URL of the PFW centralized proxy.

    Priority:
    1. CENTRALIZED_PROXY_URL — full base URL. Required whenever PFW is not on
       this host's localhost (Docker: http://pfw:8080; remote: an external
       HTTPS base behind a reverse proxy).
    2. CENTRALIZED_PROXY_PORT — legacy port-only config, resolved against
       localhost.

    Returns:
        Base URL string without trailing slash, or None if centralized
        proxying is not configured ("none"/unset).
    """
    url = os.getenv("CENTRALIZED_PROXY_URL", "").strip()
    if url and url.lower() != "none":
        if not re.match(r"^https?://", url):
            logger.warning(f"Invalid CENTRALIZED_PROXY_URL (must be http/https): {url}")
            return None
        return url.rstrip("/")

    port_env = os.getenv("CENTRALIZED_PROXY_PORT", "none").lower()
    if port_env == "none" or not port_env:
        return None
    try:
        return f"http://localhost:{int(port_env)}"
    except ValueError:
        logger.warning(f"Invalid CENTRALIZED_PROXY_PORT: {port_env}")
        return None


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
        centralized_base_url = get_centralized_base_url()
        if not centralized_base_url:
            logger.debug(
                "Centralized proxy not configured "
                "(set CENTRALIZED_PROXY_URL or CENTRALIZED_PROXY_PORT)"
            )
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
        registration_url = f"{centralized_base_url}/register-ptab-document"

        # Build headers
        headers = {"Content-Type": "application/json"}

        logger.info(
            f"Attempting centralized registration: {identifier_type} {identifier}, "
            f"doc {document_id} to {centralized_base_url}"
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
                    # Never log the URL — persistent links are credentials
                    logger.info("✅ Centralized registration successful")
                    return proxy_url
                else:
                    logger.warning("Registration succeeded but no download URL in response")
                    return None
            else:
                # Status only — response bodies stay out of logs
                logger.warning(
                    f"Centralized registration failed: HTTP {response.status_code}"
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


# NOTE: generate_enhanced_filename lives in proxy.server (single canonical
# implementation). The duplicate that used to live here was removed during
# the FastMCP 3.0 migration (Lesson 10-adjacent dedup).
