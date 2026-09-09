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

import threading
from abc import ABC, abstractmethod
from functools import cached_property
from contextvars import ContextVar
from typing import TypeVar

from pydantic import BaseModel

TModel = TypeVar("TModel", bound=BaseModel)


class LLMError(RuntimeError):
    """Provider call failed or returned output that could not be validated."""


class LLMProvider(ABC):
    """Implement this to add a provider. Nothing else should need to change."""

    name: str

    #: How many requests this backend can usefully handle at once. A hosted API
    #: absorbs a fan-out; a single local GPU does not -- it serializes the
    #: requests internally while every caller's clock runs, so firing six
    #: extractors at once there produces six timeouts instead of six results.
    max_concurrency: int = 1

    @cached_property
    def _served_model(self) -> ContextVar[str | None]:
        return ContextVar(f"served_model_{id(self)}", default=None)

    @property
    def last_model_used(self) -> str | None:
        """The model serving this execution context, never another worker's."""
        return self._served_model.get()

    @last_model_used.setter
    def last_model_used(self, value: str | None) -> None:
        self._served_model.set(value)

    @property
    def input_char_budget(self) -> int | None:
        """How much document text this backend can be sent in one call.

        None means "no practical limit at this project's document sizes", which
        is the honest answer for the hosted models. A local model has a hard
        context window that the OUTPUT also comes out of, and exceeding it
        truncates silently -- the request succeeds and the answer is drawn from
        whatever survived the cut. Page selection asks for this so a budget
        tuned for a hosted context is not sent to a 16k local one.
        """
        return None

    @cached_property
    def _gate(self) -> threading.Semaphore:
        return threading.Semaphore(self.max_concurrency)

    def __enter__(self):  # pragma: no cover - trivial
        self._gate.acquire()
        return self

    def __exit__(self, *exc):  # pragma: no cover - trivial
        self._gate.release()
        return False

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

    def generate_structured_from(self, prompt_factory, schema: type[TModel], *, system=None) -> TModel:
        """Build document context for this provider's window at call time."""
        return self.generate_structured(
            prompt_factory(self.input_char_budget), schema, system=system
        )
