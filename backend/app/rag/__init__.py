"""Phase 2 RAG: scoped retrieval + citation-grounded generation (Section 4.5).

Submodules are resolved on attribute access rather than imported here. The
package's public API pulls in Qdrant, the BGE model and the LLM providers, but
`app.rag.stats` is pure arithmetic with no dependencies at all -- and eight
callers import only that. Eagerly importing the rest cost every one of them a
torch load, and made `scripts/baseline_retrieval.py` false in its own docstring:
it promises "no Qdrant, no embedding model, no LLM" while importing a helper
that loaded all three.

PEP 562 keeps `from app.rag import answer_question` working for the API layer
while letting a stats-only caller stay cheap.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # import-time only for type checkers, never at runtime
    from app.rag.answer import Citation, GroundedAnswer, answer_question
    from app.rag.retrieve import RetrievedChunk, retrieve, retrieve_for_pair

#: public name -> the submodule that defines it
_EXPORTS = {
    "Citation": "app.rag.answer",
    "GroundedAnswer": "app.rag.answer",
    "answer_question": "app.rag.answer",
    "RetrievedChunk": "app.rag.retrieve",
    "retrieve": "app.rag.retrieve",
    "retrieve_for_pair": "app.rag.retrieve",
}

__all__ = [
    "Citation",
    "GroundedAnswer",
    "RetrievedChunk",
    "answer_question",
    "retrieve",
    "retrieve_for_pair",
]


def __getattr__(name: str):
    """Import the owning submodule the first time a public name is used."""
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_path), name)
    globals()[name] = value          # cache, so later access is a plain lookup
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
