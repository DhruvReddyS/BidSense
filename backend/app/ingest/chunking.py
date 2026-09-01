"""Chunking for the vector store (Section 7).

Two rules drive the design:

1. A chunk never spans a page boundary. Section 4.5 requires every answer to
   cite a page; a chunk covering pages 7-8 cannot honestly cite either.
2. Splits prefer paragraph, then sentence, then whitespace boundaries. Cutting
   mid-sentence in a legal clause ("...turnover of not less than Rs. 5" | "Cr")
   produces retrievable text that means the wrong thing.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from app.ingest.models import ParsedDocument
from app.schemas.common import ChunkSection

# ~1600 chars sits comfortably inside bge-base's 512-token window (roughly
# 4 chars/token for English legal prose) with headroom for the query prefix.
DEFAULT_CHUNK_SIZE = 1600
DEFAULT_OVERLAP = 200

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+")
_CLAUSE_HEADING = re.compile(
    r"^\s*((?:\d+\.)+\d*|[A-Z]\.|\(?[ivxlIVXL]+\))\s+", re.MULTILINE
)


class Chunk(BaseModel):
    """A unit of retrievable text with its citation anchor attached."""

    model_config = ConfigDict(extra="forbid")

    text: str
    page_number: int
    chunk_index: int
    section: ChunkSection = ChunkSection.GENERAL
    clause_ref: str | None = Field(
        default=None, description="Leading clause number, if the chunk starts at one."
    )


def _detect_clause_ref(text: str) -> str | None:
    match = _CLAUSE_HEADING.match(text)
    return match.group(1).rstrip(".") if match else None


def _split_to_size(text: str, size: int, overlap: int) -> list[str]:
    """Split on the largest natural boundary that fits, descending."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []

    pieces: list[str] = []
    for candidate in _PARAGRAPH_BREAK.split(text):
        candidate = candidate.strip()
        if not candidate:
            continue
        if len(candidate) <= size:
            pieces.append(candidate)
            continue
        # Paragraph still too long -- fall to sentences.
        buffer = ""
        for sentence in _SENTENCE_END.split(candidate):
            if len(buffer) + len(sentence) + 1 <= size:
                buffer = f"{buffer} {sentence}".strip()
            else:
                if buffer:
                    pieces.append(buffer)
                # A single sentence longer than the window (common in tender
                # prose) is hard-split rather than dropped.
                while len(sentence) > size:
                    pieces.append(sentence[:size])
                    sentence = sentence[size - overlap :]
                buffer = sentence
        if buffer:
            pieces.append(buffer)

    # Recombine adjacent small pieces so we don't emit a chunk per bullet point.
    merged: list[str] = []
    for piece in pieces:
        if merged and len(merged[-1]) + len(piece) + 2 <= size:
            merged[-1] = f"{merged[-1]}\n\n{piece}"
        else:
            merged.append(piece)
    return merged


def chunk_document(
    document: ParsedDocument,
    *,
    section: ChunkSection = ChunkSection.GENERAL,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Chunk a parsed document, one page at a time so page numbers stay exact."""
    chunks: list[Chunk] = []
    index = 0
    for page in document.pages:
        body = page.combined_text()
        if not body.strip():
            continue
        for piece in _split_to_size(body, chunk_size, overlap):
            chunks.append(
                Chunk(
                    text=piece,
                    page_number=page.page_number,
                    chunk_index=index,
                    section=section,
                    clause_ref=_detect_clause_ref(piece),
                )
            )
            index += 1
    return chunks


def chunk_text(
    text: str,
    *,
    page_number: int = 1,
    section: ChunkSection = ChunkSection.GENERAL,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    start_index: int = 0,
) -> list[Chunk]:
    """Chunk a free-text field (e.g. technical_approach_text) that came from the
    extraction schema rather than straight off a page."""
    return [
        Chunk(
            text=piece,
            page_number=page_number,
            chunk_index=start_index + offset,
            section=section,
            clause_ref=_detect_clause_ref(piece),
        )
        for offset, piece in enumerate(_split_to_size(text, chunk_size, overlap))
    ]
