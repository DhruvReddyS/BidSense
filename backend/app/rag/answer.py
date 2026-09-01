"""Grounded answer generation with citations (Section 4.5).

The contract this module enforces:

  * Answers come only from retrieved chunks. Nothing is answered from the
    model's own knowledge of how Indian tenders usually work -- that is exactly
    how a confident, wrong, and unfalsifiable answer gets produced.
  * Every claim carries a citation to a real retrieved chunk.
  * "The documents don't say" is a valid and expected answer. Retrieval finding
    nothing is a legitimate outcome, not a prompt to improvise.

Citations are verified after generation: any the model invented are stripped and
reported, so Section 10's citation-faithfulness metric measures something real
rather than trusting the model's own bookkeeping.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, ConfigDict, Field

from app.llm import LLMError, LLMProvider, get_llm
from app.rag.retrieve import RetrievedChunk

logger = logging.getLogger(__name__)

NO_ANSWER = "The uploaded documents do not state this."

SYSTEM_PROMPT = """You answer questions about tender documents using ONLY the \
numbered sources provided.

Rules:
1. Use only the sources given. Never use general knowledge about how tenders
   usually work. If the sources do not contain the answer, say exactly:
   "The uploaded documents do not state this." and nothing more.
2. Cite every factual claim with the source number in square brackets, e.g.
   "The EMD is Rs. 2,00,000 [1]." Multiple sources: [1][3].
3. Never cite a source number that was not provided to you.
4. Quote figures, dates and names exactly as they appear in the sources. Do not
   convert or round them.
5. Be brief and direct. A vendor is reading this to make a decision, not to
   admire the prose.
6. If the sources conflict, say so and cite both.
7. Output the answer only. No preamble, no restatement of the question, no
   narration of your reasoning ("Okay, let me check the sources...", "First,
   looking at source [1]..."). Start with the answer itself. A vendor is
   reading this under time pressure before a submission deadline."""

ANSWER_PROMPT = """Question: {question}

Sources:
{sources}

Answer using only these sources, citing each claim with [n]. Give the answer
directly -- do not narrate your reasoning or restate the question."""

_CITATION = re.compile(r"\[(\d+)\]")

# Some models narrate before answering despite instruction. Reasoning-style
# openers are stripped so a vendor sees the answer, not the model's monologue.
_REASONING_OPENER = re.compile(
    r"^\s*(?:okay|ok|alright|so|well|hmm|let me|let's|lets|first|firstly|next|"
    r"now|i need to|i'll|i will|looking at|checking|the user|to answer)\b",
    re.IGNORECASE,
)

# Abbreviations whose full stop does not end a sentence. "Rs." is the one that
# matters here: splitting on it turns "Rs. 5 Cr" into a new sentence and the
# amount gets stripped away with the narration.
_ABBREVIATIONS = {"rs", "no", "nos", "sl", "mr", "mrs", "dr", "ltd", "pvt", "viz", "etc", "vs", "sec"}
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_DIGIT = re.compile(r"\d")


def _sentences(text: str) -> list[str]:
    """Split into sentences without breaking on Indian-tender abbreviations."""
    parts = _SENTENCE_SPLIT.split(text)
    merged: list[str] = []
    for part in parts:
        if merged:
            tail = merged[-1].rstrip(".").rsplit(" ", 1)[-1].lower()
            if tail in _ABBREVIATIONS:
                merged[-1] = f"{merged[-1]} {part}"
                continue
        merged.append(part)
    return merged


def strip_reasoning_preamble(text: str) -> str:
    """Drop leading narration sentences.

    A sentence is only dropped when it opens like narration AND carries no
    substantive content -- no digits once citation markers are removed. That
    keeps "So it is Rs. 5 Cr [1]." intact while removing "First, looking at
    source [1]."; stripping by shape alone deletes real answers.

    Never returns empty: an answer that is entirely narration is handed back
    unchanged rather than blanked.
    """
    sentences = _sentences(text.strip())
    index = 0
    while index < len(sentences):
        candidate = sentences[index]
        without_citations = _CITATION.sub("", candidate)
        if _REASONING_OPENER.match(candidate) and not _DIGIT.search(without_citations):
            index += 1
            continue
        break

    remainder = " ".join(sentences[index:]).strip()
    return remainder if remainder else text.strip()


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    text: str
    source_file: str | None = None
    source_page: int | None = None
    clause_ref: str | None = None
    doc_kind: str
    score: float
    label: str


class GroundedAnswer(BaseModel):
    """An answer plus the evidence it is allowed to rest on."""

    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    retrieved: list[Citation] = Field(
        default_factory=list, description="Everything retrieved, cited or not."
    )
    invented_citations: list[int] = Field(
        default_factory=list,
        description="Source numbers the model cited that were never provided.",
    )
    answered: bool = True

    @property
    def is_grounded(self) -> bool:
        """A factual answer with no citation is ungrounded even if it is correct
        -- the vendor has no way to check it."""
        if not self.answered:
            return True
        return bool(self.citations) and not self.invented_citations


def _format_sources(chunks: list[RetrievedChunk]) -> str:
    return "\n\n".join(
        f"[{i}] ({chunk.citation})\n{chunk.text}"
        for i, chunk in enumerate(chunks, start=1)
    )


def _to_citation(index: int, chunk: RetrievedChunk) -> Citation:
    return Citation(
        index=index,
        text=chunk.text,
        source_file=chunk.source_file,
        source_page=chunk.source_page,
        clause_ref=chunk.clause_ref,
        doc_kind=chunk.doc_kind,
        score=round(chunk.score, 4),
        label=chunk.citation,
    )


def answer_question(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    llm: LLMProvider | None = None,
) -> GroundedAnswer:
    """Generate an answer grounded in `chunks`, then verify its citations."""
    retrieved = [_to_citation(i, c) for i, c in enumerate(chunks, start=1)]

    if not chunks:
        # No retrieval, no generation. Calling the model here invites it to
        # answer from memory, which is the failure this whole module prevents.
        return GroundedAnswer(
            question=question, answer=NO_ANSWER, answered=False, retrieved=[]
        )

    llm = llm or get_llm()
    try:
        raw = llm.generate_text(
            ANSWER_PROMPT.format(question=question, sources=_format_sources(chunks)),
            system=SYSTEM_PROMPT,
        )
    except LLMError as exc:
        logger.warning("answer generation failed: %s", exc)
        return GroundedAnswer(
            question=question,
            answer="The answer could not be generated. Please try again.",
            answered=False,
            retrieved=retrieved,
        )

    return _verify_citations(question, strip_reasoning_preamble(raw), retrieved)


def _verify_citations(question: str, answer: str, retrieved: list[Citation]) -> GroundedAnswer:
    """Strip citations pointing at sources that were never provided.

    A hallucinated [7] against six sources looks exactly as authoritative as a
    real one in the UI. Removing it is not cosmetic -- an uncheckable citation
    is worse than none, because it invites belief.
    """
    valid_indexes = {c.index for c in retrieved}
    cited = {int(m) for m in _CITATION.findall(answer)}

    invented = sorted(cited - valid_indexes)
    if invented:
        logger.warning("model cited non-existent sources %s", invented)
        for index in invented:
            answer = answer.replace(f"[{index}]", "")
        answer = re.sub(r"\s{2,}", " ", answer).strip()

    used = sorted(cited & valid_indexes)
    answered = NO_ANSWER.lower() not in answer.lower()

    return GroundedAnswer(
        question=question,
        answer=answer,
        citations=[c for c in retrieved if c.index in used],
        retrieved=retrieved,
        invented_citations=invented,
        answered=answered,
    )
