"""Every LLM provider must bound how long a single call can take.

A stalled connection with no timeout holds a worker thread for ever. Extraction
runs on a small pool, so two hung calls deadlock the whole ingestion queue --
observed in practice: one request sat at 0% CPU for five hours and blocked every
job behind it, with no error and no way to tell "slow" from "stuck".
"""

from __future__ import annotations

import inspect
from pathlib import Path

from unittest.mock import patch

import pytest

from app.config import settings


def test_gemini_client_is_constructed_with_a_timeout(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")

    with patch("google.genai.Client") as client_cls:
        from app.llm.gemini import GeminiProvider

        GeminiProvider()

    kwargs = client_cls.call_args.kwargs
    assert "http_options" in kwargs, "no http_options passed to the Gemini client"
    timeout = kwargs["http_options"].get("timeout")
    assert timeout, "the Gemini client was constructed without a timeout"
    assert 0 < timeout <= 600_000, f"implausible timeout: {timeout}ms"


def test_the_configured_timeout_is_bounded():
    assert 0 < settings.gemini_timeout_ms <= 600_000


def test_ollama_requests_are_bounded():
    source = inspect.getsource(
        __import__("app.llm.ollama", fromlist=["OllamaProvider"])
    )
    assert "timeout=" in source, "ollama posts without a timeout"


@pytest.mark.parametrize("module", ["gemini", "ollama"])
def test_no_provider_makes_an_unbounded_network_call(module: str):
    """A guard against the next provider being added without a timeout."""
    path = Path(__file__).resolve().parents[1] / "app" / "llm" / f"{module}.py"
    source = path.read_text()
    # Every outbound call site must sit near the word "timeout".
    for marker in ("httpx.post", "genai.Client"):
        if marker in source:
            index = source.index(marker)
            window = source[max(0, index - 600) : index + 600]
            assert "timeout" in window, f"{module}: {marker} has no timeout nearby"
