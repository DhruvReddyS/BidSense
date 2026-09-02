"""LLM provider factory (Section 8.1).

    from app.llm import get_llm
    llm = get_llm()                 # honours LLM_PROVIDER
    result = llm.generate_structured(prompt, TenderNotification)

`LLM_PROVIDER=chain` walks LLM_CHAIN in order (Gemini -> Groq -> Ollama),
retiring tiers that are spent. See `app.llm.chain` for why the middle tier
exists.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.llm.base import LLMError, LLMProvider

__all__ = ["LLMError", "LLMProvider", "get_llm", "build_provider"]


def build_provider(choice: str) -> LLMProvider:
    """Construct one named provider. No caching -- `get_llm` owns that."""
    choice = choice.strip().lower()
    if choice == "gemini":
        from app.llm.gemini import GeminiProvider

        return GeminiProvider()
    if choice == "groq":
        from app.llm.groq import GroqProvider

        return GroqProvider()
    if choice == "xai":
        from app.llm.xai import XAIProvider

        return XAIProvider()
    if choice == "ollama":
        from app.llm.ollama import OllamaProvider

        return OllamaProvider()
    raise LLMError(
        f"Unknown LLM provider {choice!r}; expected one of "
        "gemini, groq, xai, ollama, chain."
    )


@lru_cache(maxsize=4)
def get_llm(provider: str | None = None) -> LLMProvider:
    choice = (provider or settings.llm_provider).lower()
    if choice == "chain":
        from app.llm.chain import ChainProvider

        return ChainProvider([n.strip() for n in settings.llm_chain.split(",") if n.strip()])
    return build_provider(choice)
