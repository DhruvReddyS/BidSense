"""Strip a reasoning model's thinking block from its answer.

Qwen3 and the other reasoning-tuned local models emit their chain of thought in
the response body, delimited by `<think>` tags, and then the actual answer. Even
with Ollama's `think: false`, which suppresses the OPENING tag, the closing
`</think>` still arrives -- so the response looks like:

    Okay, I need to figure out what the EMD is. Starting with source [1]...
    ... 2,000 characters of deliberation ...
    Yes, so the answer is Rs. 31,500 [5].
    </think>

    Rs. 31,500 [5]

Measured on eight real questions against a real tender: every one carried the
tag, raw responses ran 1,438 to 10,149 characters, and the answer after the tag
ran 7 to 470. Splitting on the delimiter recovered a clean answer in all eight.

This is why sentence-level heuristics were the wrong tool for it. Deciding
whether "First, I notice the source [1] states ..." is narration or answer is a
judgment call that gets it right most of the time; the model is telling us
exactly where its reasoning ends, and reading that is not a judgment call at
all. The heuristic in `app.rag.answer` still runs afterwards, for models that
narrate without marking it.
"""

from __future__ import annotations

import re

__all__ = ["strip_thinking", "THINK_CLOSE"]

THINK_CLOSE = "</think>"

# Paired blocks first: <think>...</think>, and the variants different builds use.
_PAIRED = re.compile(
    r"<(think|thinking|reasoning|scratchpad)\b[^>]*>.*?</\1\s*>",
    re.DOTALL | re.IGNORECASE,
)
# An unmatched closing tag, which is what `think: false` actually produces: the
# opener is suppressed, the reasoning is emitted anyway, and the closer marks
# where it ends. Everything before the LAST such tag is deliberation.
_ORPHAN_CLOSE = re.compile(r"</(?:think|thinking|reasoning|scratchpad)\s*>", re.IGNORECASE)
# A stray opener with no closer: the model started reasoning and was cut off at
# the token limit. There is no answer after it to keep.
_ORPHAN_OPEN = re.compile(
    r"<(?:think|thinking|reasoning|scratchpad)\b[^>]*>", re.IGNORECASE
)


def strip_thinking(text: str) -> str:
    """Return the answer with any reasoning block removed.

    Never returns empty. A response that is nothing but reasoning is handed back
    with only the tags removed: a blank answer would be rendered to a vendor as
    though the documents said nothing, which is a different and much worse claim
    than "the model rambled".
    """
    if not text:
        return text

    cleaned = _PAIRED.sub("", text)

    # Split on the LAST orphan closer, not the first. A model that reasons,
    # answers, then reconsiders emits several; the final answer follows the last.
    matches = list(_ORPHAN_CLOSE.finditer(cleaned))
    if matches:
        after = cleaned[matches[-1].end() :].strip()
        if after:
            return after
        # Nothing followed the tag -- the reasoning WAS the whole response. Keep
        # it rather than returning nothing, minus the tags.
        cleaned = _ORPHAN_CLOSE.sub("", cleaned)

    cleaned = _ORPHAN_OPEN.sub("", cleaned).strip()
    return cleaned or text.strip()
