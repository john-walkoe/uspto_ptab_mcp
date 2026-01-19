"""
FastAPI HTTP server for secure PTAB document downloads.

Provides browser-accessible download URLs while keeping USPTO API keys secure.
Supports three identifier types: trial, appeal, interference.
Port configuration via PTAB_PROXY_PORT environment variable (default: 8083).
"""

import logging
import re
import os
import time
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware
import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from ..api.ptab_client import PTABClient
from .rate_limiter import rate_limiter
from ..shared.error_utils import generate_request_id
from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

# Request size limit configuration
MAX_REQUEST_SIZE = 1024 * 1024  # 1MB limit

# Global client instance
api_client = None


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
    Example: PTAB-2024-05-15_IPR2024-00123_PAT-8524787_FINAL_WRITTEN_DECISION.pdf

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

    # Join and add extension
    filename = "_".join(components) + ".pdf"

    return filename


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to all responses."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)

        # Add security headers
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to limit request body size for security.

    Prevents DoS attacks via large request bodies.
    """

    def __init__(self, app, max_request_size: int = MAX_REQUEST_SIZE):
        super().__init__(app)
        self.max_request_size = max_request_size

    async def dispatch(self, request: Request, call_next):
        """Check request size and reject if too large."""
        # Get Content-Length header if present
        content_length = request.headers.get('content-length')

        if content_length:
            content_length = int(content_length)
            if content_length > self.max_request_size:
                # Log security event
                client_ip = request.client.host if request.client else "unknown"
                request_id = generate_request_id()

                logger.warning(
                    f"[{request_id}] Request body too large: {content_length} bytes from {client_ip}"
                )

                return JSONResponse(
                    status_code=413,  # Payload Too Large
                    content={
                        "error": True,
                        "message": f"Request body too large. Maximum size: {self.max_request_size} bytes",
                        "content_length": content_length,
                        "max_allowed": self.max_request_size,
                        "request_id": request_id
                    }
                )

        return await call_next(request)


def create_lifespan(api_key: Optional[str] = None):
    """Create lifespan context manager with API key."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Manage application lifespan."""
        global api_client
        try:
            # Use provided API key or fall back to environment variable
            api_client = PTABClient(api_key=api_key) if api_key else PTABClient()
            logger.info("USPTO PTAB API client initialized for proxy server")
            yield
        except Exception as e:
            logger.error(f"Failed to initialize USPTO PTAB API client: {e}")
            raise
    return lifespan


def create_proxy_app(api_key: Optional[str] = None, port: Optional[int] = None) -> FastAPI:
    """
    Create FastAPI application for PTAB document proxy.

    Args:
        api_key: Optional USPTO API key (from secure storage).
                 If not provided, will attempt to load from environment.
        port: Optional port number for health check response.
              If not provided, reads from PTAB_PROXY_PORT or PROXY_PORT.
    """
    app = FastAPI(
        title="USPTO PTAB Document Proxy",
        description="Secure proxy for USPTO PTAB document downloads",
        version="1.0.0",
        lifespan=create_lifespan(api_key)
    )

    # Store port in app state for health check
    def safe_parse_port() -> int:
        """Safely parse proxy port, handling 'none' sentinel value."""
        port_str = os.getenv('PTAB_PROXY_PORT') or os.getenv('PROXY_PORT') or '8083'
        # CRITICAL: Check "none" sentinel BEFORE int conversion
        if port_str.lower() == 'none':
            return 8083
        try:
            return int(port_str)
        except ValueError:
            logger.warning(f"Invalid port '{port_str}', using default 8083")
            return 8083

    app.state.port = port if port is not None else safe_parse_port()

    # Add request size limit middleware (BEFORE other middleware)
    app.add_middleware(RequestSizeLimitMiddleware, max_request_size=MAX_REQUEST_SIZE)

    # Add security headers middleware
    app.add_middleware(SecurityHeadersMiddleware)

    # Add CORS middleware with strict origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8080",  # PFW centralized proxy
            "http://127.0.0.1:8080"
        ],
        allow_credentials=True,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "service": "PTAB Document Proxy",
            "port": app.state.port,
            "note": f"Runs on port {app.state.port} (configurable via PTAB_PROXY_PORT or PROXY_PORT)"
        }

    @app.get("/download/{identifier_type}/{identifier}/{document_id}")
    async def download_document(
        identifier_type: str,
        identifier: str,
        document_id: str,
        request: Request
    ):
        """
        Proxy endpoint for downloading USPTO PTAB documents.

        This endpoint handles authentication with the USPTO API and streams
        the PDF content directly to the browser, enabling direct downloads
        while keeping API keys secure.

        Args:
            identifier_type: Type of identifier (trial, appeal, interference)
            identifier: Trial/appeal/interference number
            document_id: Document ID from documentBag
            request: FastAPI request object (for client IP)
        """
        try:
            # Get client IP for rate limiting
            client_ip = request.client.host if request.client else "unknown"

            # Apply rate limiting
            if not rate_limiter.is_allowed(client_ip):
                remaining_time = max(1, int(rate_limiter.get_reset_time(client_ip) - time.time()))
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": True,
                        "message": "Rate limit exceeded. USPTO allows 5 downloads per 10 seconds.",
                        "retry_after": remaining_time,
                        "remaining_requests": 0
                    },
                    headers={"Retry-After": str(int(remaining_time))}
                )

            # Log download request
            logger.info(
                f"Proxying download for {identifier_type} {identifier}, "
                f"doc {document_id}, IP {client_ip}"
            )

            # Get documents for the identifier using correct API methods
            # NOTE: Appeals and interferences use decisions endpoints (not separate documents endpoints)
            if identifier_type == "trial":
                raw_response = await api_client.get_trial_documents(identifier)
                doc_bag_key = "patentTrialDocumentDataBag"
            elif identifier_type == "appeal":
                # Appeals use get_appeal_decisions (not get_appeal_documents)
                raw_response = await api_client.get_appeal_decisions(identifier)
                doc_bag_key = "patentAppealDataBag"
            elif identifier_type == "interference":
                # Interferences use get_interference_decisions (not get_interference_documents)
                raw_response = await api_client.get_interference_decisions(identifier)
                doc_bag_key = "patentInterferenceDataBag"
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid identifier_type: {identifier_type}"
                )

            if raw_response.get('error'):
                raise HTTPException(
                    status_code=404,
                    detail=raw_response.get('error', 'Documents not found')
                )

            # Extract documents from response - documents are nested inside documentData
            data_bag = raw_response.get(doc_bag_key, [])
            if not data_bag:
                raise HTTPException(
                    status_code=404,
                    detail=f'No documents found for {identifier_type} {identifier}'
                )

            # Find target document by extracting documentData from each bag item
            # Keep reference to parent item for metadata (patent number, etc.)
            target_doc = None
            parent_item = None
            for item in data_bag:
                doc_data = item.get('documentData', {})
                if doc_data.get('documentIdentifier') == document_id:
                    target_doc = doc_data
                    parent_item = item
                    break

            if not target_doc:
                raise HTTPException(
                    status_code=404,
                    detail=f"Document with ID '{document_id}' not found"
                )

            # Get download URL
            download_url = target_doc.get('fileDownloadURI')
            if not download_url:
                raise HTTPException(
                    status_code=404,
                    detail="Download URL not available"
                )

            # Get document metadata for enhanced filename using correct field names
            # Field names vary by identifier type:
            # - Trials: documentTitleText, trialDocumentCategory
            # - Appeals: appealDocumentCategory, decisionData.decisionTypeCategory
            # - Interferences: documentName
            # Priority: specific title > category from parent > generic type
            doc_description = (
                target_doc.get('documentTitleText') or  # Trials (most specific)
                (parent_item.get('appealDocumentCategory') if parent_item else None) or  # Appeals: "Decision"
                (parent_item.get('trialDocumentCategory') if parent_item else None) or  # Trials: "PETITION", etc.
                target_doc.get('documentCategory') or
                target_doc.get('documentTypeDescriptionText') or  # Fallback: "Paper"
                ''
            )
            # Use documentName as fallback (e.g., "Decision_2025000943_09-18-2025.pdf")
            if not doc_description and target_doc.get('documentName'):
                # Extract meaningful part from filename (before extension, replace underscores)
                doc_name = target_doc.get('documentName', '')
                if doc_name.endswith('.pdf'):
                    doc_name = doc_name[:-4]
                doc_description = doc_name.split('_')[0] if '_' in doc_name else doc_name

            doc_code = target_doc.get('documentCategory', '')

            # Get filing date from document data
            filing_date = target_doc.get('documentFilingDate')

            # Get patent number from parent item's patentOwnerData (trials)
            # or appellantData (appeals) or interferenceMetaData (interferences)
            patent_number = None
            if parent_item:
                if identifier_type == "trial":
                    patent_owner_data = parent_item.get('patentOwnerData', {})
                    patent_number = patent_owner_data.get('patentNumber')
                elif identifier_type == "appeal":
                    appellant_data = parent_item.get('appellantData', {})
                    patent_number = appellant_data.get('patentNumber')
                # Interferences typically don't have a single patent number

            # Generate enhanced filename
            filename = generate_enhanced_filename(
                filing_date=filing_date,
                identifier=identifier,
                patent_number=patent_number,
                document_description=doc_description,
                document_code=doc_code,
                max_desc_length=40
            )

            # Stream the PDF from USPTO API
            async def stream_pdf():
                async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                    headers = {
                        "X-API-KEY": api_client.api_key,
                        "Accept": "application/pdf"
                    }
                    async with client.stream("GET", download_url, headers=headers) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            yield chunk

            # Set appropriate headers for PDF download
            response_headers = {
                "Content-Type": "application/pdf",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Identifier-Type": identifier_type,
                "X-Identifier": identifier,
                "X-Document-ID": document_id,
                "X-Enhanced-Filename": filename
            }

            logger.info(f"Streaming PDF: {filename}")

            return StreamingResponse(
                stream_pdf(),
                media_type="application/pdf",
                headers=response_headers,
                background=BackgroundTask(
                    lambda: logger.info(f"Download completed: {filename}")
                )
            )

        except HTTPException:
            raise
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                logger.error(
                    f"USPTO API authentication failed for {identifier_type} "
                    f"{identifier}/{document_id}"
                )
                raise HTTPException(
                    status_code=502,
                    detail="Authentication failed with USPTO API"
                )
            else:
                logger.error(f"USPTO API error {e.response.status_code}: {e.response.text}")
                raise HTTPException(
                    status_code=502,
                    detail=f"USPTO API error: {e.response.status_code}"
                )
        except Exception as e:
            logger.error(
                f"Proxy download failed for {identifier_type} {identifier}/{document_id}: {e}"
            )
            raise HTTPException(
                status_code=500,
                detail=f"Download failed: {str(e)}"
            )

    @app.get("/rate-limit/{client_ip}")
    async def check_rate_limit(client_ip: str):
        """Check rate limit status for a client IP."""
        return {
            "client_ip": client_ip,
            "remaining_requests": rate_limiter.get_remaining_requests(client_ip),
            "max_requests": rate_limiter.max_requests,
            "time_window": rate_limiter.time_window,
            "reset_time": rate_limiter.get_reset_time(client_ip)
        }

    return app


def run_proxy_cli():
    """CLI entry point for proxy server."""
    import uvicorn
    import sys

    def safe_parse_port() -> int:
        """Safely parse proxy port, handling 'none' sentinel value."""
        port_str = os.getenv('PTAB_PROXY_PORT') or os.getenv('PROXY_PORT') or '8083'
        if port_str.lower() == 'none':
            return 8083
        try:
            return int(port_str)
        except ValueError:
            logger.warning(f"Invalid port '{port_str}', using default 8083")
            return 8083

    default_port = safe_parse_port()
    port = default_port

    # Check for port argument (command line overrides environment variables)
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            logger.warning(f"Invalid port: {sys.argv[1]}, using default {default_port}")
            port = default_port

    logger.info(f"Starting USPTO PTAB Document Proxy on port {port}...")
    logger.info(f"Health check: http://localhost:{port}/")
    logger.info(f"Port {port} (configurable via PTAB_PROXY_PORT or PROXY_PORT)")

    uvicorn.run(
        "ptab_mcp.proxy.server:create_proxy_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        log_level="info"
    )
