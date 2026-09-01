"""Rate limiting and 429 retry (Section 8.1 free-tier quota)."""

from __future__ import annotations

import threading
import time

import pytest

from app.llm.ratelimit import RateLimiter, retry_transient

QUOTA_ERROR = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded "
    "your current quota... Please retry in 16.78s', 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '2s'}]}}"
)


def test_limiter_spaces_requests():
    limiter = RateLimiter(requests_per_minute=600)  # 0.1s apart
    started = time.monotonic()
    for _ in range(4):
        limiter.acquire()
    elapsed = time.monotonic() - started
    assert elapsed >= 0.28, f"4 requests should take ~0.3s, took {elapsed:.2f}s"


def test_limiter_paces_parallel_callers():
    """The fan-out is what breaks the quota: six threads computing the same free
    slot and firing together. They must queue instead."""
    limiter = RateLimiter(requests_per_minute=600)
    timestamps: list[float] = []
    lock = threading.Lock()

    def worker():
        limiter.acquire()
        with lock:
            timestamps.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    timestamps.sort()
    gaps = [b - a for a, b in zip(timestamps, timestamps[1:])]
    assert all(g >= 0.08 for g in gaps), f"requests fired together: {gaps}"


def test_zero_rpm_disables_pacing():
    limiter = RateLimiter(requests_per_minute=0)
    started = time.monotonic()
    for _ in range(50):
        limiter.acquire()
    assert time.monotonic() - started < 0.1


def test_retry_honours_the_servers_own_delay(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("app.llm.ratelimit.time.sleep", slept.append)

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError(QUOTA_ERROR)
        return "ok"

    assert retry_transient(flaky) == "ok"
    assert calls["n"] == 3
    # retryDelay of 2s plus the margin, not a blind exponential guess.
    assert slept == [3.0, 3.0]


def test_non_rate_limit_errors_are_not_retried(monkeypatch):
    """Retrying a schema error burns quota and delays the real diagnosis."""
    monkeypatch.setattr("app.llm.ratelimit.time.sleep", lambda _: None)
    calls = {"n": 0}

    def broken():
        calls["n"] += 1
        raise ValueError("response failed schema validation")

    with pytest.raises(ValueError, match="schema validation"):
        retry_transient(broken)
    assert calls["n"] == 1


def test_persistent_rate_limiting_eventually_raises(monkeypatch):
    monkeypatch.setattr("app.llm.ratelimit.time.sleep", lambda _: None)
    calls = {"n": 0}

    def always_limited():
        calls["n"] += 1
        raise RuntimeError(QUOTA_ERROR)

    with pytest.raises(RuntimeError, match="RESOURCE_EXHAUSTED"):
        retry_transient(always_limited, attempts=3)
    assert calls["n"] == 3


def test_backoff_when_no_delay_is_supplied(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("app.llm.ratelimit.time.sleep", slept.append)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 too many requests")
        return "ok"

    assert retry_transient(flaky) == "ok"
    assert len(slept) == 2
    assert slept[1] > slept[0]      # exponential
    assert all(s <= 60 for s in slept)


def test_503_high_demand_is_retried(monkeypatch):
    """The shared free tier returns "This model is currently experiencing high
    demand" spikes that clear within seconds. Treating them as fatal loses a
    field group to a transient blip."""
    monkeypatch.setattr("app.llm.ratelimit.time.sleep", lambda _: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError(
                "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model "
                "is currently experiencing high demand.', 'status': 'UNAVAILABLE'}}"
            )
        return "ok"

    assert retry_transient(flaky) == "ok"
    assert calls["n"] == 3


def test_client_errors_are_still_not_retried(monkeypatch):
    monkeypatch.setattr("app.llm.ratelimit.time.sleep", lambda _: None)

    def bad_request():
        raise RuntimeError("400 INVALID_ARGUMENT: request contains an invalid field")

    with pytest.raises(RuntimeError, match="INVALID_ARGUMENT"):
        retry_transient(bad_request)


# --------------------------------------------------------------------------- #
# Daily quota vs per-minute quota
# --------------------------------------------------------------------------- #
DAILY_QUOTA_ERROR = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
    "current quota', 'details': [{'violations': [{'quotaId': "
    "'GenerateRequestsPerDayPerProjectPerModel-FreeTier', 'quotaValue': '20'}]}]}}"
)

PER_MINUTE_QUOTA_ERROR = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'details': [{'violations': "
    "[{'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', "
    "'quotaValue': '5'}]}], 'retryDelay': '16s'}}"
)


def test_daily_and_per_minute_quotas_are_distinguished():
    """They need opposite responses: a per-minute breach clears in seconds, a
    per-day cap does not clear until tomorrow."""
    from app.llm.ratelimit import is_daily_quota_exhausted

    assert is_daily_quota_exhausted(RuntimeError(DAILY_QUOTA_ERROR)) is True
    assert is_daily_quota_exhausted(RuntimeError(PER_MINUTE_QUOTA_ERROR)) is False
    assert is_daily_quota_exhausted(RuntimeError("503 UNAVAILABLE")) is False


def test_daily_quota_is_not_retried(monkeypatch):
    """Retrying a daily cap just burns the clock -- it will not clear today."""
    monkeypatch.setattr("app.llm.ratelimit.time.sleep", lambda _: None)
    calls = {"n": 0}

    def exhausted():
        calls["n"] += 1
        raise RuntimeError(DAILY_QUOTA_ERROR)

    with pytest.raises(RuntimeError):
        retry_transient(exhausted, attempts=4)
    assert calls["n"] == 1, "a daily cap must fail fast, not retry"


def test_per_minute_quota_is_still_retried(monkeypatch):
    monkeypatch.setattr("app.llm.ratelimit.time.sleep", lambda _: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError(PER_MINUTE_QUOTA_ERROR)
        return "ok"

    assert retry_transient(flaky) == "ok"
    assert calls["n"] == 2
