"""Request pacing and 429 retry for rate-limited LLM backends.

Section 8.1 picks the Gemini free tier, whose quota is 5 requests/minute per
model. The extraction graph fans out six specialist extractors per document, so
an unpaced run exceeds the quota on the very first document and loses whichever
branches lost the race -- which looks exactly like an extraction failure.

Two mechanisms, both needed:

  RateLimiter     allows a provider-safe burst, then paces sustained traffic
                  so the quota is not exceeded.
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
    """Paces requests against whichever quota actually binds.

    A free tier caps two different things -- requests per minute and TOKENS per
    minute -- and which one binds depends on the size of what you are sending.
    Pacing on requests alone makes every call pay the price of the largest one:
    Groq's 8,000 TPM allows roughly two 4,400-token extraction calls a minute,
    so a fixed 2 rpm was configured, and a 1,500-token question then waited 30
    seconds for no reason. Measured: 30s of latency around 1.6s of generation.

    So the limiter tracks both. A caller declares roughly how many tokens it is
    about to spend, and waits only for the constraint it actually trips. Small
    requests go almost immediately; large ones still queue.

    Nothing about WHAT is sent changes -- only when. This is pacing, not
    sampling, and it cannot affect an answer's content.
    """

    def __init__(
        self, requests_per_minute: int, tokens_per_minute: int | None = None
    ) -> None:
        self.rpm = requests_per_minute
        self.tpm = tokens_per_minute
        self._lock = threading.Lock()
        # Both buckets start full and refill continuously. This is important for
        # extraction: a fresh provider budget can safely absorb the five/six-way
        # graph fan-out. The old fixed-spacing limiter added 20 seconds at
        # 15 RPM even when all six requests fitted inside the available minute.
        self._requests = float(requests_per_minute or 0)
        self._tokens = float(tokens_per_minute or 0)
        self._refilled = time.monotonic()

    @staticmethod
    def _take(
        available: float,
        capacity: int | None,
        cost: int,
        elapsed: float,
    ) -> tuple[float, float]:
        """Return (reserved balance, wait seconds) for one token bucket."""
        if not capacity or cost <= 0:
            return available, 0.0
        rate = capacity / 60.0
        available = min(float(capacity), available + elapsed * rate)
        # A single request larger than the full budget can never become
        # admissible by waiting. Let the provider return its useful 413.
        if cost > capacity:
            return available, 0.0
        available -= cost
        return available, max(-available / rate, 0.0)

    def _reserve(self, tokens: int) -> float:
        """Reserve request and token capacity, returning the binding wait."""
        if self.rpm <= 0 and not self.tpm:
            return 0.0
        now = time.monotonic()
        elapsed = now - self._refilled
        self._requests, request_wait = self._take(
            self._requests, self.rpm, 1, elapsed
        )
        self._tokens, token_wait = self._take(
            self._tokens, self.tpm, tokens, elapsed
        )
        self._refilled = now
        return max(request_wait, token_wait)

    def acquire(self, tokens: int = 0) -> None:
        """Block until this request may be sent.

        The lock is held across the sleep on purpose: callers queue and are
        released in order. Releasing it before sleeping would let every thread
        in a fan-out compute the same slot and fire together, which is the
        behaviour the pacing exists to prevent.
        """
        if self.rpm <= 0 and not self.tpm:
            return
        with self._lock:
            wait = self._reserve(tokens)
            if wait > 0:
                logger.debug("rate limiter: waiting %.1fs (%d tokens)", wait, tokens)
                time.sleep(wait)


#: Characters per token for English legal prose. Only ever used to SIZE a
#: request for pacing, so an approximation is fine -- being out by 20% shifts a
#: wait by 20%, it does not change what is sent.
CHARS_PER_TOKEN = 3.5


def estimate_tokens(*parts: str | None) -> int:
    """Rough token cost of a request, for the limiter."""
    return int(sum(len(p) for p in parts if p) / CHARS_PER_TOKEN)


def is_daily_quota_exhausted(exc: Exception) -> bool:
    """Distinguish a per-day cap from a per-minute one.

    They need opposite responses. A per-minute breach clears in seconds, so
    waiting is right. A per-day cap does not clear until tomorrow, so waiting is
    useless -- the only useful move is to switch to a model with its own quota.
    """
    text = str(exc)
    return "429" in text and "PerDay" in text


# Transport failures, matched by TYPE rather than by message text.
#
# String matching cannot see these. A dropped connection surfaces as
# `httpx.ReadError: [Errno 54] Connection reset by peer` -- no status code, no
# "UNAVAILABLE", nothing the marker list below would catch -- and it is the most
# ordinary transient failure there is. Before this, a reset connection ended a
# document's extraction outright while a 503 from the same server was retried.
def _transport_error_types() -> tuple[type[BaseException], ...]:
    types: list[type[BaseException]] = [
        ConnectionError,      # builtin; covers ConnectionReset/Aborted/Refused
        TimeoutError,         # builtin; socket and asyncio timeouts alias to this
    ]
    try:
        import httpx

        types.append(httpx.TransportError)
    except Exception:                       # pragma: no cover - httpx is a dep
        pass
    try:
        import requests

        types.append(requests.exceptions.ConnectionError)
        types.append(requests.exceptions.Timeout)
    except Exception:                       # pragma: no cover - optional
        pass
    return tuple(types)


_TRANSPORT_ERRORS = _transport_error_types()

# Server-side conditions that clear on their own, matched in the message because
# the SDKs surface them as generic exceptions carrying the status in the text.
_TRANSIENT_MARKERS = (
    "429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500 INTERNAL",
    "502", "504", "Bad Gateway", "Gateway Time", "Service Unavailable",
    "Connection reset", "Connection aborted", "Server disconnected",
    "Temporary failure in name resolution", "EOF occurred",
)


def _is_transient(exc: Exception) -> bool:
    """Retryable: transport failures, quota pressure and temporary overload.

    Deliberately narrow on everything else. A schema-validation failure or a bad
    request is not retried -- doing so burns quota and delays the report that
    something is genuinely wrong. Nor is a daily cap: it does not clear today.
    """
    if is_daily_quota_exhausted(exc):
        return False        # retrying a daily cap just burns the clock

    # Walk the cause chain: SDKs wrap transport errors in their own exception
    # types, and the interesting one is usually two levels down.
    seen = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, _TRANSPORT_ERRORS):
            return True
        current = current.__cause__ or current.__context__

    text = str(exc)
    return any(marker.lower() in text.lower() for marker in _TRANSIENT_MARKERS)


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


def retry_transient(
    fn: Callable[[], T],
    *,
    attempts: int = 4,
    label: str = "request",
    max_delay: float = 60.0,
) -> T:
    """Run `fn`, retrying only on quota and temporary-overload errors.

    `max_delay` caps how long a single retry will wait. It exists because the
    server's own `retryDelay` hint is often 60 seconds, and honouring that is
    only correct when this provider is the last resort. With a live tier below
    it, waiting a minute for a rate-limited primary is strictly worse than
    falling through to a provider that answers in two seconds -- measured, on a
    cold chain, as 121 seconds of a 181-second extraction.
    """
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
            delay = min(_suggested_delay(exc, attempt), max_delay)
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
