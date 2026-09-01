"""Parsed-document representation (Phase 1).

Page boundaries are preserved all the way through parsing and chunking because
`source_page` is half of the citation anchor the whole system is built on
(Section 6 provenance, Section 4.5 "cite the source clause"). A parser that
returns one flat string throws that away and cannot be un-thrown later.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import DocumentKind


class ExtractionMethod(StrEnum):
    NATIVE = "native"       # embedded text layer
    OCR = "ocr"             # Tesseract on a rendered page image
    EMPTY = "empty"         # neither produced usable text


class PageText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1, description="1-indexed, matches what a human sees.")
    text: str = ""
    method: ExtractionMethod = ExtractionMethod.NATIVE
    # Tables are pulled out separately: tender eligibility grids are usually
    # tabular, and flattening them into prose destroys the row/column pairing
    # that makes "turnover | >= Rs 5 Cr" readable.
    tables: list[list[list[str | None]]] = Field(default_factory=list)

    @property
    def char_count(self) -> int:
        return len(self.text.strip())

    def tables_as_text(self) -> str:
        """Render tables as pipe-delimited rows so the LLM sees the pairing."""
        out: list[str] = []
        for table in self.tables:
            rows = [
                " | ".join((cell or "").strip().replace("\n", " ") for cell in row)
                for row in table
                if any(c and c.strip() for c in row)
            ]
            if rows:
                out.append("\n".join(rows))
        return "\n\n".join(out)

    def combined_text(self) -> str:
        parts = [self.text.strip()]
        tables = self.tables_as_text()
        if tables:
            parts.append(f"[TABLES ON PAGE {self.page_number}]\n{tables}")
        return "\n\n".join(p for p in parts if p)


class ParsedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str
    file_path: str | None = None
    doc_kind: DocumentKind
    pages: list[PageText] = Field(default_factory=list)
    parse_warnings: list[str] = Field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def total_chars(self) -> int:
        return sum(p.char_count for p in self.pages)

    @property
    def ocr_page_count(self) -> int:
        return sum(1 for p in self.pages if p.method is ExtractionMethod.OCR)

    @property
    def is_scanned(self) -> bool:
        """True when most pages needed OCR -- worth surfacing in the UI, since
        Section 13 flags OCR'd scans as the main extraction-accuracy risk."""
        return bool(self.pages) and self.ocr_page_count > len(self.pages) / 2

    def full_text(self, with_page_markers: bool = True) -> str:
        """Flatten for LLM input. Page markers stay in so the model can report
        the page a value came from instead of us guessing afterwards."""
        chunks = []
        for page in self.pages:
            body = page.combined_text()
            if not body:
                continue
            chunks.append(f"[PAGE {page.page_number}]\n{body}" if with_page_markers else body)
        return "\n\n".join(chunks)

    def page(self, number: int) -> PageText | None:
        return next((p for p in self.pages if p.page_number == number), None)

    @staticmethod
    def name_from_path(path: str | Path) -> str:
        return Path(path).name
