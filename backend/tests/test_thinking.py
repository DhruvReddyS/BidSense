"""Stripping a reasoning model's chain of thought from its answer.

Measured, not assumed. Eight real questions against a real tender through
qwen3:4b: every response carried a `</think>` tag, raw bodies ran 1,438 to
10,149 characters, and the answer after the tag ran 7 to 470. The samples below
are the shapes those responses actually took.

The earlier approach guessed sentence by sentence whether an opener was
narration. It caught some and missed others, because "First, I notice the source
[1] states 'The EMD is Rs. 2,00,000.'" is narration that contains the answer and
no prefix rule separates those two facts. The model marks where its reasoning
ends; reading the marker is not a judgment call.
"""

from __future__ import annotations

import pytest

from app.llm.cleanup import strip_thinking
from app.rag.answer import strip_reasoning_preamble


# --------------------------------------------------------------------------- #
# The real shape: an orphan closing tag, because think:false suppresses the open
# --------------------------------------------------------------------------- #
def test_an_orphan_closing_tag_marks_the_end_of_the_reasoning() -> None:
    raw = (
        "Okay, I need to figure out what the EMD is. Starting with source [1] "
        "(page 37): it mentions Earnest Money Deposit but no amount...\n"
        "Yes, so the answer is Rs. 31,500 [5].\n</think>\n\nRs. 31,500 [5]"
    )
    assert strip_thinking(raw) == "Rs. 31,500 [5]"


def test_a_paired_block_is_removed_whole() -> None:
    raw = "<think>Let me consider the sources.</think>The EMD is Rs. 2,00,000 [1]."
    assert strip_thinking(raw) == "The EMD is Rs. 2,00,000 [1]."


@pytest.mark.parametrize("tag", ["think", "thinking", "reasoning", "scratchpad"])
def test_the_variants_different_builds_emit_are_all_handled(tag) -> None:
    assert strip_thinking(f"<{tag}>deliberating</{tag}>Answer [1].") == "Answer [1]."
    assert strip_thinking(f"deliberating</{tag}>Answer [1].") == "Answer [1]."


def test_the_last_tag_wins_when_a_model_reconsiders() -> None:
    """A model that reasons, answers, then reconsiders emits several closers.
    The final answer follows the last one."""
    raw = "first pass</think>draft answer</think>Rs. 31,500 [5]"
    assert strip_thinking(raw) == "Rs. 31,500 [5]"


# --------------------------------------------------------------------------- #
# It must never blank an answer
# --------------------------------------------------------------------------- #
def test_a_response_that_is_only_reasoning_is_kept_not_blanked() -> None:
    """An empty answer renders to a vendor as "the documents say nothing", which
    is a different and much worse claim than "the model rambled"."""
    raw = "I am still thinking about the sources and have not concluded.\n</think>"
    out = strip_thinking(raw)
    assert out
    assert "</think>" not in out
    assert "still thinking" in out


def test_a_truncated_opener_with_no_answer_is_kept() -> None:
    raw = "<think>I was cut off at the token limit"
    out = strip_thinking(raw)
    assert out and "cut off" in out and "<think>" not in out


def test_an_answer_with_no_tags_is_untouched() -> None:
    clean = "The EMD is Rs. 2,00,000 [1]."
    assert strip_thinking(clean) == clean


@pytest.mark.parametrize("value", ["", None])
def test_empty_input_is_returned_as_given(value) -> None:
    assert strip_thinking(value) == value


# --------------------------------------------------------------------------- #
# The case that surfaced this, end to end through the RAG stripper
# --------------------------------------------------------------------------- #
def test_the_sample_that_surfaced_this_is_now_clean() -> None:
    raw = (
        'Hmm, the user is asking for a one-sentence definition of "EMD" with a '
        "specific source provided. Let me analyze this carefully.\n\n"
        'First, I notice the source [1] states "The EMD is Rs. 2,00,000." '
        "That's the answer.\n</think>\n\nThe EMD is Rs. 2,00,000 [1]."
    )
    assert strip_reasoning_preamble(raw) == "The EMD is Rs. 2,00,000 [1]."


# Verbatim shapes from the eight measured samples.
MEASURED = [
    ("...deliberation about page 37...\n</think>\n\nRs. 31,500 [5]", "Rs. 31,500 [5]"),
    ("...\n</think>\n\n30% of the estimated cost [1][2][4]", "30% of the estimated cost [1][2][4]"),
    ("...\n</think>\n\n22 August 2026 (18:30 Hours) [4]", "22 August 2026 (18:30 Hours) [4]"),
    (
        "...\n</think>\n\nIndian Institute of Technology (Indian School of Mines) Dhanbad [4]",
        "Indian Institute of Technology (Indian School of Mines) Dhanbad [4]",
    ),
    ("...\n</think>\n\nOne [3]", "One [3]"),
]


@pytest.mark.parametrize("raw, expected", MEASURED)
def test_every_measured_sample_shape_strips_to_its_answer(raw, expected) -> None:
    assert strip_reasoning_preamble(raw) == expected


def test_the_sentence_heuristic_still_runs_for_untagged_narration() -> None:
    """Tag stripping is the primary mechanism, not the only one -- a model that
    narrates without marking it must still be cleaned up."""
    raw = "Okay, let me look at the sources. The EMD is Rs. 2,00,000 [1]."
    assert strip_reasoning_preamble(raw) == "The EMD is Rs. 2,00,000 [1]."


def test_stripping_never_eats_a_real_answer_that_opens_like_narration() -> None:
    """The guard the heuristic already had, still in force after tag stripping."""
    assert strip_reasoning_preamble("So it is Rs. 5 Cr [1].") == "So it is Rs. 5 Cr [1]."


def test_the_provider_strips_before_the_caller_ever_sees_it() -> None:
    """Structural: this is a property of the provider, and the RAG layer is not
    the only thing that reads generated text."""
    import inspect

    from app.llm import ollama

    source = inspect.getsource(ollama.OllamaProvider.generate_text)
    assert "strip_thinking" in source
