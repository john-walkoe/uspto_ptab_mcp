"""
OCR Service for extracting content from PTAB documents using Mistral API

This service handles OCR operations for PTAB proceeding documents (trials, appeals, interferences)
using the Mistral OCR API with rate limiting and cost tracking.
"""
import asyncio
import random

import httpx
import os
import time
from typing import Any, Awaitable, Callable, Dict, Optional
from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


class OCRService:
    """Service for handling OCR operations with Mistral API"""

    def __init__(self):
        """Initialize OCR service with rate limiting"""
        # Mistral OCR configuration - check secure storage first, then environment
        raw_mistral_key = None
        try:
            from ..shared_secure_storage import get_mistral_api_key
            raw_mistral_key = get_mistral_api_key()
        except Exception:
            # Fall back to environment variable if secure storage fails
            pass

        # If still no key, try environment variable
        if not raw_mistral_key:
            raw_mistral_key = os.getenv("MISTRAL_API_KEY")

        self.mistral_api_key = self._validate_mistral_api_key(raw_mistral_key)
        self.mistral_base_url = "https://api.mistral.ai/v1"
        # Mistral OCR model slug. Default `mistral-ocr-latest` tracks Mistral's
        # current GA model (= OCR 4 as of 2026-06-23); pin to a dated slug
        # (e.g. mistral-ocr-2503, mistral-ocr-4-0) via MISTRAL_OCR_MODEL.
        self.mistral_ocr_model = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")

        # HTTP timeout for Mistral upload+OCR calls (RF-4: env-configurable
        # for parity with DOCLING_TIMEOUT)
        try:
            self.mistral_timeout = float(os.getenv("MISTRAL_OCR_TIMEOUT", "120.0"))
        except ValueError:
            logger.warning("Invalid MISTRAL_OCR_TIMEOUT, using default 120.0")
            self.mistral_timeout = 120.0

        # Cost-control page cap per document (SD-6: was a silent hard 50)
        try:
            self.max_ocr_pages = max(1, int(os.getenv("MISTRAL_OCR_MAX_PAGES", "50")))
        except ValueError:
            logger.warning("Invalid MISTRAL_OCR_MAX_PAGES, using default 50")
            self.max_ocr_pages = 50

        # OCR rate limiting configuration — throttled PER CALLER identity
        # (M-4, CWE-799): one tenant's burst can no longer exhaust the shared
        # budget for every other tenant in a multi-user HTTP deployment.
        self.ocr_calls: Dict[str, list] = {}  # caller_id -> call timestamps
        self.ocr_rate_limit = 10  # Max OCR calls per minute per caller
        self.ocr_window = 60  # Time window in seconds

        # Rolling DAILY budget per caller (PT-28). The per-minute window bounds
        # a burst but nothing bounded the cumulative total: one authorized
        # caller sustaining the minute limit runs 14,400 calls a day, visible
        # only in a server-side log line nobody reads. 0 disables the cap.
        try:
            self.ocr_daily_limit = max(0, int(os.getenv("PTAB_OCR_DAILY_LIMIT", "500")))
        except ValueError:
            logger.warning("Invalid PTAB_OCR_DAILY_LIMIT, using default 500")
            self.ocr_daily_limit = 500
        self.ocr_day_window = 86400
        self.ocr_daily_calls: Dict[str, list] = {}

    def _validate_mistral_api_key(self, raw_key: Optional[str]) -> Optional[str]:
        """
        Validate Mistral API key and detect common placeholder patterns.

        Args:
            raw_key: Raw API key from environment variable

        Returns:
            Valid API key or None if invalid/placeholder
        """
        if not raw_key:
            return None

        # Common placeholder patterns that should be treated as missing
        placeholder_patterns = [
            "your_mistral_api_key_here",
            "your_key_here",
            "your_api_key_here",
            "placeholder",
            "optional",
            "mistral_api_key",
            "enter_your_key",
            "add_your_key",
            "your_mistral_key",
            "api_key_here",
            "replace_with_your_key",
            "insert_key_here",
            "temp_key",
            "test_key",
            "example_key"
        ]

        normalized_key = raw_key.lower().strip()

        # Check against placeholder patterns
        for pattern in placeholder_patterns:
            if pattern in normalized_key:
                logger.info(f"Detected placeholder pattern '{pattern}' in MISTRAL_API_KEY. Treating as missing key.")
                return None

        # Additional check for very short keys that are likely placeholders
        if len(raw_key.strip()) < 10:
            logger.info(f"Detected suspiciously short API key ({len(raw_key)} chars). Treating as missing key.")
            return None

        return raw_key.strip()

    #: Upstream statuses worth another attempt. A 4xx that is not 429 will not
    #: become a 200, and 401/402 are handled as their own envelopes upstream.
    _RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
    _RETRY_ATTEMPTS = 3

    async def _post_with_retry(self, client, url: str, **kwargs):
        """POST with bounded backoff on transient failures.

        Mistral was the one paid tier with no retry at all (RF-7): a single
        connection reset discarded a 120-second operation the user had already
        waited for, and the caller then saw the document reported as a scanned
        image. Retries do NOT re-count against the caller's OCR budget —
        _check_ocr_rate_limit runs once per extract_document_content, above
        this — so a retry storm cannot consume someone's allowance.
        """
        last_exc = None
        for attempt in range(self._RETRY_ATTEMPTS):
            try:
                response = await client.post(url, **kwargs)
                if (response.status_code in self._RETRY_STATUSES
                        and attempt < self._RETRY_ATTEMPTS - 1):
                    logger.warning(
                        "Mistral OCR %s returned %d; retrying (attempt %d/%d)",
                        url.rsplit("/", 1)[-1], response.status_code,
                        attempt + 1, self._RETRY_ATTEMPTS,
                    )
                else:
                    return response
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt == self._RETRY_ATTEMPTS - 1:
                    raise
                logger.warning(
                    "Mistral OCR %s failed (%s); retrying (attempt %d/%d)",
                    url.rsplit("/", 1)[-1], type(exc).__name__,
                    attempt + 1, self._RETRY_ATTEMPTS,
                )
            await asyncio.sleep(2 ** attempt + random.uniform(0.1, 0.5))
        if last_exc is not None:  # pragma: no cover - defensive
            raise last_exc
        return response

    def _check_ocr_rate_limit(self, caller_id: str = "default") -> bool:
        """
        Check if the caller's OCR rate limit is exceeded (per-identity, M-4).

        Args:
            caller_id: Stable identity of the caller (authenticated email in
                OAuth mode, process-local sentinel otherwise).

        Returns:
            True if rate limit allows request, False otherwise
        """
        now = time.time()

        # Clean old calls outside the time window; drop idle callers so the
        # dict cannot grow unbounded across many identities
        for key in list(self.ocr_calls):
            fresh = [ts for ts in self.ocr_calls[key] if now - ts < self.ocr_window]
            if fresh:
                self.ocr_calls[key] = fresh
            else:
                del self.ocr_calls[key]

        calls = self.ocr_calls.get(caller_id, [])
        if len(calls) >= self.ocr_rate_limit:
            oldest_call = min(calls)
            wait_time = self.ocr_window - (now - oldest_call)
            logger.warning(f"OCR rate limit exceeded for caller. {len(calls)} calls in last "
                          f"{self.ocr_window}s. Try again in {wait_time:.0f} seconds.")
            return False

        # Rolling 24h budget, swept the same way (PT-28)
        if self.ocr_daily_limit:
            for key in list(self.ocr_daily_calls):
                fresh_day = [ts for ts in self.ocr_daily_calls[key]
                             if now - ts < self.ocr_day_window]
                if fresh_day:
                    self.ocr_daily_calls[key] = fresh_day
                else:
                    del self.ocr_daily_calls[key]
            day_calls = self.ocr_daily_calls.get(caller_id, [])
            if len(day_calls) >= self.ocr_daily_limit:
                logger.warning(
                    "OCR DAILY budget exhausted for caller: %d calls in the last "
                    "24h (PTAB_OCR_DAILY_LIMIT=%d).",
                    len(day_calls), self.ocr_daily_limit,
                )
                return False
            self.ocr_daily_calls.setdefault(caller_id, []).append(now)

        # Record this call
        self.ocr_calls.setdefault(caller_id, []).append(now)
        logger.info(f"OCR rate limit check passed. {len(calls) + 1}/{self.ocr_rate_limit} calls in window")
        return True

    def _rate_limit_wait_seconds(self, caller_id: str = "default") -> int:
        """Seconds until the caller's oldest in-window call expires."""
        calls = self.ocr_calls.get(caller_id, [])
        if not calls:
            return 1
        return max(1, int(self.ocr_window - (time.time() - min(calls))) + 1)

    def _resolve_page_window(self, page_count: Optional[int]) -> tuple:
        """(known_page_count, pages_to_request, truncated) for one document.

        A page count of None means USPTO metadata carried none AND the PDF
        bytes would not parse. That case requests the cap as an explicit
        bounded range and is reported TRUNCATED against a null total —
        previously a fabricated count of 50 made `truncated = 50 > 50` read
        false, so a capped 300-page exhibit looked complete.
        """
        known = page_count if isinstance(page_count, int) and page_count > 0 else None
        if known is None:
            return None, self.max_ocr_pages, True
        pages = min(known, self.max_ocr_pages)
        return known, pages, known > pages

    def _truncation_note(self, known_page_count: Optional[int], max_pages: int) -> str:
        """Caller-facing explanation of an OCR page cap."""
        if known_page_count is not None:
            return (
                f"Document has {known_page_count} pages; OCR processed the "
                f"first {max_pages} (MISTRAL_OCR_MAX_PAGES limit)."
            )
        return (
            "The document's page count could not be determined, so OCR was "
            f"capped at {max_pages} pages (MISTRAL_OCR_MAX_PAGES limit); the "
            "extracted text may be incomplete."
        )

    @staticmethod
    def _join_ocr_pages(pages: list) -> str:
        """Join OCR page markdown under `=== PAGE N ===` headers.

        The header is emitted for EVERY page, including ones OCR returned
        empty: it used to live inside the non-blank branch, so a page that
        produced no text vanished without a trace and the surviving page
        numbers implied a complete document.
        """
        parts = []
        for page in pages:
            page_markdown = page.get("markdown", "")
            page_label = f"=== PAGE {page.get('index', 0) + 1} ==="
            if page_markdown.strip():
                parts.append(f"{page_label}\n{page_markdown}")
            else:
                parts.append(f"{page_label}\n[no text recovered from this page]")
        return "\n\n".join(parts)

    async def extract_document_content(
        self,
        pdf_content: bytes,
        page_count: Optional[int],
        identifier: str,
        document_id: str,
        progress_cb: Optional[Callable[[float, float, str], Awaitable[None]]] = None,
        caller_id: str = "default"
    ) -> Dict[str, Any]:
        """
        Extract document content using Mistral OCR API

        Args:
            pdf_content: PDF content as bytes
            page_count: Number of pages in the document, or None when it could
                not be determined. Unknown is handled honestly: OCR requests an
                explicit MISTRAL_OCR_MAX_PAGES range and the result is marked
                truncated with a null total, rather than a fabricated count
                making `truncated = count > cap` read false.
            identifier: PTAB proceeding identifier (trial/appeal/interference number)
            document_id: Document identifier
            progress_cb: Optional async callback(progress, total, message) for
                MCP progress notifications. Kept framework-agnostic (Lesson 20) —
                the caller wires it to ctx.report_progress.

        Returns:
            Dictionary containing OCR-extracted content and metadata
            (including internal per-page cost accounting — server-side only,
            never surfaced in tool responses)
        """
        try:
            # Check if Mistral API key is available
            if not self.mistral_api_key:
                return {
                    "success": False,
                    "error": "MISTRAL_API_KEY not configured",
                    "message": (
                        "MISTRAL_API_KEY environment variable is required for OCR content extraction. "
                        "Set it with: set MISTRAL_API_KEY=your_key_here (Windows) or "
                        "export MISTRAL_API_KEY=your_key_here (Linux/Mac)"
                    )
                }

            # Check the caller's OCR rate limit before proceeding (M-4)
            if not self._check_ocr_rate_limit(caller_id):
                wait_time = self._rate_limit_wait_seconds(caller_id)
                return {
                    "success": False,
                    "error": "Rate limit exceeded",
                    "message": (
                        f"OCR rate limit exceeded. Maximum {self.ocr_rate_limit} calls per "
                        f"{self.ocr_window} seconds. Try again in {wait_time} seconds."
                    ),
                    "retry_after_seconds": wait_time
                }

            known_page_count, ocr_max_pages, ocr_truncated = self._resolve_page_window(page_count)
            page_label = f"{known_page_count}-page" if known_page_count else "unknown-length"
            logger.info(
                f"Starting OCR extraction for {identifier}/{document_id} ({page_label})"
            )

            if progress_cb:
                await progress_cb(50, 100, f"Uploading {page_label} PDF to Mistral OCR...")

            # Step 1: Upload file to Mistral
            mistral_headers = {
                "Authorization": f"Bearer {self.mistral_api_key}",
            }

            files = {
                "file": ("document.pdf", pdf_content, "application/pdf")
            }

            data = {
                "purpose": "ocr"
            }

            async with httpx.AsyncClient(timeout=self.mistral_timeout) as client:
                upload_response = await self._post_with_retry(
                    client,
                    f"{self.mistral_base_url}/files",
                    headers=mistral_headers,
                    files=files,
                    data=data
                )
                upload_response.raise_for_status()
                upload_data = upload_response.json()
                file_id = upload_data.get("id")

                if not file_id:
                    return {
                        "success": False,
                        "error": "Upload failed",
                        "message": "Failed to upload file to Mistral OCR service"
                    }

                # Step 2: Process with OCR. Page window resolved above by
                # _resolve_page_window (cost control: MISTRAL_OCR_MAX_PAGES).
                max_pages, truncated = ocr_max_pages, ocr_truncated

                if progress_cb:
                    await progress_cb(65, 100, f"Running Mistral OCR on {max_pages} pages...")

                ocr_payload = {
                    "model": self.mistral_ocr_model,
                    "document": {
                        "type": "file",
                        "file_id": file_id
                    },
                    "pages": list(range(max_pages)),
                    "include_image_base64": False  # Save tokens
                }

                ocr_response = await self._post_with_retry(
                    client,
                    f"{self.mistral_base_url}/ocr",
                    headers={
                        "Authorization": f"Bearer {self.mistral_api_key}",
                        "Content-Type": "application/json"
                    },
                    json=ocr_payload
                )
                ocr_response.raise_for_status()
                ocr_data = ocr_response.json()

                # Extract content from OCR response
                pages_processed = ocr_data.get("usage_info", {}).get("pages_processed", 0)
                estimated_cost = pages_processed * 0.001  # $1 per 1000 pages

                # Combine all page content under `=== PAGE N ===` headers
                # (every page, including blank ones — see _join_ocr_pages).
                full_content = self._join_ocr_pages(ocr_data.get("pages", []))

                logger.info(f"OCR extraction successful: {len(full_content)} chars, "
                           f"{pages_processed} pages, ${estimated_cost:.4f} cost")

                truncation_note = self._truncation_note(known_page_count, max_pages)

                return {
                    "success": True,
                    "identifier": identifier,
                    "document_id": document_id,
                    # Null, never a fabricated default, when the real count is
                    # unknown — the caller reports it as unknown.
                    "page_count": known_page_count,
                    "pages_requested": max_pages,
                    "pages_processed": pages_processed,
                    # Surface truncation (SD-6) instead of silently returning
                    # a partial document as if it were complete
                    "truncated": truncated,
                    **({"truncation_note": truncation_note} if truncated else {}),
                    "extracted_content": full_content,
                    "structured_output": "markdown",
                    "processing_cost_usd": round(estimated_cost, 4),
                    "cost_breakdown": f"${estimated_cost:.4f} for {pages_processed} pages at $0.001/page",
                    "ocr_model": ocr_data.get("model", self.mistral_ocr_model),
                    "file_size_bytes": len(pdf_content),
                    "usage_info": ocr_data.get("usage_info", {}),
                    "note": "Content extracted using Mistral OCR - supports scanned documents, formulas, and complex layouts"
                }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {
                    "success": False,
                    "error": "Authentication failed",
                    "message": "Mistral API authentication failed - check MISTRAL_API_KEY"
                }
            elif e.response.status_code == 402:
                return {
                    "success": False,
                    "error": "Payment required",
                    "message": "Mistral API payment required - insufficient credits"
                }
            else:
                # Truncate the upstream body (L-6, CWE-209) — full provider
                # error pages can carry internal infrastructure details
                return {
                    "success": False,
                    "error": f"HTTP {e.response.status_code}",
                    "message": f"Mistral API error {e.response.status_code}: {e.response.text[:200]}"
                }
        except Exception as e:
            logger.error(f"OCR extraction failed: {str(e)}")
            return {
                "success": False,
                "error": "Extraction failed",
                "message": f"Failed to extract document content with Mistral OCR: {str(e)}"
            }
