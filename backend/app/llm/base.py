"""The single LLM interface (Section 8.1).

Everything downstream -- extraction agents, RAG generation, the Level 3 router --
talks to this and only this. Swapping Gemini 2.5 Flash for Ollama/Qwen2.5 is a
change to LLM_PROVIDER in .env, not a code change.

`generate_structured` is the primary entry point on purpose: Section 8.1 calls
for schema-constrained decoding so the model cannot return malformed output.
Providers implement that with whatever native mechanism they have (Gemini's
JSON mode with a response schema, a grammar for the Ollama path).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

TModel = TypeVar("TModel", bound=BaseModel)


class LLMError(RuntimeError):
    """Provider call failed or returned output that could not be validated."""


class LLMProvider(ABC):
    """Implement this to add a provider. Nothing else should need to change."""

    name: str

    @abstractmethod
    def generate_text(self, prompt: str, *, system: str | None = None) -> str:
        """Free-form generation. Used for grounded summaries and RAG answers."""

    @abstractmethod
    def generate_structured(
        self, prompt: str, schema: type[TModel], *, system: str | None = None
    ) -> TModel:
        """Schema-constrained generation returning a validated Pydantic instance.

        Implementations must validate before returning -- callers are entitled to
        assume the result conforms, which is what keeps the extraction pipeline
        from having to defensively re-parse everywhere.
        """
