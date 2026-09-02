"""Gemini 2.5 Flash provider (Section 8.1 primary)."""

from __future__ import annotations

import json
import logging

from app.config import settings
from app.llm.base import LLMError, LLMProvider, TModel
from app.llm.ratelimit import (
    RateLimiter,
    is_daily_quota_exhausted,
    retry_transient,
)


logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    name = "gemini"
    # A hosted API handles the extractor fan-out concurrently, but the free tier
    # caps requests per minute, so the rate limiter -- not this number -- is what
    # actually governs throughput.
    max_concurrency = 6

    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set; cannot use the gemini provider.")
        from google import genai

        # An explicit timeout is not optional. Without one the SDK will wait on
        # a stalled connection indefinitely, and because extraction runs on a
        # small worker pool a single hung call takes a worker with it -- two of
        # them deadlock the whole ingestion queue. Observed in practice: one
        # request sat at 0% CPU for five hours and blocked every job behind it.
        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options={"timeout": settings.gemini_timeout_ms},
        )
        # Free tier is a few requests per minute per model (5 for
        # gemini-2.5-flash). Unpaced, the six-way extractor fan-out exceeds it
        # on the first document and the losing branches look like extraction
        # failures rather than quota errors.
        self._limiter = RateLimiter(settings.gemini_rpm)

        # Free-tier quota is per model per day (20/day for gemini-2.5-flash),
        # and the extraction graph spends six requests per document -- three
        # documents and the model is done for the day. Each model carries its
        # own quota, so exhausting one is not the end of the run: fail over to
        # the next and keep going. Section 8.1 anticipates exactly this
        # ("if you hit free-tier rate limits during a heavy testing push").
        self._candidates = [settings.gemini_model] + [
            m.strip()
            for m in settings.gemini_fallback_models.split(",")
            if m.strip() and m.strip() != settings.gemini_model
        ]
        self._exhausted: set[str] = set()

    @property
    def _model(self) -> str:
        """The first candidate whose daily quota is not known to be spent."""
        for model in self._candidates:
            if model not in self._exhausted:
                return model
        # Everything is spent; retry the primary so the caller sees the real
        # quota error rather than a confusing internal state error.
        return self._candidates[0]

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

    def _call(self, contents: str, config: dict, label: str):
        last: Exception | None = None

        # Walk the candidate models, retiring any whose daily quota is spent.
        for _ in range(len(self._candidates)):
            model = self._model

            def once(model=model):
                self._limiter.acquire()
                return self._client.models.generate_content(
                    model=model, contents=contents, config=config
                )

            try:
                return retry_transient(
                    once, label=f"gemini {label} [{model}]", attempts=settings.gemini_retries
                )
            except Exception as exc:
                last = exc
                if not is_daily_quota_exhausted(exc):
                    raise LLMError(f"gemini {label} failed: {exc}") from exc
                self._exhausted.add(model)
                remaining = [m for m in self._candidates if m not in self._exhausted]
                logger.warning(
                    "%s: daily free-tier quota exhausted; %s",
                    model,
                    f"falling back to {remaining[0]}" if remaining else "no models left",
                )

        raise LLMError(
            "gemini: every configured model has exhausted its daily free-tier "
            f"quota ({', '.join(self._candidates)}). Wait for the quota to reset, "
            "add more models to GEMINI_FALLBACK_MODELS, switch LLM_PROVIDER to "
            f"ollama, or upgrade the key. Last error: {last}"
        )

    @staticmethod
    def _reject_if_truncated(response, schema) -> None:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return
        reason = str(getattr(candidates[0], "finish_reason", "") or "")
        if "MAX_TOKENS" in reason.upper():
            raise LLMError(
                f"gemini response for {schema.__name__} was cut off at the output "
                f"token limit ({settings.llm_max_output_tokens}). The document "
                "produced more items than fit in one response -- raise "
                "LLM_MAX_OUTPUT_TOKENS or narrow the page selection for this "
                "field group."
            )

    def generate_text(self, prompt: str, *, system: str | None = None) -> str:
        response = self._call(prompt, self._config(system), "generate_text")
        return (response.text or "").strip()

    def generate_structured(
        self, prompt: str, schema: type[TModel], *, system: str | None = None
    ) -> TModel:
        response = self._call(
            prompt, self._config(system, schema), "generate_structured"
        )

        # A response cut off at the token limit yields half a JSON document,
        # which surfaces as a baffling "Unterminated string" parse error. Name
        # the real cause instead: the field group was too large for the budget.
        self._reject_if_truncated(response, schema)

        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, schema):
            return parsed
        try:
            return schema.model_validate(json.loads(response.text or "{}"))
        except Exception as exc:
            raise LLMError(f"gemini returned output failing {schema.__name__}: {exc}") from exc
