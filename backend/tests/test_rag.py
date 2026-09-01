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
