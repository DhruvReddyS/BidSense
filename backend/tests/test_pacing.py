"""Pacing against the quota that actually binds.

A free tier caps requests per minute AND tokens per minute, and which one binds
depends on what you are sending. Pacing on requests alone made every call pay
the price of the largest: Groq's 8,000 TPM allows about two 4,400-token
extraction calls a minute, so 2 rpm was configured, and a 1,500-token question
then waited 30 seconds around 1.6 seconds of generation.

Nothing here changes WHAT is sent. Pacing cannot affect an answer's content --
these tests exist to prove the latency came from the limiter, not the model.
"""

from __future__ import annotations

import time

import pytest

from app.llm.ratelimit import RateLimiter, estimate_tokens, retry_transient


# --------------------------------------------------------------------------- #
# Token pacing
# --------------------------------------------------------------------------- #
def test_a_small_request_does_not_wait_for_a_large_one() -> None:
    """The whole point. Under a request-only limiter these two waits were
    identical; under a token budget the small one goes straight through."""
    limiter = RateLimiter(requests_per_minute=0, tokens_per_minute=8000)

    started = time.monotonic()
    limiter.acquire(1500)          # a RAG question
    small = time.monotonic() - started

    assert small < 0.05, f"a small request waited {small:.2f}s"


def test_the_bucket_starts_full_so_a_cold_start_fires_immediately() -> None:
    """An empty bucket would make the first call of a session wait out a
    phantom minute for budget it has never spent."""
    limiter = RateLimiter(0, tokens_per_minute=8000)
    started = time.monotonic()
    limiter.acquire(7900)
    assert time.monotonic() - started < 0.05


def test_spending_the_budget_makes_the_next_caller_wait() -> None:
    """The limit still has to bind, or this is not a limiter."""
    limiter = RateLimiter(0, tokens_per_minute=600)   # 10 tokens/second
    limiter.acquire(600)                               # empties the bucket

    started = time.monotonic()
    limiter.acquire(20)                                # needs ~2s of refill
    waited = time.monotonic() - started
    assert 1.0 < waited < 4.0, f"waited {waited:.2f}s"


def test_the_bucket_refills_over_time() -> None:
    limiter = RateLimiter(0, tokens_per_minute=6000)   # 100 tokens/second
    limiter.acquire(6000)
    time.sleep(0.3)                                    # ~30 tokens back
    started = time.monotonic()
    limiter.acquire(25)
    assert time.monotonic() - started < 0.15


def test_a_request_larger_than_the_whole_budget_is_not_waited_on_forever() -> None:
    """No amount of waiting satisfies it. Letting the provider return its real
    413 is a better answer than hanging."""
    limiter = RateLimiter(0, tokens_per_minute=1000)
    started = time.monotonic()
    limiter.acquire(50_000)
    assert time.monotonic() - started < 2.0


def test_both_constraints_apply_and_the_binding_one_wins() -> None:
    """Once burst capacity is spent, whichever bucket refills slower wins."""
    limiter = RateLimiter(requests_per_minute=60, tokens_per_minute=60_000)
    for _ in range(60):
        limiter.acquire(10)
    started = time.monotonic()
    limiter.acquire(10)             # request bucket needs ~1s; tokens are free
    waited = time.monotonic() - started
    assert 0.7 < waited < 1.6, f"waited {waited:.2f}s"


def test_no_limits_configured_means_no_waiting() -> None:
    limiter = RateLimiter(0, tokens_per_minute=None)
    started = time.monotonic()
    for _ in range(50):
        limiter.acquire(5000)
    assert time.monotonic() - started < 0.05


@pytest.mark.parametrize(
    "text, low, high",
    [("", 0, 1), ("a" * 3500, 900, 1100), ("word " * 1000, 1300, 1600)],
)
def test_the_token_estimate_is_in_the_right_order(text, low, high) -> None:
    """Only ever used to SIZE a request. Being out by 20% shifts a wait by 20%;
    it cannot change what is sent."""
    assert low <= estimate_tokens(text) <= high


# --------------------------------------------------------------------------- #
# Impatience when a fallback exists
# --------------------------------------------------------------------------- #
def test_a_long_server_retry_hint_is_capped_when_a_tier_sits_below(monkeypatch) -> None:
    """The server suggests 60s. Honouring that is right for a last resort and
    wrong for a primary with a live tier below it -- measured as 121s of a
    181s cold extraction."""
    slept: list[float] = []
    monkeypatch.setattr("app.llm.ratelimit.time.sleep", lambda s: slept.append(s))

    attempts = {"n": 0}

    def rate_limited():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("429 RESOURCE_EXHAUSTED {'retryDelay': '60s'}")
        return "ok"

    assert retry_transient(rate_limited, attempts=2, max_delay=8.0) == "ok"
    assert slept and max(slept) <= 8.0, f"waited {slept}"


def test_the_last_tier_keeps_its_full_patience(monkeypatch) -> None:
    """With nowhere to fall through to, waiting out the server's hint is the
    right move -- an error is worse than a wait."""
    slept: list[float] = []
    monkeypatch.setattr("app.llm.ratelimit.time.sleep", lambda s: slept.append(s))

    attempts = {"n": 0}

    def rate_limited():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("429 RESOURCE_EXHAUSTED {'retryDelay': '45s'}")
        return "ok"

    retry_transient(rate_limited, attempts=3, max_delay=60.0)
    assert max(slept) > 8.0


def test_every_tier_but_the_last_is_marked_impatient(monkeypatch) -> None:
    """Structural: the chain, not each provider, decides who has somewhere to go."""
    from app.llm.base import LLMProvider
    from app.llm.chain import ChainProvider

    class Fake(LLMProvider):
        def __init__(self, name):
            self.name = name
            self.has_fallback = False

        def generate_text(self, prompt, *, system=None):
            return "ok"

        def generate_structured(self, prompt, schema, *, system=None):
            return schema()

    monkeypatch.setattr("app.llm.build_provider", lambda name: Fake(name))
    chain = ChainProvider(["gemini", "groq", "ollama"])
    assert chain._build("gemini").has_fallback is True
    assert chain._build("groq").has_fallback is True
    assert chain._build("ollama").has_fallback is False, (
        "the last resort must keep its patience; it has nowhere to fall through to"
    )
