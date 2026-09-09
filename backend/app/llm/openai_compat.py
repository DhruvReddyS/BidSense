"""Shared provider for OpenAI-compatible chat APIs (Groq, xAI).

Both speak the same `/chat/completions` dialect and both support constrained
decoding through `response_format`, so they differ only in base URL, key and
model. One implementation with two thin subclasses beats two files that drift.

Structured output is negotiated rather than assumed: `json_schema` is requested
first because it is the only mode that actually guarantees conformance, and a
backend that rejects it falls back to `json_object` with the schema stated in
the prompt. The fallback is weaker -- the model can return conforming-looking
JSON with a missing field -- so Pydantic still validates, and a failure there is
raised rather than papered over.
"""

from __future__ import annotations

import json
import logging
import threading

import httpx

from app.llm.base import LLMError, LLMProvider, TModel
from app.llm.cleanup import strip_thinking
from app.llm.ratelimit import RateLimiter, estimate_tokens, retry_transient

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """A hosted chat API speaking OpenAI's request shape."""

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_s: int = 180
    retries: int = 3
    #: Hosted APIs absorb the six-way extractor fan-out; the rate limiter, not
    #: this number, is what governs throughput.
    max_concurrency = 6
    #: Tokens-per-minute ceiling for the account's tier. Measured, not guessed:
    #: Groq's free tier answers a 15,009-token request with
    #: `413 ... tokens per minute (TPM): Limit 8000`. A hosted provider having a
    #: SMALLER usable context than a local one is counter-intuitive and is
    #: exactly the kind of thing that shows up as unexplained failures, so it is
    #: declared here and page selection sizes itself to it.
    tokens_per_minute: int = 8000
    #: Chars per token for English legal prose, and the share of the window kept
    #: for the system prompt, the schema and the output.
    CHARS_PER_TOKEN = 3.5
    RESERVED = 0.45

    @property
    def input_char_budget(self) -> int:
        return int(self.tokens_per_minute * self.CHARS_PER_TOKEN * (1 - self.RESERVED))

    def __init__(self, *, rpm: int = 30) -> None:
        if not self.api_key:
            raise LLMError(
                f"{self.name}: no API key configured; cannot use this provider."
            )
        # Both constraints. The TPM is the one that actually binds here, and
        # pacing on requests alone made a 1,500-token question wait as long as a
        # 4,400-token extraction.
        self._limiter = RateLimiter(rpm, tokens_per_minute=self.tokens_per_minute)
        #: Set by the chain when a live tier sits below this one. A provider
        #: with somewhere to fall through to should not wait out a 60-second
        #: server retry hint.
        self.has_fallback = False
        # Whether this backend accepted a json_schema response_format. Learned
        # once from a real response rather than hard-coded per model, because
        # support varies by model within the same provider and changes over time.
        self._schema_mode: str | None = None
        self._lock = threading.Lock()
        self.last_model_used: str | None = None

    # ------------------------------------------------------------------ #
    def _messages(self, prompt: str, system: str | None) -> list[dict]:
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        return messages

    def _post(self, payload: dict) -> dict:
        cost = estimate_tokens(
            *(message.get("content") for message in payload.get("messages", []))
        )

        def once() -> dict:
            self._limiter.acquire(cost)
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_s,
            )
            if response.status_code >= 400:
                # Raised with the body attached: these APIs put the actionable
                # part (which quota, which field of the schema was rejected) in
                # the body, and a bare status code says none of it.
                raise RuntimeError(
                    f"{response.status_code} {response.text[:400]}"
                )
            return response.json()

        return retry_transient(
            once,
            attempts=2 if self.has_fallback else self.retries,
            label=f"{self.name} {self.model}",
            max_delay=8.0 if self.has_fallback else 60.0,
        )

    @staticmethod
    def _content(data: dict) -> str:
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("no choices returned")
        message = choices[0].get("message") or {}
        return (message.get("content") or "").strip()

    @staticmethod
    def _reject_if_truncated(data: dict) -> None:
        choices = data.get("choices") or []
        if choices and choices[0].get("finish_reason") == "length":
            raise LLMError(
                "response was cut off at the output token limit. The document "
                "produced more items than fit in one response -- raise the limit "
                "or narrow the page selection for this field group."
            )

    # ------------------------------------------------------------------ #
    def generate_text(self, prompt: str, *, system: str | None = None) -> str:
        from app.config import settings

        data = self._post(
            {
                "model": self.model,
                "messages": self._messages(prompt, system),
                "temperature": settings.llm_temperature,
            }
        )
        self._reject_if_truncated(data)
        with self._lock:
            self.last_model_used = self.model
        return strip_thinking(self._content(data))

    def generate_structured(
        self, prompt: str, schema: type[TModel], *, system: str | None = None
    ) -> TModel:
        from app.config import settings

        base = {
            "model": self.model,
            "messages": self._messages(prompt, system),
            "temperature": settings.llm_temperature,
        }

        for mode in self._modes():
            payload = dict(base)
            if mode == "json_schema":
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "schema": _strict_schema(schema),
                        "strict": True,
                    },
                }
            else:
                payload["response_format"] = {"type": "json_object"}
                payload["messages"] = self._messages(
                    f"{prompt}\n\nReturn ONLY a JSON object conforming to this schema:\n"
                    f"{json.dumps(schema.model_json_schema())}",
                    system,
                )

            try:
                data = self._post(payload)
            except Exception as exc:
                # A backend that rejects json_schema says so with a 400. Learn
                # it once and use the weaker mode from then on, rather than
                # paying for a failed request on every call.
                if mode == "json_schema" and _is_unsupported_format(exc):
                    logger.info(
                        "%s: %s does not accept json_schema; using json_object",
                        self.name, self.model,
                    )
                    with self._lock:
                        self._schema_mode = "json_object"
                    continue
                raise LLMError(f"{self.name} {schema.__name__} failed: {exc}") from exc

            with self._lock:
                self._schema_mode = mode
                self.last_model_used = self.model
            self._reject_if_truncated(data)
            raw = strip_thinking(self._content(data))
            if not raw:
                raise LLMError(
                    f"{self.name} returned an empty response for {schema.__name__}."
                )
            try:
                return schema.model_validate(json.loads(raw))
            except Exception as exc:
                raise LLMError(
                    f"{self.name} returned output failing {schema.__name__}: {exc}. "
                    f"First 200 characters: {raw[:200]!r}"
                ) from exc

        raise LLMError(f"{self.name}: no usable structured-output mode for {schema.__name__}")

    def _modes(self) -> list[str]:
        with self._lock:
            known = self._schema_mode
        return [known] if known else ["json_schema", "json_object"]


def _is_unsupported_format(exc: Exception) -> bool:
    text = str(exc).lower()
    return "400" in text and any(
        marker in text
        for marker in ("response_format", "json_schema", "not supported", "unsupported")
    )


def _strict_schema(schema: type[TModel]) -> dict:
    """Pydantic's JSON schema, adjusted for strict structured-output mode.

    Strict mode requires `additionalProperties: false` on every object and every
    property listed in `required` -- optional fields included, expressed as a
    nullable type instead. Pydantic emits neither, so a raw schema is rejected
    with a 400 that names none of this.
    """
    document = schema.model_json_schema()

    def fix(node: dict) -> dict:
        if not isinstance(node, dict):
            return node
        if node.get("type") == "object" or "properties" in node:
            node["additionalProperties"] = False
            properties = node.get("properties", {})
            node["required"] = list(properties)
            for value in properties.values():
                fix(value)
        for key in ("items", "$defs", "definitions"):
            child = node.get(key)
            if isinstance(child, dict):
                if key in ("$defs", "definitions"):
                    for value in child.values():
                        fix(value)
                else:
                    fix(child)
        for key in ("anyOf", "oneOf", "allOf"):
            for value in node.get(key, []) or []:
                fix(value)
        return node

    return fix(document)
