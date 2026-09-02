"""Groq provider (Section 8.1 tier 2).

Sits between Gemini and the local model for one reason: Gemini's free tier is
twenty requests per model per day against six requests per document, so quota
exhaustion is the normal case rather than an edge case, and falling straight
from a hosted frontier model to a 4B local one is a bigger quality drop than the
situation calls for. Groq has its own quota and its own hardware, so tier 2
absorbs most exhaustion without leaving hosted inference at all.

Still needs internet. Ollama remains the offline last resort.
"""

from __future__ import annotations

from app.config import settings
from app.llm.openai_compat import OpenAICompatibleProvider


class GroqProvider(OpenAICompatibleProvider):
    name = "groq"
    base_url = "https://api.groq.com/openai/v1"

    def __init__(self) -> None:
        self.api_key = settings.groq_api_key or ""
        self.model = settings.groq_model
        self.timeout_s = settings.groq_timeout_s
        self.retries = settings.groq_retries
        self.tokens_per_minute = settings.groq_tpm
        super().__init__(rpm=settings.groq_rpm)
