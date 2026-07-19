"""
USPTO PTAB API Client for Open Data Portal

Client for accessing the USPTO Patent Trial and Appeal Board (PTAB) API via ODP.
Supports trials (IPR/PGR/CBM), appeals, and interferences.
Requires USPTO API key (X-API-KEY header).
"""

import asyncio
import httpx
import os
import random
from typing import Dict, Any, List, Optional
from ..shared.error_utils import format_error_response, generate_request_id
from ..shared.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from ..shared.cache import CacheManager
from ..shared.safe_logger import get_safe_logger
from ..shared.uspto_shared_rate_limiter import get_shared_limiter
from ..config import api_constants
from ..validation.validators import validate_timeout

logger = get_safe_logger(__name__)


class PTABClient:
    """Client for USPTO PTAB API (Open Data Portal)"""

    # Constants
    DEFAULT_LIMIT = 25
    MAX_SEARCH_LIMIT = 200
    MAX_CONCURRENT_REQUESTS = 10

    # Retry configuration
    RETRY_ATTEMPTS = 3
    RETRY_DELAY = 1.0  # Base delay in seconds
    RETRY_BACKOFF = 2  # Exponential backoff multiplier

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize PTAB client with USPTO API key

        Args:
            api_key: USPTO API key (optional, will fallback to secure storage/env)

        Raises:
            ValueError: If no API key found in any location
        """
        self.base_url = "https://api.uspto.gov/api/v1/patent"

        # Load API key with unified secure storage support
        self.api_key = None

        if api_key:
            self.api_key = api_key
        else:
            # Try unified secure storage first
            try:
                from ..shared_secure_storage import get_uspto_api_key
                self.api_key = get_uspto_api_key()
            except Exception:
                # Fall back to environment variable
                pass

            # If still no key, try environment variable
            if not self.api_key:
                self.api_key = os.getenv("USPTO_API_KEY")

        if not self.api_key:
            raise ValueError(
                "USPTO API key is required. Please provide via parameter, "
                "secure storage, or USPTO_API_KEY environment variable"
            )

        self.headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # Configurable timeouts from environment variables (with bounds checking)
        # Security: Validates timeouts to prevent DoS (CWE-400) and service failures
        try:
            default_timeout_raw = float(os.getenv("USPTO_TIMEOUT", "30.0"))
            self.default_timeout = validate_timeout(default_timeout_raw, min_timeout=5.0, max_timeout=120.0)
        except ValueError as e:
            logger.warning(f"Invalid USPTO_TIMEOUT: {e}. Using default 30.0s")
            self.default_timeout = 30.0

        try:
            download_timeout_raw = float(os.getenv("USPTO_DOWNLOAD_TIMEOUT", "60.0"))
            self.download_timeout = validate_timeout(download_timeout_raw, min_timeout=10.0, max_timeout=300.0)
        except ValueError as e:
            logger.warning(f"Invalid USPTO_DOWNLOAD_TIMEOUT: {e}. Using default 60.0s")
            self.download_timeout = 60.0

        # Retry attempts configurable via env (RF-3) — single source of truth
        # alongside USPTO_TIMEOUT / USPTO_DOWNLOAD_TIMEOUT above
        try:
            self.retry_attempts = max(1, min(10, int(os.getenv("USPTO_MAX_RETRIES", str(self.RETRY_ATTEMPTS)))))
        except ValueError:
            logger.warning("Invalid USPTO_MAX_RETRIES, using default 3")
            self.retry_attempts = self.RETRY_ATTEMPTS

        logger.info(
            f"Timeout configuration: default={self.default_timeout}s, "
            f"download={self.download_timeout}s, retries={self.retry_attempts}"
        )

        # Connection pool limits to prevent exhaustion under high load
        self.connection_limits = httpx.Limits(
            max_connections=api_constants.DEFAULT_MAX_CONNECTIONS,
            max_keepalive_connections=api_constants.DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
            keepalive_expiry=api_constants.DEFAULT_KEEPALIVE_EXPIRY_SECONDS
        )
        logger.info(
            f"Connection pool limits: max={self.connection_limits.max_connections}, "
            f"keepalive={self.connection_limits.max_keepalive_connections}"
        )

        # Service-specific semaphores for better resource isolation
        self.uspto_semaphore = asyncio.Semaphore(api_constants.USPTO_MAX_CONCURRENT_REQUESTS)
        self.mistral_semaphore = asyncio.Semaphore(api_constants.MISTRAL_MAX_CONCURRENT_REQUESTS)

        # Circuit breakers for resilience (separate for each data type)
        self.trials_circuit_breaker = CircuitBreaker(
            failure_threshold=api_constants.USPTO_CIRCUIT_BREAKER_THRESHOLD,
            recovery_timeout=api_constants.USPTO_CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
            name="PTAB_Trials"
        )
        self.appeals_circuit_breaker = CircuitBreaker(
            failure_threshold=api_constants.USPTO_CIRCUIT_BREAKER_THRESHOLD,
            recovery_timeout=api_constants.USPTO_CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
            name="PTAB_Appeals"
        )
        self.interferences_circuit_breaker = CircuitBreaker(
            failure_threshold=api_constants.USPTO_CIRCUIT_BREAKER_THRESHOLD,
            recovery_timeout=api_constants.USPTO_CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
            name="PTAB_Interferences"
        )
        self.mistral_circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=30,
            name="Mistral_OCR"
        )

        # Cache manager for circuit breaker fallback
        self.cache_manager = CacheManager(
            maxsize=api_constants.DEFAULT_CACHE_SIZE,
            ttl=api_constants.DEFAULT_CACHE_TTL_SECONDS
        )

        logger.info(
            "PTAB client initialized with USPTO API key, semaphores, "
            "circuit breakers, and cache"
        )

    def get_circuit_breaker_status(self) -> Dict[str, Any]:
        """Get status of all circuit breakers for monitoring"""
        return {
            "trials": self.trials_circuit_breaker.get_state(),
            "appeals": self.appeals_circuit_breaker.get_state(),
            "interferences": self.interferences_circuit_breaker.get_state(),
            "mistral_ocr": self.mistral_circuit_breaker.get_state()
        }

    async def _send_once(self, method: str, url: str, request_timeout: float, **kwargs) -> "httpx.Response":
        """Perform exactly one HTTP send. Extracted out of _make_request's
        retry loop into its own method (rather than a nested closure) so its
        branches are counted toward ITS OWN cyclomatic complexity instead of
        _make_request's — mechanical decomposition, no behavior change.

        Shared cross-process rate limiter (token + concurrency slot), one
        acquire per ATTEMPT — off unless USPTO_SHARED_RATE_LIMIT_DIR is set.
        This is the single choke point around the actual outbound USPTO HTTP
        send.
        """
        async with httpx.AsyncClient(
            timeout=request_timeout,
            verify=True,
            limits=self.connection_limits,
            follow_redirects=True  # Handle 302 redirects to S3 signed URLs
        ) as client:
            if method.upper() == "POST":
                send = client.post(url, headers=self.headers, **kwargs)
            else:
                send = client.get(url, headers=self.headers, **kwargs)
            limiter = get_shared_limiter()
            if limiter is not None:
                async with limiter:
                    return await send
            return await send

    async def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        circuit_breaker: Optional[CircuitBreaker] = None,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Make HTTP request to PTAB API with rate limiting and retry logic

        Args:
            endpoint: API endpoint path
            method: HTTP method (GET or POST)
            circuit_breaker: Circuit breaker to use (optional)
            timeout: Request timeout in seconds (optional, uses default if None)
            **kwargs: Additional arguments for httpx request

        Returns:
            Dict containing API response or error response

        Note:
            - Uses exponential backoff with jitter for retries
            - Implements circuit breaker pattern for resilience
            - Caches successful responses for fallback when circuit is open
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        request_id = generate_request_id()
        request_timeout = timeout if timeout is not None else self.default_timeout

        logger.info(f"[{request_id}] Starting {method} request to {endpoint}")

        # Use appropriate circuit breaker (default to trials if not specified)
        cb = circuit_breaker if circuit_breaker else self.trials_circuit_breaker

        # Use USPTO-specific semaphore
        async def _execute_request():
            async with self.uspto_semaphore:
                last_exception = None

                for attempt in range(self.retry_attempts):
                    try:
                        response = await self._send_once(method, url, request_timeout, **kwargs)
                        response.raise_for_status()
                        logger.info(f"[{request_id}] Request successful on attempt {attempt + 1}")
                        return response.json()

                    except httpx.HTTPStatusError as e:
                        # Don't retry authentication errors or client errors (4xx)
                        if e.response.status_code < 500:
                            # Status only — response bodies stay out of logs
                            # (the returned error keeps the API detail for the user)
                            logger.error(
                                f"[{request_id}] API error {e.response.status_code}"
                            )
                            return format_error_response(
                                f"API error: {e.response.text}",
                                e.response.status_code,
                                request_id
                            )
                        last_exception = e

                    except httpx.TimeoutException as e:
                        last_exception = e

                    except Exception as e:
                        last_exception = e

                    # Calculate delay with exponential backoff and jitter
                    if attempt < self.retry_attempts - 1:
                        delay = self.RETRY_DELAY * (self.RETRY_BACKOFF ** attempt)
                        # Add jitter to prevent thundering herd
                        jitter = random.uniform(0.1, 0.5)
                        total_delay = delay + jitter

                        logger.warning(
                            f"[{request_id}] Request failed on attempt {attempt + 1}/"
                            f"{self.retry_attempts}, retrying in {total_delay:.2f}s: "
                            f"{str(last_exception)}"
                        )
                        await asyncio.sleep(total_delay)

                # All retries failed — RAISE so the circuit breaker records
                # the failure (EF-1/RF-1: returning a formatted error dict
                # here looked like success to cb.call(), so the breaker
                # could never open for the dominant failure mode). The
                # user-facing formatting happens in the outer handler.
                raise last_exception if last_exception else RuntimeError(
                    "Request failed with no recorded exception"
                )

        # Execute through circuit breaker with cache fallback. Retry-exhausted
        # failures arrive here as exceptions (after the breaker recorded
        # them) and are formatted for the caller.
        try:
            result = await cb.call(_execute_request)

            # Cache successful responses for circuit breaker fallback
            if result and not result.get("error"):
                cache_key = f"{method}_{endpoint}"
                self.cache_manager.set(cache_key, result, **kwargs)
                logger.debug(f"[{request_id}] Cached response for {cache_key}")

            return result

        except CircuitBreakerOpenError as e:
            # Typed OPEN signal (EH-4) — attempt stale-cache fallback
            logger.warning(f"[{request_id}] Circuit OPEN - attempting cache fallback")

            cache_key = f"{method}_{endpoint}"
            cached_result = self.cache_manager.get(cache_key, **kwargs)

            if cached_result:
                logger.info(f"[{request_id}] Serving stale cached response (circuit OPEN)")

                # Add metadata to indicate cached/degraded response
                cached_result = cached_result.copy()
                cached_result["_cached"] = True
                cached_result["_circuit_open"] = True
                cached_result["_warning"] = (
                    "Serving cached data - USPTO API temporarily unavailable"
                )
                cached_result["request_id"] = request_id

                return cached_result

            logger.error(f"[{request_id}] No cached fallback available for {cache_key}")
            return format_error_response(
                f"Service temporarily unavailable: {str(e)}",
                503,
                request_id
            )

        except httpx.TimeoutException:
            logger.error(
                f"[{request_id}] Request timeout after {self.retry_attempts} attempts"
            )
            return format_error_response(
                "Request timeout - please try again",
                408,
                request_id
            )

        except httpx.HTTPStatusError as e:
            logger.error(
                f"[{request_id}] API error {e.response.status_code} "
                f"after {self.retry_attempts} attempts"
            )
            return format_error_response(
                f"API error: {e.response.text}",
                e.response.status_code,
                request_id
            )

        except Exception as e:
            logger.error(
                f"[{request_id}] Request failed after {self.retry_attempts} "
                f"attempts: {str(e)}"
            )
            return format_error_response(
                f"Request failed: {str(e)}",
                500,
                request_id
            )

    async def _search(
        self,
        endpoint: str,
        circuit_breaker: CircuitBreaker,
        label: str,
        filters: Optional[List[Dict[str, Any]]] = None,
        range_filters: Optional[List[Dict[str, Any]]] = None,
        sort: Optional[List[Dict[str, str]]] = None,
        pagination: Optional[Dict[str, int]] = None,
        fields: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Shared POST-search body for trials/appeals/interferences (dedup 2.3)."""
        try:
            body = {
                "pagination": pagination or {
                    "offset": 0,
                    "limit": self.DEFAULT_LIMIT
                }
            }
            if filters:
                body["filters"] = filters
            if range_filters:
                body["rangeFilters"] = range_filters
            if sort:
                body["sort"] = sort
            if fields:
                body["fields"] = fields

            # Content minimization: log the request SHAPE (our own field names),
            # never filter values — party names etc. are client work-product
            logger.debug(
                f"{label} search shape: filters={[f['name'] for f in body.get('filters', [])]}, "
                f"range_filters={len(body.get('rangeFilters', []))}, "
                f"fields={len(body.get('fields', []))}, pagination={body.get('pagination')}"
            )

            return await self._make_request(
                endpoint,
                method="POST",
                circuit_breaker=circuit_breaker,
                json=body
            )

        except Exception as e:
            logger.error(f"Error in search_{label.lower()}s: {str(e)}")
            return format_error_response(str(e), 500, generate_request_id())

    async def _download_document(self, file_download_uri: str, doc_type: str) -> bytes:
        """Shared document download body (dedup 1.2).

        Args:
            file_download_uri: Full download URL from document metadata
            doc_type: "trial" | "appeal" | "interference" (log label only)

        Returns:
            Raw PDF bytes

        Raises:
            httpx.HTTPStatusError: If download fails
        """
        try:
            request_id = generate_request_id()
            logger.info(f"[{request_id}] Downloading {doc_type} document")

            async with httpx.AsyncClient(
                timeout=self.download_timeout,
                verify=True,
                limits=self.connection_limits,
                follow_redirects=True  # Handle 302 redirects to S3 signed URLs
            ) as client:
                send = client.get(file_download_uri, headers=self.headers)

                # Shared cross-process rate limiter (token + concurrency
                # slot), one acquire per attempt — off unless
                # USPTO_SHARED_RATE_LIMIT_DIR is set. Single choke point
                # around the actual outbound USPTO document download.
                limiter = get_shared_limiter()
                if limiter is not None:
                    async with limiter:
                        response = await send
                else:
                    response = await send

                response.raise_for_status()
                logger.info(f"[{request_id}] Downloaded {len(response.content)} bytes")
                return response.content

        except Exception as e:
            logger.error(f"Error downloading {doc_type} document: {str(e)}")
            raise

    # ==========================================
    # TRIALS ENDPOINTS (5 endpoints)
    # ==========================================

    async def search_trials(
        self,
        filters: Optional[List[Dict[str, Any]]] = None,
        range_filters: Optional[List[Dict[str, Any]]] = None,
        sort: Optional[List[Dict[str, str]]] = None,
        pagination: Optional[Dict[str, int]] = None,
        fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Search trial proceedings (IPR, PGR, CBM)

        Args:
            filters: List of filter objects with 'name' and 'value'
            range_filters: List of range filters with 'field', 'valueFrom', 'valueTo'
            sort: List of sort specifications with 'field' and 'order'
            pagination: Dict with 'offset' and 'limit'
            fields: Optional list of fields to retrieve for context reduction

        Returns:
            Dict containing search results with patentTrialProceedingDataBag

        Example:
            filters = [{
                "name": "trialMetaData.trialStatusCategory",
                "value": ["Institution Denied"]
            }]
            range_filters = [{
                "field": "respondentData.grantDate",
                "valueFrom": "2023-01-01",
                "valueTo": "2024-12-31"
            }]
        """
        return await self._search(
            "trials/proceedings/search",
            circuit_breaker=self.trials_circuit_breaker,
            label="Trial",
            filters=filters,
            range_filters=range_filters,
            sort=sort,
            pagination=pagination,
            fields=fields,
        )

    async def get_trial_proceeding(
        self,
        trial_number: str
    ) -> Dict[str, Any]:
        """
        Get specific trial proceeding by trial number

        Args:
            trial_number: Trial number (e.g., "IPR2024-00123")

        Returns:
            Dict containing trial proceeding details
        """
        try:
            return await self._make_request(
                f"trials/proceedings/{trial_number}",
                method="GET",
                circuit_breaker=self.trials_circuit_breaker
            )

        except Exception as e:
            logger.error(f"Error in get_trial_proceeding: {str(e)}")
            return format_error_response(str(e), 500, generate_request_id())

    async def search_trial_documents(
        self,
        trial_number: str,
        offset: int = 0,
        limit: int = 25,
        sort_order: str = "desc"
    ) -> Dict[str, Any]:
        """
        Search documents for a specific trial using the POST search endpoint.
        Supports true server-side pagination and sort — use this instead of
        get_trial_documents for proceedings with 25+ documents.

        Args:
            trial_number: Trial number (e.g., "IPR2024-00123")
            offset: Zero-based starting record index (default: 0)
            limit: Number of documents to return (default: 25, max: 100 —
                   the API rejects larger pages with HTTP 400)
            sort_order: "asc" (oldest first) or "desc" (newest first)

        Returns:
            Dict with patentTrialDocumentDataBag and count
        """
        try:
            # API rejects limit > 100 with 400 "Requested page limit exceeds allowed limit 100"
            limit = min(limit, 100)
            body = {
                "filters": [{"name": "trialNumber", "value": [trial_number]}],
                "pagination": {"offset": offset, "limit": limit},
                "sort": [{"field": "documentData.documentFilingDate", "order": sort_order}]
            }
            # Trial number is a public identifier — allowed in logs
            logger.debug(
                f"Document search: trial {trial_number}, offset={offset}, limit={limit}"
            )
            return await self._make_request(
                "trials/documents/search",
                method="POST",
                circuit_breaker=self.trials_circuit_breaker,
                json=body
            )

        except Exception as e:
            logger.error(f"Error in search_trial_documents: {str(e)}")
            return format_error_response(str(e), 500, generate_request_id())

    async def search_all_trial_documents(
        self,
        trial_number: str,
        max_docs: int = 500
    ) -> Dict[str, Any]:
        """
        Fetch all documents for a trial, paginating past the API's 100-per-page cap.

        Args:
            trial_number: Trial number (e.g., "IPR2024-00123")
            max_docs: Safety cap on total documents fetched (default: 500)

        Returns:
            Dict with the merged patentTrialDocumentDataBag and the API's count
        """
        first = await self.search_trial_documents(trial_number, offset=0, limit=100)
        bag = first.get("patentTrialDocumentDataBag") or []
        total = first.get("count") or len(bag)
        offset = len(bag)
        while bag and offset < min(total, max_docs):
            page = await self.search_trial_documents(trial_number, offset=offset, limit=100)
            page_bag = page.get("patentTrialDocumentDataBag") or []
            if not page_bag:
                break
            bag.extend(page_bag)
            offset += len(page_bag)
        first["patentTrialDocumentDataBag"] = bag
        return first

    async def get_trial_documents(
        self,
        trial_number: str
    ) -> Dict[str, Any]:
        """
        Get documents for a trial via the GET convenience endpoint.
        Returns ~25 documents with no pagination support — use
        search_trial_documents() for full paginated access.

        Args:
            trial_number: Trial number (e.g., "IPR2024-00123")

        Returns:
            Dict containing list of documents with metadata
        """
        try:
            return await self._make_request(
                f"trials/{trial_number}/documents",
                method="GET",
                circuit_breaker=self.trials_circuit_breaker
            )

        except Exception as e:
            logger.error(f"Error in get_trial_documents: {str(e)}")
            return format_error_response(str(e), 500, generate_request_id())

    async def get_trial_decisions(
        self,
        trial_number: str
    ) -> Dict[str, Any]:
        """
        Get all decisions for a specific trial

        Args:
            trial_number: Trial number (e.g., "IPR2024-00123")

        Returns:
            Dict containing list of decisions
        """
        try:
            return await self._make_request(
                f"trials/{trial_number}/decisions",
                method="GET",
                circuit_breaker=self.trials_circuit_breaker
            )

        except Exception as e:
            logger.error(f"Error in get_trial_decisions: {str(e)}")
            return format_error_response(str(e), 500, generate_request_id())

    async def download_trial_document(
        self,
        file_download_uri: str
    ) -> bytes:
        """
        Download a trial document from fileDownloadURI

        Args:
            file_download_uri: Full download URL from document metadata

        Returns:
            Raw PDF bytes

        Raises:
            httpx.HTTPStatusError: If download fails
        """
        return await self._download_document(file_download_uri, "trial")

    # ==========================================
    # APPEALS ENDPOINTS (3 endpoints)
    # ==========================================

    async def search_appeals(
        self,
        filters: Optional[List[Dict[str, Any]]] = None,
        range_filters: Optional[List[Dict[str, Any]]] = None,
        sort: Optional[List[Dict[str, str]]] = None,
        pagination: Optional[Dict[str, int]] = None,
        fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Search appeal decisions

        Args:
            filters: List of filter objects with 'name' and 'value'
            range_filters: List of range filters with 'field', 'valueFrom', 'valueTo'
            sort: List of sort specifications with 'field' and 'order'
            pagination: Dict with 'offset' and 'limit'
            fields: Optional list of fields to retrieve for context reduction

        Returns:
            Dict containing search results with patentAppealDataBag
        """
        return await self._search(
            "appeals/decisions/search",
            circuit_breaker=self.appeals_circuit_breaker,
            label="Appeal",
            filters=filters,
            range_filters=range_filters,
            sort=sort,
            pagination=pagination,
            fields=fields,
        )

    async def get_appeal_decisions(
        self,
        appeal_number: str
    ) -> Dict[str, Any]:
        """
        Get all decisions for a specific appeal

        Args:
            appeal_number: Appeal number (8 digits)

        Returns:
            Dict containing list of decisions
        """
        try:
            return await self._make_request(
                f"appeals/{appeal_number}/decisions",
                method="GET",
                circuit_breaker=self.appeals_circuit_breaker
            )

        except Exception as e:
            logger.error(f"Error in get_appeal_decisions: {str(e)}")
            return format_error_response(str(e), 500, generate_request_id())

    async def download_appeal_document(
        self,
        file_download_uri: str
    ) -> bytes:
        """
        Download an appeal document from fileDownloadURI

        Args:
            file_download_uri: Full download URL from document metadata

        Returns:
            Raw PDF bytes

        Raises:
            httpx.HTTPStatusError: If download fails
        """
        return await self._download_document(file_download_uri, "appeal")

    # ==========================================
    # INTERFERENCES ENDPOINTS (3 endpoints)
    # ==========================================

    async def search_interferences(
        self,
        filters: Optional[List[Dict[str, Any]]] = None,
        range_filters: Optional[List[Dict[str, Any]]] = None,
        sort: Optional[List[Dict[str, str]]] = None,
        pagination: Optional[Dict[str, int]] = None,
        fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Search interference decisions

        Args:
            filters: List of filter objects with 'name' and 'value'
            range_filters: List of range filters with 'field', 'valueFrom', 'valueTo'
            sort: List of sort specifications with 'field' and 'order'
            pagination: Dict with 'offset' and 'limit'
            fields: Optional list of fields to retrieve for context reduction

        Returns:
            Dict containing search results with interference decisions
        """
        return await self._search(
            "interferences/decisions/search",
            circuit_breaker=self.interferences_circuit_breaker,
            label="Interference",
            filters=filters,
            range_filters=range_filters,
            sort=sort,
            pagination=pagination,
            fields=fields,
        )

    async def get_interference_decisions(
        self,
        interference_number: str
    ) -> Dict[str, Any]:
        """
        Get all decisions for a specific interference

        Args:
            interference_number: Interference number

        Returns:
            Dict containing list of decisions
        """
        try:
            return await self._make_request(
                f"interferences/{interference_number}/decisions",
                method="GET",
                circuit_breaker=self.interferences_circuit_breaker
            )

        except Exception as e:
            logger.error(f"Error in get_interference_decisions: {str(e)}")
            return format_error_response(str(e), 500, generate_request_id())

    async def download_interference_document(
        self,
        file_download_uri: str
    ) -> bytes:
        """
        Download an interference document from fileDownloadURI

        Args:
            file_download_uri: Full download URL from document metadata

        Returns:
            Raw PDF bytes

        Raises:
            httpx.HTTPStatusError: If download fails
        """
        return await self._download_document(file_download_uri, "interference")

