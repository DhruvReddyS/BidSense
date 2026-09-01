"""Ollama / Qwen2.5 provider (Section 8.1 fallback -- rate limits, offline demo)."""

from __future__ import annotations

import json

import httpx

from app.config import settings
from app.llm.base import LLMError, LLMProvider, TModel


class OllamaProvider(LLMProvider):
    name = "ollama"
    # One local GPU: run the extractors one at a time. Overriding this above 1
    # does not make Ollama faster, it just moves the queueing into HTTP timeouts.
    max_concurrency = 1

    def __init__(self) -> None:
        self._url = settings.ollama_base_url.rstrip("/")
        self._model = settings.ollama_model

    def _options(self) -> dict:
        return {
            "temperature": settings.llm_temperature,
            "num_ctx": settings.ollama_num_ctx,
        }

    def _post(self, payload: dict) -> dict:
        try:
            response = httpx.post(f"{self._url}/api/chat", json=payload, timeout=300)
            response.raise_for_status()
            return response.json()
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
        return data.get("message", {}).get("content", "").strip()

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
        raw = data.get("message", {}).get("content", "")
        try:
            return schema.model_validate(json.loads(raw))
        except Exception as exc:
            raise LLMError(f"ollama returned output failing {schema.__name__}: {exc}") from exc
