"""The ordered provider chain: Gemini -> Groq -> Ollama (Section 8.1).

The middle tier exists because of arithmetic. Gemini's free tier allows twenty
requests per model per day and the extraction graph spends six per document, so
exhaustion is the ordinary case. Falling from a hosted frontier model straight
to a 4B local one is a far bigger quality drop than the situation calls for when
a second hosted provider with its own quota is available.

Every scenario here was also run against the real APIs before being written down
-- tier 2 answering a genuinely exhausted Gemini in 2.4s against Gemini's own
207s, tier 3 answering when both hosted tiers were dead. These tests pin the
behaviour so it cannot regress without a key.
"""

from __future__ import annotations

import pytest

from app.llm.base import LLMError, LLMProvider
from app.llm.chain import ChainProvider, _is_persistent

DAILY_QUOTA = (
    "gemini: every configured model has exhausted its daily free-tier quota "
    "(gemini-3.6-flash, gemini-3.5-flash)."
)


class FakeProvider(LLMProvider):
    """A tier that answers, or fails in a chosen way, and counts its calls."""

    max_concurrency = 4

    def __init__(self, name: str, *, fail: Exception | None = None, answer: str = "ok"):
        self.name = name
        self.model = f"{name}-model"
        self.last_model_used: str | None = None
        self._fail = fail
        self._answer = answer
        self.calls = 0

    def generate_text(self, prompt, *, system=None):
        self.calls += 1
        if self._fail:
            raise self._fail
        self.last_model_used = self.model
        return self._answer

    def generate_structured(self, prompt, schema, *, system=None):
        self.calls += 1
        if self._fail:
            raise self._fail
        self.last_model_used = self.model
        return schema()


def _chain(monkeypatch, **tiers: FakeProvider) -> ChainProvider:
    monkeypatch.setattr("app.llm.build_provider", lambda name: tiers[name])
    return ChainProvider(list(tiers))


# --------------------------------------------------------------------------- #
# Falling through
# --------------------------------------------------------------------------- #
def test_tier_two_answers_when_the_primary_is_exhausted(monkeypatch) -> None:
    gemini = FakeProvider("gemini", fail=LLMError(DAILY_QUOTA))
    groq = FakeProvider("groq", answer="from groq")
    chain = _chain(monkeypatch, gemini=gemini, groq=groq, ollama=FakeProvider("ollama"))

    assert chain.generate_text("hi") == "from groq"
    assert chain.active_provider == "groq:groq-model"
    assert "gemini" in chain.retired


def test_tier_three_answers_when_both_hosted_tiers_are_gone(monkeypatch) -> None:
    chain = _chain(
        monkeypatch,
        gemini=FakeProvider("gemini", fail=LLMError(DAILY_QUOTA)),
        groq=FakeProvider("groq", fail=LLMError("403 permission-denied: out of credits")),
        ollama=FakeProvider("ollama", answer="from ollama"),
    )
    assert chain.generate_text("hi") == "from ollama"
    assert chain.active_provider == "ollama:ollama-model"
    assert set(chain.retired) == {"gemini", "groq"}


def test_a_tier_that_cannot_even_be_constructed_is_skipped(monkeypatch) -> None:
    """A missing key is a configuration fact, not a runtime failure. It must not
    take the whole chain down."""
    groq = FakeProvider("groq", answer="from groq")

    def build(name):
        if name == "gemini":
            raise LLMError("GEMINI_API_KEY is not set; cannot use the gemini provider.")
        return {"groq": groq, "ollama": FakeProvider("ollama")}[name]

    monkeypatch.setattr("app.llm.build_provider", build)
    chain = ChainProvider(["gemini", "groq", "ollama"])
    assert chain.generate_text("hi") == "from groq"
    assert "GEMINI_API_KEY" in chain.retired["gemini"]


# --------------------------------------------------------------------------- #
# Retirement: the lesson from the Gemini fan-out
# --------------------------------------------------------------------------- #
def test_a_retired_tier_is_never_called_again(monkeypatch) -> None:
    """Without this, six parallel extractors each pay a full rate-limited
    request to rediscover a tier already known to be dead -- exactly the waste
    measured and fixed inside the Gemini provider."""
    gemini = FakeProvider("gemini", fail=LLMError(DAILY_QUOTA))
    groq = FakeProvider("groq")
    chain = _chain(monkeypatch, gemini=gemini, groq=groq, ollama=FakeProvider("ollama"))

    for _ in range(5):
        chain.generate_text("hi")

    assert gemini.calls == 1, f"the dead tier was probed {gemini.calls} times"
    assert groq.calls == 5


def test_a_transient_failure_does_not_retire_a_tier(monkeypatch) -> None:
    """One bad document must not disable a provider for every document after it.
    The tier's own retry has already had its go."""
    gemini = FakeProvider("gemini", fail=LLMError("500 INTERNAL: transient"))
    chain = _chain(monkeypatch, gemini=gemini, groq=FakeProvider("groq"))

    chain.generate_text("hi")
    assert "gemini" not in chain.retired
    chain.generate_text("hi")
    assert gemini.calls == 2, "a transient failure wrongly retired the tier"


@pytest.mark.parametrize(
    "message",
    [
        DAILY_QUOTA,
        "403 permission-denied: used all available credits",
        "401 invalid_api_key",
        "404 model_not_found: llama-3.3-70b-versatile does not exist",
        "groq: no API key configured; cannot use this provider.",
    ],
)
def test_persistent_failures_retire_the_tier(message) -> None:
    assert _is_persistent(LLMError(message))


@pytest.mark.parametrize(
    "message",
    [
        "500 INTERNAL",
        "503 UNAVAILABLE: model overloaded",
        "returned output failing RawHeader: Expecting value",
        "read timed out",
    ],
)
def test_transient_failures_do_not_retire_the_tier(message) -> None:
    assert not _is_persistent(LLMError(message))


# --------------------------------------------------------------------------- #
# Honesty about which tier answered
# --------------------------------------------------------------------------- #
def test_the_chain_reports_the_tier_and_model_that_actually_answered(monkeypatch) -> None:
    """A silent downgrade is how a degraded extraction gets presented as a clean
    one. `active_provider` is what lets a report say it came from the fallback."""
    chain = _chain(
        monkeypatch,
        gemini=FakeProvider("gemini", fail=LLMError(DAILY_QUOTA)),
        groq=FakeProvider("groq"),
    )
    assert chain.active_provider is None
    chain.generate_text("hi")
    assert chain.active_provider == "groq:groq-model"


def test_concurrency_and_budget_track_the_live_tier(monkeypatch) -> None:
    """The tiers differ six-fold in what they can absorb, and the local tier has
    a hard context window the hosted ones do not. Fixing either at the chain
    level sends a hosted-sized selection to a local model."""
    gemini = FakeProvider("gemini")
    gemini.max_concurrency = 6
    ollama = FakeProvider("ollama")
    ollama.max_concurrency = 1
    chain = _chain(monkeypatch, gemini=gemini, ollama=ollama)

    assert chain.max_concurrency == 6
    chain._retire("gemini", "forced")
    assert chain.max_concurrency == 1


def test_every_tier_failing_gives_one_error_naming_all_of_them(monkeypatch) -> None:
    chain = _chain(
        monkeypatch,
        gemini=FakeProvider("gemini", fail=LLMError(DAILY_QUOTA)),
        groq=FakeProvider("groq", fail=LLMError("403 permission-denied")),
        ollama=FakeProvider("ollama", fail=LLMError("connection refused")),
    )
    with pytest.raises(LLMError) as exc:
        chain.generate_text("hi")
    message = str(exc.value)
    for tier in ("gemini", "groq", "ollama"):
        assert tier in message


def test_an_empty_chain_is_rejected_at_construction() -> None:
    with pytest.raises(LLMError):
        ChainProvider([])


def test_the_default_chain_puts_the_local_model_last() -> None:
    """Ordering is the whole design. A local 4B model ahead of a hosted one
    would be a quality regression on every document."""
    from app.config import settings

    tiers = [t.strip() for t in settings.llm_chain.split(",")]
    assert tiers[0] == "gemini"
    assert tiers[-1] == "ollama"
    assert "groq" in tiers
