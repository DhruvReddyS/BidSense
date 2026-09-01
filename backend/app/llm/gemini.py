"""Gemini 2.5 Flash provider (Section 8.1 primary)."""

from __future__ import annotations

import json

from app.config import settings
from app.llm.base import LLMError, LLMProvider, TModel


class GeminiProvider(LLMProvider):
    name = "gemini"
    # A hosted API handles the extractor fan-out concurrently.
    max_concurrency = 6

    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set; cannot use the gemini provider.")
        from google import genai

        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    def _config(self, system: str | None, schema: type[TModel] | None = None) -> dict:
        cfg: dict = {
            "temperature": settings.llm_temperature,
            "max_output_tokens": settings.llm_max_output_tokens,
        }
        if system:
            cfg["system_instruction"] = system
        if schema is not None:
            # Native structured output -- the model cannot return non-conforming JSON.
            cfg["response_mime_type"] = "application/json"
            cfg["response_schema"] = schema
        return cfg

    def generate_text(self, prompt: str, *, system: str | None = None) -> str:
        try:
            response = self._client.models.generate_content(
                model=self._model, contents=prompt, config=self._config(system)
            )
        except Exception as exc:
            raise LLMError(f"gemini generate_text failed: {exc}") from exc
        return (response.text or "").strip()

    def generate_structured(
        self, prompt: str, schema: type[TModel], *, system: str | None = None
    ) -> TModel:
        try:
            response = self._client.models.generate_content(
                model=self._model, contents=prompt, config=self._config(system, schema)
            )
        except Exception as exc:
            raise LLMError(f"gemini generate_structured failed: {exc}") from exc

        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, schema):
            return parsed
        try:
            return schema.model_validate(json.loads(response.text or "{}"))
        except Exception as exc:
            raise LLMError(f"gemini returned output failing {schema.__name__}: {exc}") from exc
