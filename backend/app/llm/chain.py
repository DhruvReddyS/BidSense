"""Ordered provider fallback (Section 8.1).

    Gemini  ->  Groq  ->  Ollama
    hosted      hosted     local
    frontier    fast       offline last resort

The middle tier exists because of arithmetic, not preference. Gemini's free tier
allows twenty requests per model per day and the extraction graph spends six per
document, so exhaustion is the ordinary case rather than an edge case. Before
this, exhausting Gemini dropped straight to a 4B local model -- a far bigger
quality drop than the situation calls for, when a second hosted provider with its
own quota was available.

Two things this gets right that a naive loop does not:

  RETIREMENT   a tier that fails for a PERSISTENT reason -- quota spent for the
               day, key rejected, account out of credit -- is retired for the
               life of the process. The same lesson as Gemini's internal model
               failover: without it, every one of six parallel extractors pays a
               full rate-limited request to rediscover a tier that is already
               known to be dead.
  HONESTY      `active_provider` reports which tier actually answered, so a
               report produced by the local fallback can say so. A silent
               downgrade is how a degraded extraction gets presented as a clean
               one, which is the failure the whole validation pass exists for.
"""

from __future__ import annotations

import logging
import threading

from app.llm.base import LLMError, LLMProvider, TModel

logger = logging.getLogger(__name__)

# Failures that mean "do not come back to this tier today". Anything else -- a
# timeout, a 500, a malformed response -- is treated as transient: the tier's own
# retry has already had its go, and one bad document should not retire a
# provider for every document after it.
_PERSISTENT_MARKERS = (
    "exhausted its daily free-tier quota",
    "every configured model has exhausted",
    "permission-denied",
    "permission_denied",
    "used all available credits",
    "spending limit",
    "invalid_api_key",
    "invalid api key",
    "no api key configured",
    "401",
    "403",
    "model_not_found",
    "does not exist or you do not have access",
)


def _is_persistent(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _PERSISTENT_MARKERS)


class ChainProvider(LLMProvider):
    """Tries each provider in turn, remembering which ones are spent."""

    name = "chain"

    def __init__(self, names: list[str]) -> None:
        self._names = names
        self._built: dict[str, LLMProvider] = {}
        self._retired: dict[str, str] = {}
        self._lock = threading.Lock()
        self._last_used: str | None = None
        if not names:
            raise LLMError("LLM_CHAIN is empty; nothing to call.")

    # ------------------------------------------------------------------ #
    @property
    def max_concurrency(self) -> int:
        """The concurrency of whichever tier is currently live.

        Taken from the live tier rather than fixed, because the tiers differ by
        six-fold: a hosted API absorbs the extractor fan-out, a single local GPU
        serialises it internally while every caller's clock runs.
        """
        provider = self._peek()
        return provider.max_concurrency if provider else 1

    @property
    def input_char_budget(self) -> int | None:
        provider = self._peek()
        return provider.input_char_budget if provider else None

    @property
    def active_provider(self) -> str | None:
        """Which tier answered the last call. None before the first one."""
        return self._last_used

    @property
    def retired(self) -> dict[str, str]:
        with self._lock:
            return dict(self._retired)

    # ------------------------------------------------------------------ #
    def _build(self, name: str) -> LLMProvider:
        if name not in self._built:
            from app.llm import build_provider

            self._built[name] = build_provider(name)
        return self._built[name]

    def _peek(self) -> LLMProvider | None:
        """The first live tier, without calling it. Construction failures (no
        key configured) retire the tier just as a rejected key would."""
        for name in self._names:
            with self._lock:
                if name in self._retired:
                    continue
            try:
                return self._build(name)
            except Exception as exc:
                self._retire(name, str(exc)[:200])
        return None

    def _retire(self, name: str, reason: str) -> None:
        with self._lock:
            if name in self._retired:
                return
            self._retired[name] = reason
            remaining = [n for n in self._names if n not in self._retired]
        logger.warning(
            "llm tier %s retired (%s); %s",
            name, reason,
            f"falling back to {remaining[0]}" if remaining else "no tiers left",
        )

    def _call(self, method: str, *args, **kwargs):
        errors: list[str] = []
        for name in self._names:
            with self._lock:
                retired = name in self._retired
            if retired:
                continue

            try:
                provider = self._build(name)
            except Exception as exc:
                self._retire(name, str(exc)[:200])
                errors.append(f"{name}: {exc}")
                continue

            try:
                result = getattr(provider, method)(*args, **kwargs)
            except Exception as exc:
                errors.append(f"{name}: {str(exc)[:300]}")
                if _is_persistent(exc):
                    self._retire(name, str(exc)[:200])
                else:
                    logger.warning("llm tier %s failed, trying the next: %s", name, str(exc)[:200])
                continue

            with self._lock:
                # `last_model_used` is the model that actually served the call.
                # Reading the provider's "current" model instead reports whatever
                # it would pick NEXT, which after a mid-call retirement is a
                # different model from the one that answered.
                served = getattr(provider, "last_model_used", None)
                self._last_used = f"{name}:{served}" if served else name
            return result

        raise LLMError(
            "every LLM tier failed or is exhausted ("
            + ", ".join(self._names)
            + "). "
            + " | ".join(errors)
        )

    def generate_text(self, prompt: str, *, system: str | None = None) -> str:
        return self._call("generate_text", prompt, system=system)

    def generate_structured(
        self, prompt: str, schema: type[TModel], *, system: str | None = None
    ) -> TModel:
        return self._call("generate_structured", prompt, schema, system=system)
