"""LLM provider factory (Section 8.1).

    from app.llm import get_llm
    llm = get_llm()                 # honours LLM_PROVIDER
    result = llm.generate_structured(prompt, TenderNotification)
"""

from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.llm.base import LLMError, LLMProvider

__all__ = ["LLMError", "LLMProvider", "get_llm"]


@lru_cache(maxsize=2)
def get_llm(provider: str | None = None) -> LLMProvider:
    choice = (provider or settings.llm_provider).lower()
    if choice == "gemini":
        from app.llm.gemini import GeminiProvider

        return GeminiProvider()
    if choice == "ollama":
        from app.llm.ollama import OllamaProvider

        return OllamaProvider()
    raise LLMError(f"Unknown LLM_PROVIDER {choice!r}; expected 'gemini' or 'ollama'.")
