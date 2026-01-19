"""
Circuit Breaker Pattern Implementation

Prevents cascading failures by monitoring API call success/failure rates
and temporarily stopping requests when failure threshold is exceeded.
"""

import asyncio
import time
import logging
from enum import Enum
from typing import Callable, Any, Optional, Dict
from .safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation, requests pass through
    OPEN = "open"          # Circuit is open, requests fail fast
    HALF_OPEN = "half_open"  # Testing state, limited requests allowed


class CircuitBreaker:
    """
    Circuit breaker for preventing cascading failures

    Monitors consecutive failures and opens circuit when threshold is exceeded.
    After timeout period, allows limited requests in half-open state to test recovery.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        name: str = "default"
    ):
        """
        Initialize circuit breaker

        Args:
            failure_threshold: Number of consecutive failures before opening circuit
            recovery_timeout: Seconds to wait before testing recovery
            name: Name for logging and identification
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name

        # State tracking
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = CircuitState.CLOSED
        self._lock = asyncio.Lock()

        logger.info(f"Circuit breaker '{name}' initialized: threshold={failure_threshold}, timeout={recovery_timeout}s")

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function call through circuit breaker

        Args:
            func: Async function to call
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result if successful

        Raises:
            Exception: If circuit is open or function fails
        """
        async with self._lock:
            # Check if circuit should transition from open to half-open
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    logger.info(f"Circuit breaker '{self.name}' transitioning to HALF_OPEN for testing")
                    self.state = CircuitState.HALF_OPEN
                else:
                    raise Exception(f"Circuit breaker '{self.name}' is OPEN - service unavailable")

            # In half-open state, limit the number of test requests
            if self.state == CircuitState.HALF_OPEN:
                if self.success_count >= 3:  # After 3 successes, close circuit
                    logger.info(f"Circuit breaker '{self.name}' closing after successful recovery")
                    self._close_circuit()

        # Execute the function call
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure(e)
            raise e

    async def _on_success(self):
        """Handle successful function call"""
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                logger.debug(f"Circuit breaker '{self.name}' success in HALF_OPEN state: {self.success_count}/3")

                if self.success_count >= 3:
                    self._close_circuit()
            elif self.state == CircuitState.CLOSED:
                # Reset failure count on success
                if self.failure_count > 0:
                    logger.debug(f"Circuit breaker '{self.name}' reset failure count after success")
                    self.failure_count = 0

    async def _on_failure(self, exception: Exception):
        """Handle failed function call"""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            logger.warning(f"Circuit breaker '{self.name}' failure {self.failure_count}/{self.failure_threshold}: {str(exception)}")

            if self.state == CircuitState.HALF_OPEN:
                # Failure in half-open state - go back to open
                logger.warning(f"Circuit breaker '{self.name}' opening due to failure in HALF_OPEN state")
                self._open_circuit()
            elif self.state == CircuitState.CLOSED and self.failure_count >= self.failure_threshold:
                # Too many failures - open circuit
                logger.error(f"Circuit breaker '{self.name}' opening due to {self.failure_count} consecutive failures")
                self._open_circuit()

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset"""
        if self.last_failure_time is None:
            return True

        return time.time() - self.last_failure_time > self.recovery_timeout

    def _open_circuit(self):
        """Open the circuit"""
        self.state = CircuitState.OPEN
        self.success_count = 0
        self.last_failure_time = time.time()

    def _close_circuit(self):
        """Close the circuit"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None

    def get_state(self) -> Dict[str, Any]:
        """
        Get current circuit breaker state for monitoring

        Returns:
            Dictionary with state information
        """
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "last_failure_time": self.last_failure_time,
            "time_until_retry": max(0, self.recovery_timeout - (time.time() - (self.last_failure_time or 0))) if self.last_failure_time else 0
        }

    def reset(self):
        """Manually reset circuit breaker to closed state"""
        logger.info(f"Circuit breaker '{self.name}' manually reset")
        self._close_circuit()
