"""
Circuit Breaker Pattern Implementation

Prevents cascading failures by monitoring API call success/failure rates
and temporarily stopping requests when failure threshold is exceeded.
"""

import asyncio
import time
from enum import Enum
from typing import Callable, Any, Optional, Dict
from .safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation, requests pass through
    OPEN = "open"          # Circuit is open, requests fail fast
    HALF_OPEN = "half_open"  # Testing state, limited requests allowed


class CircuitBreakerOpenError(Exception):
    """Raised when a call is rejected because the circuit is OPEN (EH-4).

    Typed so callers can branch on it directly instead of string-matching
    the exception message.
    """

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Circuit breaker '{name}' is OPEN - service unavailable")


class CircuitBreaker:
    """
    Circuit breaker for preventing cascading failures

    Monitors consecutive failures and opens circuit when threshold is exceeded.
    After timeout period, allows limited requests in half-open state to test recovery.
    """

    #: Consecutive HALF_OPEN successes required to close the circuit. Was a
    #: bare 3 compared in two separate methods (R-6).
    HALF_OPEN_SUCCESSES_TO_CLOSE = 3

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        name: str = "default",
        half_open_max_probes: int = 1
    ):
        """
        Initialize circuit breaker

        Args:
            failure_threshold: Number of consecutive failures before opening circuit
            recovery_timeout: Seconds to wait before testing recovery
            name: Name for logging and identification
            half_open_max_probes: Concurrent probe requests admitted while
                HALF_OPEN. Everything beyond this fails fast rather than
                queueing against a still-down upstream.
        """
        self.half_open_max_probes = half_open_max_probes
        self._probes_in_flight = 0
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
                    raise CircuitBreakerOpenError(self.name)

            # In half-open state, limit the number of test requests.
            # NOTE (RF-8): this check-then-recheck across the lock release is
            # safe — _on_success() re-checks success_count under the same
            # lock before closing, so a concurrent success cannot be lost;
            # this early close is only an optimization.
            if self.state == CircuitState.HALF_OPEN:
                if self.success_count >= self.HALF_OPEN_SUCCESSES_TO_CLOSE:
                    logger.info(f"Circuit breaker '{self.name}' closing after successful recovery")
                    self._close_circuit()

            # Admission control, which the comment above has always claimed and
            # the code never did: success_count >= N is a CLOSE condition, not a
            # limit on probes. Every caller arriving while HALF_OPEN used to be
            # admitted, each burning its full retry budget against a still-down
            # upstream before the first failure re-opened the circuit.
            probing = False
            if self.state == CircuitState.HALF_OPEN:
                if self._probes_in_flight >= self.half_open_max_probes:
                    raise CircuitBreakerOpenError(self.name)
                self._probes_in_flight += 1
                probing = True

        # Execute the function call
        try:
            result = await func(*args, **kwargs)
            await self._on_success(probing)
            return result
        except Exception as e:
            await self._on_failure(e, probing)
            raise e

    async def _on_success(self, probing: bool = False):
        """Handle successful function call"""
        async with self._lock:
            if probing:
                self._probes_in_flight = max(0, self._probes_in_flight - 1)
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                logger.debug(
                    f"Circuit breaker '{self.name}' success in HALF_OPEN state: "
                    f"{self.success_count}/{self.HALF_OPEN_SUCCESSES_TO_CLOSE}"
                )

                if self.success_count >= self.HALF_OPEN_SUCCESSES_TO_CLOSE:
                    self._close_circuit()
            elif self.state == CircuitState.CLOSED:
                # Reset failure count on success
                if self.failure_count > 0:
                    logger.debug(f"Circuit breaker '{self.name}' reset failure count after success")
                    self.failure_count = 0

    async def _on_failure(self, exception: Exception, probing: bool = False):
        """Handle failed function call"""
        async with self._lock:
            if probing:
                self._probes_in_flight = max(0, self._probes_in_flight - 1)
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
