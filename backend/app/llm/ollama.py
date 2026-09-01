"""Ollama / Qwen2.5 provider (Section 8.1 fallback -- rate limits, offline demo)."""

from __future__ import annotations

import json

import httpx

from app.config import settings
from app.llm.base import LLMError, LLMProvider, TModel


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self) -> None:
        self._url = settings.ollama_base_url.rstrip("/")
        self._model = settings.ollama_model

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
                "options": {"temperature": settings.llm_temperature},
            }
        )
        return data.get("message", {}).get("content", "").strip()

    def generate_structured(
        self, prompt: str, schema: type[TModel], *, system: str | None = None
    ) -> TModel:
        # Ollama constrains decoding to a JSON Schema when `format` is a schema
        # object -- the local equivalent of Gemini's response_schema.
        data = self._post(
            {
                "model": self._model,
                "messages": self._messages(prompt, system),
                "stream": False,
                "format": schema.model_json_schema(),
                "options": {"temperature": settings.llm_temperature},
            }
        )
        raw = data.get("message", {}).get("content", "")
        try:
            return schema.model_validate(json.loads(raw))
        except Exception as exc:
            raise LLMError(f"ollama returned output failing {schema.__name__}: {exc}") from exc
