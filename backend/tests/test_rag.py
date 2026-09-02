"""RAG grounding and citation-verification tests (Section 4.5).

Generation runs against a stub so the grounding contract is tested
deterministically. Retrieval quality itself is Section 10's measurement.
"""

from __future__ import annotations

import pytest

from app.llm.base import LLMError, LLMProvider
from app.rag.answer import NO_ANSWER, answer_question
from app.rag.retrieve import RetrievedChunk


def chunk(text: str, *, page=2, clause="4.2", file="NOTIF_01.pdf", score=0.8, kind="notification"):
    return RetrievedChunk(
        text=text, score=score, doc_kind=kind, source_file=file,
        source_page=page, clause_ref=clause, vendor_id=None,
        tender_id="T-1", section="eligibility",
    )


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, reply: str | None = None, fail: bool = False):
        self.reply = reply
        self.fail = fail
        self.prompts: list[str] = []

    def generate_text(self, prompt, *, system=None):
        self.prompts.append(prompt)
        if self.fail:
            raise LLMError("scripted failure")
        return self.reply

    def generate_structured(self, prompt, schema, *, system=None):
        raise NotImplementedError


SOURCES = [
    chunk("The Earnest Money Deposit shall be Rs. 2,00,000.", page=1, clause="3.1"),
    chunk("The bidder shall have an average annual turnover of not less than Rs. 5 Cr."),
]


# --------------------------------------------------------------------------- #
# Citation formatting
# --------------------------------------------------------------------------- #
def test_citation_label_includes_file_page_and_clause():
    assert SOURCES[1].citation == "NOTIF_01.pdf, page 2, clause 4.2"


def test_citation_label_degrades_when_anchors_are_missing():
    bare = RetrievedChunk(
        text="x", score=0.5, doc_kind="submission", source_file=None,
        source_page=None, clause_ref=None, vendor_id="V-1", tender_id="T-1", section=None,
    )
    assert bare.citation == "submission"


# --------------------------------------------------------------------------- #
# Grounding
# --------------------------------------------------------------------------- #
def test_answer_records_only_the_sources_actually_cited():
    llm = ScriptedLLM("The EMD is Rs. 2,00,000 [1].")
    result = answer_question("What is the EMD?", SOURCES, llm=llm)

    assert result.answered
    assert [c.index for c in result.citations] == [1]
    assert len(result.retrieved) == 2       # both were offered
    assert result.citations[0].source_page == 1
    assert result.citations[0].clause_ref == "3.1"
    assert result.is_grounded


def test_empty_retrieval_never_reaches_the_model():
    """Calling the model with no sources invites it to answer from memory --
    the exact failure this module exists to prevent."""
    llm = ScriptedLLM("I would have made something up.")
    result = answer_question("What is the EMD?", [], llm=llm)

    assert llm.prompts == []                # the model was never called
    assert result.answer == NO_ANSWER
    assert result.answered is False
    assert result.citations == []
    assert result.is_grounded               # honestly declining is grounded


def test_model_saying_it_does_not_know_is_marked_unanswered():
    llm = ScriptedLLM(NO_ANSWER)
    result = answer_question("What is the penalty clause?", SOURCES, llm=llm)
    assert result.answered is False
    assert result.is_grounded


def test_uncited_factual_answer_is_flagged_as_ungrounded():
    """A correct answer the vendor cannot check is still a failure."""
    llm = ScriptedLLM("The EMD is Rs. 2,00,000.")
    result = answer_question("What is the EMD?", SOURCES, llm=llm)
    assert result.answered
    assert result.citations == []
    assert result.is_grounded is False


def test_multiple_citations_are_all_resolved():
    llm = ScriptedLLM("EMD is Rs. 2,00,000 [1] and turnover must be Rs. 5 Cr [2].")
    result = answer_question("Summarise the requirements", SOURCES, llm=llm)
    assert [c.index for c in result.citations] == [1, 2]


# --------------------------------------------------------------------------- #
# Invented citations
# --------------------------------------------------------------------------- #
def test_invented_citation_is_stripped_and_reported():
    """A hallucinated [7] against two sources looks exactly as authoritative as
    a real one in the UI. An uncheckable citation invites belief."""
    llm = ScriptedLLM("EMD is Rs. 2,00,000 [1]. Bid validity is 180 days [7].")
    result = answer_question("Tell me about the bid", SOURCES, llm=llm)

    assert result.invented_citations == [7]
    assert "[7]" not in result.answer
    assert "[1]" in result.answer
    assert [c.index for c in result.citations] == [1]
    assert result.is_grounded is False      # the answer is not trustworthy


def test_only_invented_citations_leaves_nothing_grounded():
    llm = ScriptedLLM("The penalty is 2% per week [4][5].")
    result = answer_question("What is the penalty?", SOURCES, llm=llm)
    assert result.invented_citations == [4, 5]
    assert result.citations == []
    assert result.is_grounded is False


def test_generation_failure_is_reported_not_faked():
    llm = ScriptedLLM(fail=True)
    result = answer_question("What is the EMD?", SOURCES, llm=llm)
    assert result.answered is False
    assert "could not be generated" in result.answer
    assert len(result.retrieved) == 2       # retrieval is still shown to the user


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #
def test_sources_are_numbered_and_labelled_in_the_prompt():
    llm = ScriptedLLM("ok [1]")
    answer_question("What is the EMD?", SOURCES, llm=llm)
    prompt = llm.prompts[0]
    assert "[1] (NOTIF_01.pdf, page 1, clause 3.1)" in prompt
    assert "[2] (NOTIF_01.pdf, page 2, clause 4.2)" in prompt
    assert "Rs. 2,00,000" in prompt


# --------------------------------------------------------------------------- #
# Leaked reasoning
# --------------------------------------------------------------------------- #
def test_reasoning_preamble_is_stripped():
    """Reasoning-capable models narrate before answering even when told not to.
    A vendor reading this before a deadline should see the answer, not the
    model's monologue."""
    llm = ScriptedLLM(
        "Okay, let me tackle this step by step. First, looking at source [1]. "
        "The EMD is Rs. 2,00,000 [1]."
    )
    result = answer_question("What is the EMD?", SOURCES, llm=llm)
    assert result.answer.startswith("The EMD is Rs. 2,00,000")
    assert "let me tackle" not in result.answer
    assert [c.index for c in result.citations] == [1]


def test_stripping_never_eats_a_short_answer():
    """The strip is bounded -- a runaway would delete the answer itself."""
    from app.rag.answer import strip_reasoning_preamble

    assert strip_reasoning_preamble("Rs. 2,00,000 [1].") == "Rs. 2,00,000 [1]."
    # "Rs." must not be read as a sentence end, or the amount is stripped away
    # with the narration.
    assert strip_reasoning_preamble("So it is Rs. 5 Cr [1].") == "So it is Rs. 5 Cr [1]."
    # Even an answer that is nothing but narration must not vanish.
    assert strip_reasoning_preamble("Okay. Let me think. So.").strip() != ""


def test_a_normal_answer_is_left_alone():
    llm = ScriptedLLM("The EMD is Rs. 2,00,000 [1] and bids close on 15 March 2026 [1].")
    result = answer_question("What is the EMD?", SOURCES, llm=llm)
    assert result.answer.startswith("The EMD is Rs. 2,00,000")


# --------------------------------------------------------------------------- #
# Three-state retrieval confidence (Stage 4.11)
# --------------------------------------------------------------------------- #
def _chunk(score: float, text: str = "The EMD is Rs. 2,00,000."):
    from app.rag.retrieve import RetrievedChunk

    return RetrievedChunk(
        text=text, score=score, doc_kind="notification", source_file="n.pdf",
        source_page=2, clause_ref="3.1", vendor_id=None, tender_id="T-1",
        section="eligibility",
    )


def test_confidence_is_taken_from_the_best_chunk_not_the_average():
    """One strongly matching clause is enough to answer a question about that
    clause. Averaging it against five pieces of surrounding boilerplate punishes
    exactly the queries retrieval got right -- a precise question has the fewest
    good matches, not the most."""
    from app.rag.answer import Confidence, classify_confidence

    chunks = [_chunk(0.78)] + [_chunk(0.30) for _ in range(5)]
    assert classify_confidence(chunks) is Confidence.HIGH


@pytest.mark.parametrize(
    "best, expected",
    [
        (0.78, "high"),   # measured: answerable questions land 0.65-0.77
        (0.65, "high"),
        (0.58, "low"),    # measured: vague questions land 0.48-0.58
        (0.47, "low"),
        (0.40, "none"),   # measured: off-topic lands 0.40-0.55
    ],
)
def test_the_three_states_match_the_measured_score_bands(best, expected):
    from app.rag.answer import classify_confidence

    assert classify_confidence([_chunk(best)]).value == expected


def test_a_question_nothing_matches_never_reaches_the_model():
    """Sending loosely related chunks anyway invites the model to stitch an
    answer out of whatever it was handed -- and every citation in that answer
    would be REAL, which is exactly what makes it hard to catch."""
    from app.rag.answer import NOT_COVERED, answer_question

    llm = CountingLLM(["The EMD is Rs. 2,00,000 [1]."])
    answer = answer_question("Who won the 2019 cricket world cup?", [_chunk(0.40)], llm=llm)

    assert llm.calls == 0, "a model call was spent on a question nothing matched"
    assert answer.answer == NOT_COVERED
    assert answer.answered is False
    assert answer.confidence.value == "none"


def test_a_declined_question_still_shows_what_was_found():
    """The passages are returned so the vendor can judge for themselves rather
    than being told only that we gave up."""
    from app.rag.answer import answer_question

    answer = answer_question("unrelated", [_chunk(0.40)], llm=CountingLLM([""]))
    assert len(answer.retrieved) == 1
    assert answer.retrieved[0].label


def test_a_weak_match_is_answered_but_says_so():
    from app.rag.answer import answer_question

    llm = CountingLLM(["The penalty is 0.5% per week [1]."])
    answer = answer_question("Tell me about penalties", [_chunk(0.52)], llm=llm)

    assert llm.calls == 1
    assert answer.answered
    assert answer.confidence.value == "low"
    assert answer.caveat and "weaker evidence" in answer.caveat


def test_a_strong_match_carries_no_caveat():
    """The caveat must mean something. Attaching it to every answer would make
    it invisible."""
    from app.rag.answer import answer_question

    answer = answer_question(
        "What is the EMD?", [_chunk(0.74)],
        llm=CountingLLM(["The EMD is Rs. 2,00,000 [1]."]),
    )
    assert answer.confidence.value == "high"
    assert answer.caveat is None


def test_a_weak_match_where_the_model_declines_carries_no_caveat():
    """"The documents do not state this" is already the honest answer. Telling a
    vendor the evidence was thin for a non-answer is noise."""
    from app.rag.answer import NO_ANSWER, answer_question

    answer = answer_question(
        "something", [_chunk(0.50)], llm=CountingLLM([NO_ANSWER])
    )
    assert answer.confidence.value == "low"
    assert answer.answered is False
    assert answer.caveat is None


class CountingLLM:
    """Returns canned text and counts how often it was actually called.

    Separate from `ScriptedLLM` above because these tests assert that the model
    is NOT called, which needs a counter rather than a recorded prompt list.
    """

    name = "scripted"
    max_concurrency = 1

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def generate_text(self, prompt, *, system=None):
        self.calls += 1
        return self._replies[min(self.calls - 1, len(self._replies) - 1)]

    def generate_structured(self, prompt, schema, *, system=None):
        raise NotImplementedError
