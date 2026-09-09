"""Model failover when a daily free-tier quota is exhausted (Section 8.1).

The free tier caps requests per model per day (20/day for gemini-2.5-flash) and
the extraction graph spends six per document. Each model carries its own quota,
so exhausting one must not end the run.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.llm.base import LLMError

DAILY = (
    "429 RESOURCE_EXHAUSTED {'violations': [{'quotaId': "
    "'GenerateRequestsPerDayPerProjectPerModel-FreeTier', 'quotaValue': '20'}]}"
)


@pytest.fixture
def provider(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_model", "model-a")
    monkeypatch.setattr(settings, "gemini_fallback_models", "model-b,model-c")
    monkeypatch.setattr(settings, "gemini_rpm", 0)          # no pacing in tests
    monkeypatch.setattr(settings, "gemini_retries", 2)

    with patch("google.genai.Client") as client_cls:
        from app.llm.gemini import GeminiProvider

        instance = GeminiProvider()
        instance._client = client_cls.return_value
        yield instance


def _response(text: str = '{"tender_id": "T-1"}'):
    response = MagicMock()
    response.text = text
    response.parsed = None
    response.candidates = [MagicMock(finish_reason="STOP")]
    return response


def test_candidate_order_starts_with_the_configured_model(provider):
    assert provider._candidates == ["model-a", "model-b", "model-c"]
    assert provider._model == "model-a"


def test_exhausted_model_is_retired_and_the_next_is_used(provider):
    calls: list[str] = []

    def generate(model, contents, config):
        calls.append(model)
        if model == "model-a":
            raise RuntimeError(DAILY)
        return _response()

    provider._client.models.generate_content.side_effect = generate

    assert provider.generate_text("hi") == '{"tender_id": "T-1"}'
    assert calls == ["model-a", "model-b"]
    assert provider._model == "model-b", "the spent model must not be retried"


def test_subsequent_calls_skip_the_exhausted_model(provider):
    calls: list[str] = []

    def generate(model, contents, config):
        calls.append(model)
        if model == "model-a":
            raise RuntimeError(DAILY)
        return _response()

    provider._client.models.generate_content.side_effect = generate

    provider.generate_text("first")
    calls.clear()
    provider.generate_text("second")
    assert calls == ["model-b"], "model-a should not be tried again today"


def test_all_models_exhausted_gives_an_actionable_error(provider):
    provider._client.models.generate_content.side_effect = RuntimeError(DAILY)

    with pytest.raises(LLMError) as exc:
        provider.generate_text("hi")

    message = str(exc.value)
    assert "every configured model has exhausted" in message
    assert "model-a" in message and "model-c" in message
    # The message must say what to actually do about it.
    assert "ollama" in message.lower()


def test_non_quota_errors_do_not_trigger_failover(provider):
    """A schema or auth error is not fixed by switching models, and burning the
    fallbacks on it would hide the real problem."""
    calls: list[str] = []

    def generate(model, contents, config):
        calls.append(model)
        raise RuntimeError("400 INVALID_ARGUMENT: bad request")

    provider._client.models.generate_content.side_effect = generate

    with pytest.raises(LLMError, match="INVALID_ARGUMENT"):
        provider.generate_text("hi")
    assert calls == ["model-a"]
    assert provider._exhausted == set()


def test_truncated_response_is_named_not_left_as_a_json_error(provider):
    """A response cut off at the token limit yields half a JSON document, which
    surfaces as a baffling 'Unterminated string' parse error."""
    from app.extraction.llm_schemas import RawHeader

    truncated = _response('{"tender_id": "T-1", "title": "Supply of')
    truncated.candidates = [MagicMock(finish_reason="MAX_TOKENS")]
    provider._client.models.generate_content.return_value = truncated

    with pytest.raises(LLMError, match="cut off at the output token limit"):
        provider.generate_structured("hi", RawHeader)


# --------------------------------------------------------------------------- #
# Concurrent failover: the fan-out must retire a model ONCE, not once per thread
# --------------------------------------------------------------------------- #
def test_a_parallel_fan_out_spends_one_request_discovering_a_dead_model(provider):
    """Six extractors start together and all pick the same model.

    Before the post-slot re-check, every one of them queued behind the rate
    limiter and spent its turn finding out the model was already retired. At the
    free tier's 5 requests per minute that is roughly a minute of wall clock
    burned per model, on a run whose entire budget is a few minutes. Observed in
    a real run as five identical "quota exhausted" lines for one model.

    Asserted on the number of requests actually issued against the dead model,
    not on the log output -- the log is a symptom, the wasted request is the cost.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    attempts: list[str] = []
    lock = threading.Lock()

    def fake_generate_content(model, contents, config):
        with lock:
            attempts.append(model)
        if model == provider._candidates[0]:
            raise RuntimeError(DAILY)
        return _response()

    provider._client.models.generate_content.side_effect = fake_generate_content
    # Pacing is what creates the window; keep it, but small enough to be a test.
    provider._limiter = _FastLimiter()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = [
            pool.submit(provider._call, "prompt", {}, "generate_text") for _ in range(6)
        ]
        for future in results:
            future.result()

    dead = provider._candidates[0]
    spent_on_dead = attempts.count(dead)
    assert spent_on_dead == 1, (
        f"{spent_on_dead} requests were spent on a model already known to be "
        f"exhausted (attempts: {attempts})"
    )
    assert len(attempts) == 7, f"expected 1 doomed + 6 real requests, got {attempts}"


def test_every_caller_still_gets_an_answer_after_the_failover(provider):
    """The saving must not come from dropping work. All six still succeed."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    lock = threading.Lock()
    calls: list[str] = []

    def fake_generate_content(model, contents, config):
        with lock:
            calls.append(model)
        if model == provider._candidates[0]:
            raise RuntimeError(DAILY)
        return _response()

    provider._client.models.generate_content.side_effect = fake_generate_content
    provider._limiter = _FastLimiter()

    with ThreadPoolExecutor(max_workers=6) as pool:
        answers = [
            f.result()
            for f in [pool.submit(provider._call, "p", {}, "generate_text") for _ in range(6)]
        ]
    assert len(answers) == 6
    assert all(a is not None for a in answers)


def test_all_models_retired_stops_calling_rather_than_firing_a_doomed_request(provider):
    """With nothing live left, the actionable quota error is raised without
    spending another request on a model already known to be dead."""
    attempts: list[str] = []

    def fake_generate_content(model, contents, config):
        attempts.append(model)
        raise RuntimeError(DAILY)

    provider._client.models.generate_content.side_effect = fake_generate_content
    provider._limiter = _FastLimiter()

    with pytest.raises(LLMError) as exc:
        provider._call("prompt", {}, "generate_text")

    assert "every configured model has exhausted" in str(exc.value)
    # One request per model, and not one more.
    assert len(attempts) == len(provider._candidates), attempts


class _FastLimiter:
    """A rate limiter that still serialises callers but does not sleep for real."""

    def __init__(self):
        self._lock = __import__("threading").Lock()

    def acquire(self, tokens=0):
        with self._lock:
            __import__("time").sleep(0.01)
