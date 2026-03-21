"""
USPTO PTAB API Client for Open Data Portal

Client for accessing the USPTO Patent Trial and Appeal Board (PTAB) API via ODP.
Supports trials (IPR/PGR/CBM), appeals, and interferences.
Requires USPTO API key (X-API-KEY header).
"""

import asyncio
import httpx
import logging
import json
import os
import random
from typing import Dict, Any, List, Optional
from ..shared.error_utils import format_error_response, generate_request_id
from ..shared.circuit_breaker import CircuitBreaker
from ..shared.cache import CacheManager
from ..shared.safe_logger import get_safe_logger
from ..config import api_constants
from .field_constants import TrialFields, AppealFields, InterferenceFields
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

        logger.info(
            f"Timeout configuration: default={self.default_timeout}s, "
            f"download={self.download_timeout}s"
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

                for attempt in range(self.RETRY_ATTEMPTS):
                    try:
                        async with httpx.AsyncClient(
                            timeout=request_timeout,
                            verify=True,
                            limits=self.connection_limits,
                            follow_redirects=True  # Handle 302 redirects to S3 signed URLs
                        ) as client:
                            if method.upper() == "POST":
                                response = await client.post(url, headers=self.headers, **kwargs)
                            else:
                                response = await client.get(url, headers=self.headers, **kwargs)

                            response.raise_for_status()
                            logger.info(f"[{request_id}] Request successful on attempt {attempt + 1}")
                            return response.json()

                    except httpx.HTTPStatusError as e:
                        # Don't retry authentication errors or client errors (4xx)
                        if e.response.status_code < 500:
                            logger.error(
                                f"[{request_id}] API error {e.response.status_code}: "
                                f"{e.response.text}"
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
                        # Don't retry unexpected errors on final attempt
                        if attempt == self.RETRY_ATTEMPTS - 1:
                            logger.error(f"[{request_id}] Request failed: {str(e)}")
                            return format_error_response(
                                f"Request failed: {str(e)}",
                                500,
                                request_id
                            )
                        last_exception = e

                    # Calculate delay with exponential backoff and jitter
                    if attempt < self.RETRY_ATTEMPTS - 1:
                        delay = self.RETRY_DELAY * (self.RETRY_BACKOFF ** attempt)
                        # Add jitter to prevent thundering herd
                        jitter = random.uniform(0.1, 0.5)
                        total_delay = delay + jitter

                        logger.warning(
                            f"[{request_id}] Request failed on attempt {attempt + 1}/"
                            f"{self.RETRY_ATTEMPTS}, retrying in {total_delay:.2f}s: "
                            f"{str(last_exception)}"
                        )
                        await asyncio.sleep(total_delay)

                # All retries failed
                if isinstance(last_exception, httpx.TimeoutException):
                    logger.error(
                        f"[{request_id}] Request timeout after {self.RETRY_ATTEMPTS} attempts"
                    )
                    return format_error_response(
                        "Request timeout - please try again",
                        408,
                        request_id
                    )
                elif isinstance(last_exception, httpx.HTTPStatusError):
                    logger.error(
                        f"[{request_id}] API error {last_exception.response.status_code} "
                        f"after {self.RETRY_ATTEMPTS} attempts"
                    )
                    return format_error_response(
                        f"API error: {last_exception.response.text}",
                        last_exception.response.status_code,
                        request_id
                    )
                else:
                    logger.error(
                        f"[{request_id}] Request failed after {self.RETRY_ATTEMPTS} "
                        f"attempts: {str(last_exception)}"
                    )
                    return format_error_response(
                        f"Request failed: {str(last_exception)}",
                        500,
                        request_id
                    )

        # Execute through circuit breaker with cache fallback
        try:
            result = await cb.call(_execute_request)

            # Cache successful responses for circuit breaker fallback
            if result and not result.get("error"):
                cache_key = f"{method}_{endpoint}"
                self.cache_manager.set(cache_key, result, **kwargs)
                logger.debug(f"[{request_id}] Cached response for {cache_key}")

            return result

        except Exception as e:
            logger.error(f"[{request_id}] Circuit breaker error: {str(e)}")

            # Try cache fallback when circuit is OPEN
            if "Circuit breaker" in str(e) and "OPEN" in str(e):
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
                else:
                    logger.error(f"[{request_id}] No cached fallback available for {cache_key}")

            # No cache available - return error
            return format_error_response(
                f"Service temporarily unavailable: {str(e)}",
                503,
                request_id
            )

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
        try:
            # Build request body
            body = {
                "pagination": pagination or {
                    "offset": 0,
                    "limit": self.DEFAULT_LIMIT
                }
            }

            # Add optional parameters
            if filters:
                body["filters"] = filters

            if range_filters:
                body["rangeFilters"] = range_filters

            if sort:
                body["sort"] = sort

            if fields:
                body["fields"] = fields

            logger.debug(f"Trial search request body: {json.dumps(body, indent=2)}")

            return await self._make_request(
                "trials/proceedings/search",
                method="POST",
                circuit_breaker=self.trials_circuit_breaker,
                json=body
            )

        except Exception as e:
            logger.error(f"Error in search_trials: {str(e)}")
            return format_error_response(str(e), 500, generate_request_id())

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
            limit: Number of documents to return (default: 25, max: 200)
            sort_order: "asc" (oldest first) or "desc" (newest first)

        Returns:
            Dict with patentTrialDocumentDataBag and count
        """
        try:
            body = {
                "filters": [{"name": "trialNumber", "value": [trial_number]}],
                "pagination": {"offset": offset, "limit": limit}
                # sort omitted until field name is confirmed against live API;
                # sort_order is applied client-side in ptab_get_documents
            }
            logger.debug(f"Document search request body: {json.dumps(body, indent=2)}")
            return await self._make_request(
                "trials/documents/search",
                method="POST",
                circuit_breaker=self.trials_circuit_breaker,
                json=body
            )

        except Exception as e:
            logger.error(f"Error in search_trial_documents: {str(e)}")
            return format_error_response(str(e), 500, generate_request_id())

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
        try:
            request_id = generate_request_id()
            logger.info(f"[{request_id}] Downloading trial document from {file_download_uri}")

            async with httpx.AsyncClient(
                timeout=self.download_timeout,
                verify=True,
                limits=self.connection_limits,
                follow_redirects=True  # Handle 302 redirects to S3 signed URLs
            ) as client:
                response = await client.get(file_download_uri, headers=self.headers)
                response.raise_for_status()
                logger.info(f"[{request_id}] Downloaded {len(response.content)} bytes")
                return response.content

        except Exception as e:
            logger.error(f"Error downloading trial document: {str(e)}")
            raise

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
        try:
            # Build request body
            body = {
                "pagination": pagination or {
                    "offset": 0,
                    "limit": self.DEFAULT_LIMIT
                }
            }

            # Add optional parameters
            if filters:
                body["filters"] = filters

            if range_filters:
                body["rangeFilters"] = range_filters

            if sort:
                body["sort"] = sort

            if fields:
                body["fields"] = fields

            logger.debug(f"Appeal search request body: {json.dumps(body, indent=2)}")

            return await self._make_request(
                "appeals/decisions/search",
                method="POST",
                circuit_breaker=self.appeals_circuit_breaker,
                json=body
            )

        except Exception as e:
            logger.error(f"Error in search_appeals: {str(e)}")
            return format_error_response(str(e), 500, generate_request_id())

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
        try:
            request_id = generate_request_id()
            logger.info(f"[{request_id}] Downloading appeal document from {file_download_uri}")

            async with httpx.AsyncClient(
                timeout=self.download_timeout,
                verify=True,
                limits=self.connection_limits,
                follow_redirects=True  # Handle 302 redirects to S3 signed URLs
            ) as client:
                response = await client.get(file_download_uri, headers=self.headers)
                response.raise_for_status()
                logger.info(f"[{request_id}] Downloaded {len(response.content)} bytes")
                return response.content

        except Exception as e:
            logger.error(f"Error downloading appeal document: {str(e)}")
            raise

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
        try:
            # Build request body
            body = {
                "pagination": pagination or {
                    "offset": 0,
                    "limit": self.DEFAULT_LIMIT
                }
            }

            # Add optional parameters
            if filters:
                body["filters"] = filters

            if range_filters:
                body["rangeFilters"] = range_filters

            if sort:
                body["sort"] = sort

            if fields:
                body["fields"] = fields

            logger.debug(f"Interference search request body: {json.dumps(body, indent=2)}")

            return await self._make_request(
                "interferences/decisions/search",
                method="POST",
                circuit_breaker=self.interferences_circuit_breaker,
                json=body
            )

        except Exception as e:
            logger.error(f"Error in search_interferences: {str(e)}")
            return format_error_response(str(e), 500, generate_request_id())

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
        try:
            request_id = generate_request_id()
            logger.info(
                f"[{request_id}] Downloading interference document from {file_download_uri}"
            )

            async with httpx.AsyncClient(
                timeout=self.download_timeout,
                verify=True,
                limits=self.connection_limits,
                follow_redirects=True  # Handle 302 redirects to S3 signed URLs
            ) as client:
                response = await client.get(file_download_uri, headers=self.headers)
                response.raise_for_status()
                logger.info(f"[{request_id}] Downloaded {len(response.content)} bytes")
                return response.content

        except Exception as e:
            logger.error(f"Error downloading interference document: {str(e)}")
            raise
