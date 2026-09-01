"""Request pacing and 429 retry for rate-limited LLM backends.

Section 8.1 picks the Gemini free tier, whose quota is 5 requests/minute per
model. The extraction graph fans out six specialist extractors per document, so
an unpaced run exceeds the quota on the very first document and loses whichever
branches lost the race -- which looks exactly like an extraction failure.

Two mechanisms, both needed:

  RateLimiter     spaces requests so the quota is not exceeded in the first
                  place.
  retry_transient honours the server's own `retryDelay` when it is exceeded
                  anyway (shared quota, another process, a burst at a minute
                  boundary), and also retries 503 UNAVAILABLE -- a shared free
                  tier returns "high demand" spikes that clear in seconds.
"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_RETRY_DELAY = re.compile(r"'retryDelay':\s*'(\d+(?:\.\d+)?)s'")
_RETRY_SECONDS = re.compile(r"retry in (\d+(?:\.\d+)?)s")


class RateLimiter:
    """Thread-safe minimum-interval pacer.

    The lock is deliberately held across the sleep: callers queue and are
    released one interval apart, which is the behaviour that keeps a parallel
    fan-out inside a per-minute quota. Releasing the lock before sleeping would
    let every thread compute the same slot and fire together.
    """

    def __init__(self, requests_per_minute: int) -> None:
        self.rpm = requests_per_minute
        self._interval = 60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        self._lock = threading.Lock()
        self._next_slot = 0.0

    def acquire(self) -> None:
        if self._interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._next_slot - now
            if wait > 0:
                logger.debug("rate limiter: waiting %.1fs", wait)
                time.sleep(wait)
                now = time.monotonic()
            self._next_slot = now + self._interval


def is_daily_quota_exhausted(exc: Exception) -> bool:
    """Distinguish a per-day cap from a per-minute one.

    They need opposite responses. A per-minute breach clears in seconds, so
    waiting is right. A per-day cap does not clear until tomorrow, so waiting is
    useless -- the only useful move is to switch to a model with its own quota.
    """
    text = str(exc)
    return "429" in text and "PerDay" in text


def _is_transient(exc: Exception) -> bool:
    """Retryable: quota exhaustion and temporary server overload.

    Deliberately narrow. A schema-validation failure or a bad request is not
    retried -- doing so burns quota and delays the report that something is
    genuinely wrong.
    """
    if is_daily_quota_exhausted(exc):
        return False        # retrying a daily cap just burns the clock
    text = str(exc)
    return any(
        marker in text
        for marker in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500 INTERNAL")
    )


def _suggested_delay(exc: Exception, attempt: int) -> float:
    """Prefer the server's own retry hint; fall back to exponential backoff."""
    text = str(exc)
    for pattern in (_RETRY_DELAY, _RETRY_SECONDS):
        match = pattern.search(text)
        if match:
            # A small margin: retrying at exactly the stated instant tends to
            # land on the same side of the quota window boundary.
            return float(match.group(1)) + 1.0
    return min(60.0, (2**attempt) + random.uniform(0, 1))


def retry_transient(fn: Callable[[], T], *, attempts: int = 4, label: str = "request") -> T:
    """Run `fn`, retrying only on quota and temporary-overload errors."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised below when not a 429
            if not _is_transient(exc):
                raise
            last = exc
            if attempt == attempts - 1:
                break
            delay = _suggested_delay(exc, attempt)
            logger.warning(
                "%s: %s (attempt %d/%d), retrying in %.1fs",
                label,
                "rate limited" if "429" in str(exc) else "service unavailable",
                attempt + 1, attempts, delay,
            )
            time.sleep(delay)
    raise last  # type: ignore[misc]


# Backwards-compatible alias: the original name only covered 429s.
retry_on_429 = retry_transient
