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
