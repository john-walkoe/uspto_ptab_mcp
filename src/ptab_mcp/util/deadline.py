"""One end-to-end time budget for a long tool call.

Cloudflare cuts a proxied request at about 100 s, and claude.ai then sees an
error the server never hears about. PTAB_get_document_content's OCR path
(document download, then Mistral upload + OCR with retries, then Docling)
used to budget each attempt on its own: 120 s per Mistral request, three
attempts, two requests. One Deadline is created when the tool starts and
every step below takes what is left of it, so retries and fallbacks stay
inside the one budget rather than each getting a fresh one.

Env:
    PTAB_CONTENT_DEADLINE_SECONDS   budget per PTAB_get_document_content
                                    call (default 85, under the ~100 s cut)
"""

from __future__ import annotations

import os
import time
from typing import Callable

from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

DEFAULT_CONTENT_DEADLINE_SECONDS = 85.0


class DeadlineExceeded(Exception):
    """The call's time budget ran out before the step could finish."""


class Deadline:
    """A monotonic end time. `clock` is injectable so tests can fake time."""

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.seconds = float(seconds)
        self._clock = clock
        self._end = clock() + self.seconds

    def remaining(self) -> float:
        """Seconds left, never negative."""
        return max(0.0, self._end - self._clock())

    def expired(self) -> bool:
        return self.remaining() <= 0.0


def content_deadline_seconds() -> float:
    """PTAB_CONTENT_DEADLINE_SECONDS, else 85; non-positive or junk -> 85."""
    raw = os.getenv("PTAB_CONTENT_DEADLINE_SECONDS", "").strip()
    if not raw:
        return DEFAULT_CONTENT_DEADLINE_SECONDS
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid PTAB_CONTENT_DEADLINE_SECONDS, using default 85")
        return DEFAULT_CONTENT_DEADLINE_SECONDS
    return value if value > 0 else DEFAULT_CONTENT_DEADLINE_SECONDS
