"""
OCR Service for extracting content from PTAB documents using Mistral API

This service handles OCR operations for PTAB proceeding documents (trials, appeals, interferences)
using the Mistral OCR API with rate limiting and cost tracking.
"""
import httpx
import os
import time
from typing import Dict, Any, Optional
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

        # OCR rate limiting configuration
        self.ocr_calls = []  # List of timestamps for OCR calls
        self.ocr_rate_limit = 10  # Max OCR calls per minute
        self.ocr_window = 60  # Time window in seconds

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

    def _check_ocr_rate_limit(self) -> bool:
        """
        Check if OCR rate limit is exceeded.

        Returns:
            True if rate limit allows request, False otherwise
        """
        now = time.time()

        # Clean old calls outside the time window
        self.ocr_calls = [ts for ts in self.ocr_calls if now - ts < self.ocr_window]

        if len(self.ocr_calls) >= self.ocr_rate_limit:
            oldest_call = min(self.ocr_calls)
            wait_time = self.ocr_window - (now - oldest_call)
            logger.warning(f"OCR rate limit exceeded. {len(self.ocr_calls)} calls in last {self.ocr_window}s. "
                          f"Try again in {wait_time:.0f} seconds.")
            return False

        # Record this call
        self.ocr_calls.append(now)
        logger.info(f"OCR rate limit check passed. {len(self.ocr_calls)}/{self.ocr_rate_limit} calls in window")
        return True

    async def extract_document_content(
        self,
        pdf_content: bytes,
        page_count: int,
        identifier: str,
        document_id: str
    ) -> Dict[str, Any]:
        """
        Extract document content using Mistral OCR API

        Args:
            pdf_content: PDF content as bytes
            page_count: Number of pages in the document
            identifier: PTAB proceeding identifier (trial/appeal/interference number)
            document_id: Document identifier

        Returns:
            Dictionary containing OCR-extracted content and metadata

        Cost Calculation:
            - Mistral OCR: ~$1 per 1000 pages
            - Example costs:
              - Final Written Decision (45 pages): ~$0.045
              - Petition (100 pages): ~$0.10
              - Complete docket (500 pages): ~$0.50
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

            # Check OCR rate limit before proceeding
            if not self._check_ocr_rate_limit():
                oldest_call = min(self.ocr_calls) if self.ocr_calls else time.time()
                wait_time = self.ocr_window - (time.time() - oldest_call)
                return {
                    "success": False,
                    "error": "Rate limit exceeded",
                    "message": (
                        f"OCR rate limit exceeded. Maximum {self.ocr_rate_limit} calls per "
                        f"{self.ocr_window} seconds. Try again in {int(wait_time) + 1} seconds."
                    ),
                    "retry_after_seconds": int(wait_time) + 1
                }

            logger.info(f"Starting OCR extraction for {identifier}/{document_id} ({page_count} pages)")

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

            async with httpx.AsyncClient(timeout=120.0) as client:
                upload_response = await client.post(
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

                # Step 2: Process with OCR
                # Limit to first 50 pages for cost control (configurable)
                max_pages = min(page_count, 50)

                ocr_payload = {
                    "model": "mistral-ocr-latest",
                    "document": {
                        "type": "file",
                        "file_id": file_id
                    },
                    "pages": list(range(max_pages)),
                    "include_image_base64": False  # Save tokens
                }

                ocr_response = await client.post(
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

                # Combine all page content
                extracted_content = []
                for page in ocr_data.get("pages", []):
                    page_markdown = page.get("markdown", "")
                    if page_markdown.strip():
                        extracted_content.append(f"=== PAGE {page.get('index', 0) + 1} ===\n{page_markdown}")

                full_content = "\n\n".join(extracted_content)

                logger.info(f"OCR extraction successful: {len(full_content)} chars, "
                           f"{pages_processed} pages, ${estimated_cost:.4f} cost")

                return {
                    "success": True,
                    "identifier": identifier,
                    "document_id": document_id,
                    "page_count": page_count,
                    "pages_processed": pages_processed,
                    "extracted_content": full_content,
                    "structured_output": "markdown",
                    "processing_cost_usd": round(estimated_cost, 4),
                    "cost_breakdown": f"${estimated_cost:.4f} for {pages_processed} pages at $0.001/page",
                    "ocr_model": ocr_data.get("model", "mistral-ocr-latest"),
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
                return {
                    "success": False,
                    "error": f"HTTP {e.response.status_code}",
                    "message": f"Mistral API error {e.response.status_code}: {e.response.text}"
                }
        except Exception as e:
            logger.error(f"OCR extraction failed: {str(e)}")
            return {
                "success": False,
                "error": "Extraction failed",
                "message": f"Failed to extract document content with Mistral OCR: {str(e)}"
            }
