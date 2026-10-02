"""Chunking for the vector store (Section 7).

Three rules drive the design:

1. A chunk never spans a page boundary. Section 4.5 requires every answer to
   cite a page; a chunk covering pages 7-8 cannot honestly cite either.
2. Splits prefer paragraph, then sentence, then whitespace boundaries. Cutting
   mid-sentence in a legal clause ("...turnover of not less than Rs. 5" | "Cr")
   produces retrievable text that means the wrong thing.
3. TABLES ARE CHUNKED BY ROW, prose by size. This rule was earned by
   measurement, and it is the single largest retrieval win in the system.

   Why rule 3 exists. Tables were originally appended to the page's prose and
   split by size like everything else, which put an entire date grid into one
   1,208-character chunk:

       [TABLES ON PAGE 5] date of issue/publishing | 17 august 2026 ...
       document download end date | 22 august 2026 ... last date for
       submission of emd | 24 august 2026 ... last date and time for
       uploading of bids | 22 august 2026 ... receipt of queries | 19
       august 2026 ...

   One vector had to stand for seven differently-labelled dates, so it was
   diffuse -- about dates in general, specific to none of them. Asked "By when
   must I upload my bid?", retrieval ranked that chunk 11th of 212 (0.589)
   behind prose that merely DISCUSSED uploading and contained no date at all
   (0.665). Measured over a 17-question labelled set, hit@5 was 29.4% and
   precision@1 was 5.9%, with the misses clustered exactly on the fields that
   live in tables: EMD, deadlines, conditions.

   A row is already the unit of meaning in a tender grid -- "label | value" is
   a complete fact -- so one row per chunk gives each fact its own vector.
   `scripts/evaluate_retrieval.py` measures the difference.
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
#: A table row is a fact, not a size budget, so rows are not merged to fill
#: this. It only bounds a pathologically long row before splitting it.
TABLE_ROW_MAX = 600

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



def _looks_like_header(row: list[str]) -> bool:
    """True when a table's first row labels its columns rather than stating a fact.

    Deliberately conservative. In the date grid that motivated row chunking the
    FIRST row is itself a fact ("date of issue/publishing | 17 august 2026"),
    so treating row zero as a header unconditionally would silently delete a
    value from the index -- the worst possible failure for a system whose whole
    claim is that it does not lose things.

    The test is therefore: a header has at least two labelled cells, carries no
    digits (a column called "Threshold" rarely does, a row stating 17 August
    2026 always does), and sits above enough rows to be worth repeating.
    """
    cells = [c for c in row if c and c.strip()]
    if len(cells) < 2:
        return False
    return not any(any(ch.isdigit() for ch in cell) for cell in cells)


def _render_row(row: list[str | None]) -> str:
    return " | ".join((cell or "").strip().replace("\n", " ") for cell in row).strip(" |")


def _table_chunks(
    page, section: ChunkSection, start_index: int, chunk_size: int, overlap: int
) -> list["Chunk"]:
    """One chunk per table row, so each labelled fact gets its own vector."""
    chunks: list[Chunk] = []
    index = start_index

    for table in page.tables:
        rows = [r for r in table if any(c and c.strip() for c in r)]
        if not rows:
            continue

        header = None
        body = rows
        if len(rows) >= 3 and _looks_like_header(rows[0]):
            header = _render_row(rows[0])
            body = rows[1:]

        for row in body:
            rendered = _render_row(row)
            if not rendered:
                continue
            # The page marker keeps the chunk self-describing once it is
            # retrieved out of context; the header, when there is one, restores
            # the column meaning a bare row would lose.
            prefix = f"[table on page {page.page_number}]"
            text = f"{prefix} {header}\n{rendered}" if header else f"{prefix} {rendered}"

            for piece in (
                [text] if len(text) <= TABLE_ROW_MAX
                else _split_to_size(text, chunk_size, overlap)
            ):
                chunks.append(
                    Chunk(
                        text=piece,
                        page_number=page.page_number,
                        chunk_index=index,
                        section=section,
                        clause_ref=_detect_clause_ref(rendered),
                    )
                )
                index += 1
    return chunks


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
        # Prose and tables are chunked by different rules -- see rule 3 in the
        # module docstring. combined_text() is deliberately NOT used here: it
        # concatenates the two, which is what produced the diffuse table blobs.
        prose = (page.text or "").strip()
        if prose:
            for piece in _split_to_size(prose, chunk_size, overlap):
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

        table_chunks = _table_chunks(page, section, index, chunk_size, overlap)
        chunks.extend(table_chunks)
        index += len(table_chunks)
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
