"""Phase 2 RAG: scoped retrieval + citation-grounded generation (Section 4.5)."""

from app.rag.answer import Citation, GroundedAnswer, answer_question
from app.rag.retrieve import RetrievedChunk, retrieve, retrieve_for_pair

__all__ = [
    "Citation",
    "GroundedAnswer",
    "RetrievedChunk",
    "answer_question",
    "retrieve",
    "retrieve_for_pair",
]
