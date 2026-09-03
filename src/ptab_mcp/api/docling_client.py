"""Docling-serve REST client for PTAB PDF OCR extraction.

Posts PDF bytes to a running docling-serve instance via /v1/convert/file.
Supports local Docker (e.g. http://localhost:5001) or remote instances
(e.g. https://docling.example.com).

Docling is the third extraction tier (pypdf -> Mistral OCR -> Docling) and
is intended for SHORT scanned filings only. PTAB documents run large (IPR
petitions up to 60 pages, responses up to 80, exhibits 100-300+) and EasyOCR
processing scales ~10-30s/page on CPU — larger documents should go to
Mistral OCR instead, which is why DOCLING_MAX_PAGES defaults to 20 here
(Lesson 19).

Env vars:
    DOCLING_SERVE_URL   – Base URL of the docling-serve instance.
    DOCLING_TIMEOUT     – Read timeout in seconds for OCR processing (default: 300).
                          Increase for very large documents, e.g. DOCLING_TIMEOUT=600.
    DOCLING_MAX_PAGES   – Skip Docling for documents exceeding this page count
                          (default: 20). Prevents tool call timeouts on large
                          scanned documents; Claude Desktop's tool timeout is
                          ~5-10 minutes.
"""

import os
import httpx
from typing import Optional

from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

_DEFAULT_TIMEOUT = 300.0   # 5 minutes — EasyOCR scales ~10-30s/page on CPU
_DEFAULT_MAX_PAGES = 20    # PTAB docs run large; push anything bigger to Mistral


def _env_float(name: str, default: float) -> float:
    """Parse a float env var, falling back to the default on garbage."""
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("Invalid %s, using default %s", name, default)
        return default


def _env_int(name: str, default: int) -> int:
    """Parse an int env var, falling back to the default on garbage."""
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("Invalid %s, using default %s", name, default)
        return default


class DoclingClient:
    """REST client for docling-serve PDF extraction.

    Accepts raw PDF bytes and posts them to the docling-serve
    /v1/convert/file endpoint, returning plain text.
    """

    def __init__(self) -> None:
        self.url: Optional[str] = os.getenv("DOCLING_SERVE_URL", "").strip() or None
        # DoclingClient() is constructed at runtime.py import, i.e. at import of
        # every tool module, so an unguarded float()/int() here meant
        # DOCLING_TIMEOUT=5m took the whole server down with a ValueError
        # traceback before a single tool registered. Every sibling env parse in
        # the repo guards this (ptab_client.py, ocr_service.py).
        self.timeout = _env_float("DOCLING_TIMEOUT", _DEFAULT_TIMEOUT)
        self.max_pages = _env_int("DOCLING_MAX_PAGES", _DEFAULT_MAX_PAGES)

    def is_available(self) -> bool:
        """Return True if DOCLING_SERVE_URL is configured."""
        return bool(self.url)

    def within_page_limit(self, page_count: int) -> bool:
        """Return True if page_count is within the DOCLING_MAX_PAGES threshold."""
        return page_count <= self.max_pages

    async def extract(self, pdf_content: bytes, filename: str = "document.pdf") -> str:
        """Send PDF bytes to docling-serve and return extracted plain text.

        Args:
            pdf_content: Raw PDF bytes.
            filename: Filename hint sent to the server (default: document.pdf).

        Returns:
            Extracted plain text (non-empty).

        Raises:
            ValueError: If Docling is not configured, the server returns an
                        error, or the extracted text is empty.
            httpx.HTTPError: On network errors.
        """
        if not self.is_available():
            raise ValueError(
                "Docling extraction is not configured. "
                "Set DOCLING_SERVE_URL to enable (e.g. http://localhost:5001 "
                "or https://docling.example.com)."
            )

        url = f"{self.url.rstrip('/')}/v1/convert/file"
        logger.info(f"Sending {filename} ({len(pdf_content)} bytes) to docling-serve: {url}")

        # Use split timeouts: short connect (10s), long read (DOCLING_TIMEOUT) for OCR processing.
        # Write timeout is generous (60s) for large PDF uploads over slower connections.
        timeout = httpx.Timeout(connect=10.0, read=self.timeout, write=60.0, pool=5.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    url,
                    files={"files": (filename, pdf_content, "application/pdf")},
                    # /v1/convert/file takes options as individual multipart
                    # form fields (NOT a JSON options blob). Always request
                    # placeholder image mode — the default 'embedded' inlines
                    # base64 images and bloats the output.
                    data={
                        "to_formats": "text",
                        "abort_on_error": "false",
                        "image_export_mode": "placeholder",
                    },
                )
                response.raise_for_status()

            data = response.json()
            status = data.get("status", "unknown")

            if status == "failure":
                errors = data.get("errors", [])
                raise ValueError(f"Docling conversion failed: {errors}")

            text = (data.get("document") or {}).get("text_content") or ""

            if not text.strip():
                raise ValueError(
                    f"Docling returned empty text for {filename} (status={status}). "
                    "The document may be encrypted, corrupted, or an unsupported format."
                )

            logger.info(f"Docling extracted {len(text)} chars from {filename} (status={status})")
            return text.strip()

        except httpx.ConnectError:
            raise ValueError(
                f"Could not connect to docling-serve at {self.url}. "
                "Check that the server is running and DOCLING_SERVE_URL is correct "
                "(e.g. http://localhost:5001 or https://docling.example.com)."
            )
        except httpx.TimeoutException:
            raise ValueError(
                f"Docling timed out processing {filename} after {self.timeout:.0f}s. "
                "Large scanned documents take longer with EasyOCR (~10-30s/page on CPU). "
                f"Increase the limit by setting DOCLING_TIMEOUT=600 (or higher) in your MCP config."
            )
        except httpx.HTTPStatusError as exc:
            raise ValueError(
                f"Docling server returned HTTP {exc.response.status_code}: "
                f"{exc.response.text[:200]}"
            ) from exc

    async def health_check(self) -> bool:
        """Return True if the docling server is reachable and healthy."""
        if not self.is_available():
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.url.rstrip('/')}/health")
                return resp.status_code == 200
        except Exception:
            return False
