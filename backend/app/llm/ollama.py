"""Ollama / Qwen2.5 provider (Section 8.1 fallback -- rate limits, offline demo)."""

from __future__ import annotations

import json

import httpx

from app.config import settings
from app.llm.base import LLMError, LLMProvider, TModel
from app.llm.cleanup import strip_thinking
from app.llm.ratelimit import retry_transient


class OllamaProvider(LLMProvider):
    name = "ollama"
    # One local GPU: run the extractors one at a time. Overriding this above 1
    # does not make Ollama faster, it just moves the queueing into HTTP timeouts.
    max_concurrency = 1

    def __init__(self) -> None:
        self._url = settings.ollama_base_url.rstrip("/")
        self._model = settings.ollama_model
        self.last_model_used: str | None = None

    #: Roughly how many characters of English legal prose a token holds. Used
    #: only to size the page-selection budget, so an approximation is fine --
    #: what matters is not being out by a factor.
    CHARS_PER_TOKEN = 3.5
    #: Share of the window left for the system prompt, the JSON schema and the
    #: model's own output. The output comes out of the SAME window on a local
    #: model, which is what makes a naive budget truncate the document.
    RESERVED = 0.45

    @property
    def input_char_budget(self) -> int:
        return int(settings.ollama_num_ctx * self.CHARS_PER_TOKEN * (1 - self.RESERVED))

    def _options(self) -> dict:
        return {
            "temperature": settings.llm_temperature,
            "num_ctx": settings.ollama_num_ctx,
        }

    def _post(self, payload: dict) -> dict:
        """POST to Ollama, retrying transport failures.

        Ollama had no retry at all: a connection reset while the model was
        loading -- which happens routinely, because loading a 5GB model into
        VRAM takes seconds during which the server is up but not answering --
        ended the whole document's extraction. The Gemini path had retried the
        equivalent failure since the beginning; this was simply a gap.

        Fewer attempts than the hosted path. A local retry re-runs generation
        from scratch on hardware that is already the bottleneck, so the useful
        number is "once or twice more", not "until the quota window rolls".
        """

        def once() -> dict:
            response = httpx.post(
                f"{self._url}/api/chat", json=payload, timeout=settings.ollama_timeout_s
            )
            response.raise_for_status()
            return response.json()

        try:
            return retry_transient(
                once, attempts=settings.ollama_retries, label=f"ollama {self._model}"
            )
        except Exception as exc:
            raise LLMError(f"ollama call failed: {exc}") from exc

    def _messages(self, prompt: str, system: str | None) -> list[dict]:
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        return messages

    def generate_text(self, prompt: str, *, system: str | None = None) -> str:
        data = self._post(
            {
                "model": self._model,
                "messages": self._messages(prompt, system),
                "stream": False,
                "think": settings.ollama_think,
                "options": self._options(),
            }
        )
        # Reasoning models emit their chain of thought in the body, closed by a
        # </think> tag, even when `think: false` suppresses the opening tag.
        # Stripped here rather than at each call site: it is a property of this
        # provider, and the RAG layer is not the only thing that reads text.
        self.last_model_used = self._model
        return strip_thinking(data.get("message", {}).get("content", "").strip())

    def generate_structured(
        self, prompt: str, schema: type[TModel], *, system: str | None = None
    ) -> TModel:
        data = self._post(
            {
                "model": self._model,
                "messages": self._messages(prompt, system),
                "stream": False,
                # Ollama constrains decoding to this JSON Schema -- the local
                # equivalent of Gemini's response_schema (Section 8.1).
                "format": schema.model_json_schema(),
                "think": settings.ollama_think,
                "options": self._options(),
            }
        )
        self.last_model_used = self._model
        raw = data.get("message", {}).get("content", "")

        # An empty body is a distinct failure with a distinct cause, and it
        # surfaces from json.loads as "Expecting value: line 1 column 1
        # (char 0)" -- which says nothing about what went wrong. Observed with
        # gpt-oss-20b against a 17k-token prompt: the model returned nothing at
        # all rather than failing, and the parse error was the only symptom.
        if not raw.strip():
            raise LLMError(
                f"ollama returned an empty response for {schema.__name__}. The "
                f"model ({self._model}) produced no output -- usually the prompt "
                f"exceeded its context window (OLLAMA_NUM_CTX={settings.ollama_num_ctx}), "
                "or the model does not support schema-constrained decoding. Try a "
                "larger context, a smaller page-selection budget, or another model."
            )

        try:
            return schema.model_validate(json.loads(raw))
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(
                f"ollama returned output failing {schema.__name__}: {exc}. "
                f"First 200 characters: {raw[:200]!r}"
            ) from exc
