"""xAI / Grok provider (Section 8.1 tier 2 alternative).

Same role as Groq and the same OpenAI-compatible dialect, kept as a separate
tier so the chain has two independent hosted fallbacks rather than one. Two
providers sharing a single outage is far less likely than one having it.
"""

from __future__ import annotations

from app.config import settings
from app.llm.openai_compat import OpenAICompatibleProvider


class XAIProvider(OpenAICompatibleProvider):
    name = "xai"
    base_url = "https://api.x.ai/v1"

    def __init__(self) -> None:
        self.api_key = settings.xai_api_key or ""
        self.model = settings.xai_model
        self.timeout_s = settings.xai_timeout_s
        self.retries = settings.xai_retries
        self.tokens_per_minute = settings.xai_tpm
        super().__init__(rpm=settings.xai_rpm)
