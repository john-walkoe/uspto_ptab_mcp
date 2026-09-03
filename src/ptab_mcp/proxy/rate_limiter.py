"""
Rate limiting for USPTO PTAB API compliance.

Implements USPTO's download limit (assumed 5 files per 10 seconds based on FPD pattern).
"""

import time
from collections import defaultdict, deque
from typing import Dict, Deque
from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

# USPTO rate limit constants (from api_constants if available)
# Using same limits as FPD for consistency
USPTO_MAX_DOWNLOADS_PER_WINDOW = 5
USPTO_RATE_LIMIT_WINDOW_SECONDS = 10


class RateLimiter:
    """Rate limiter for USPTO PTAB document downloads."""

    def __init__(
        self,
        max_requests: int = USPTO_MAX_DOWNLOADS_PER_WINDOW,
        time_window: int = USPTO_RATE_LIMIT_WINDOW_SECONDS
    ):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed in time window (default: 5)
            time_window: Time window in seconds (default: 10)
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests: Dict[str, Deque[float]] = defaultdict(deque)
        self._last_eviction = 0.0
        self._eviction_interval = 60.0  # seconds between idle-IP sweeps

    def _evict_idle(self, now: float) -> None:
        """Drop IPs with no in-window requests so the dict stays bounded (L-7)."""
        if now - self._last_eviction < self._eviction_interval:
            return
        self._last_eviction = now
        cutoff = now - self.time_window
        for ip in list(self.requests):
            timestamps = self.requests[ip]
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()
            if not timestamps:
                del self.requests[ip]

    def is_allowed(self, client_ip: str) -> bool:
        """
        Check if a request from the given IP is allowed.

        Args:
            client_ip: Client IP address

        Returns:
            True if request is allowed, False if rate limited
        """
        now = time.time()
        self._evict_idle(now)
        client_requests = self.requests[client_ip]

        # Remove requests outside the time window
        while client_requests and client_requests[0] < now - self.time_window:
            client_requests.popleft()

        # Check if we're at the limit
        if len(client_requests) >= self.max_requests:
            logger.warning(
                f"Rate limit exceeded for IP {client_ip}: "
                f"{len(client_requests)} requests in {self.time_window} seconds"
            )
            return False

        # Add the current request
        client_requests.append(now)
        logger.info(
            f"Request allowed for IP {client_ip}: "
            f"{len(client_requests)}/{self.max_requests} requests in window"
        )
        return True

    def get_remaining_requests(self, client_ip: str) -> int:
        """
        Get number of remaining requests for the IP.

        Args:
            client_ip: Client IP address

        Returns:
            Number of remaining requests in current window
        """
        now = time.time()
        # Read without materializing: self.requests is a defaultdict, so
        # indexing it here allocated a permanent entry for every distinct
        # string handed to the read-only /rate-limit/{client_ip} route, and
        # _evict_idle only ever runs from is_allowed.
        client_requests = self.requests.get(client_ip)
        if not client_requests:
            return self.max_requests

        # Remove old requests
        while client_requests and client_requests[0] < now - self.time_window:
            client_requests.popleft()

        return max(0, self.max_requests - len(client_requests))

    def get_reset_time(self, client_ip: str) -> float:
        """
        Get time when rate limit will reset for the IP.

        Args:
            client_ip: Client IP address

        Returns:
            Unix timestamp when oldest request will expire
        """
        # .get, not [] — see get_remaining_requests: indexing the defaultdict
        # from a read-only path grows it without bound.
        client_requests = self.requests.get(client_ip)
        if not client_requests:
            return time.time()

        return client_requests[0] + self.time_window


# Global rate limiter instance
rate_limiter = RateLimiter()
