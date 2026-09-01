"""DOCX parsing (Phase 1).

DOCX has no fixed pagination -- page breaks are computed at render time by Word.
Rather than invent page numbers, we track *explicit* page breaks and otherwise
accumulate into a synthetic page. Citations from DOCX are therefore
"approximate page N", which is honest; claiming exact pages would be fabrication.
"""

from __future__ import annotations

import logging

from app.ingest.models import ExtractionMethod, PageText, ParsedDocument
from app.schemas.common import DocumentKind

logger = logging.getLogger(__name__)

# Roughly a page of dense text; used only to keep synthetic pages a sane size
# so a citation points at a findable region rather than "somewhere in the file".
CHARS_PER_SYNTHETIC_PAGE = 3000


def _paragraph_has_page_break(paragraph) -> bool:
    xml = paragraph._p.xml
    return 'w:br' in xml and 'type="page"' in xml


def parse_docx(
    path: str, doc_kind: DocumentKind = DocumentKind.NOTIFICATION
) -> ParsedDocument:
    import docx as python_docx

    document = python_docx.Document(path)
    warnings: list[str] = []
    pages: list[PageText] = []

    buffer: list[str] = []
    buffered_chars = 0
    page_number = 1
    explicit_breaks_seen = False

    def flush(tables=None) -> None:
        nonlocal buffer, buffered_chars, page_number
        body = "\n".join(buffer).strip()
        if body or tables:
            pages.append(
                PageText(
                    page_number=page_number,
                    text=body,
                    method=ExtractionMethod.NATIVE,
                    tables=tables or [],
                )
            )
            page_number += 1
        buffer, buffered_chars = [], 0

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if _paragraph_has_page_break(paragraph):
            explicit_breaks_seen = True
            flush()
        if text:
            buffer.append(text)
            buffered_chars += len(text)
            if not explicit_breaks_seen and buffered_chars >= CHARS_PER_SYNTHETIC_PAGE:
                flush()

    # Tables live outside the paragraph flow in the DOCX object model, so their
    # true position is not recoverable -- attach them to the final page and say so.
    tables = [
        [[cell.text for cell in row.cells] for row in table.rows]
        for table in document.tables
    ]
    flush(tables=tables)

    if not explicit_breaks_seen and len(pages) > 1:
        warnings.append(
            "DOCX has no explicit page breaks; page numbers are approximate "
            f"(~{CHARS_PER_SYNTHETIC_PAGE} chars per synthetic page)"
        )
    if tables:
        warnings.append(
            f"{len(tables)} table(s) appended to the last page -- DOCX does not "
            "preserve table position within the paragraph flow"
        )

    parsed = ParsedDocument(
        file_name=ParsedDocument.name_from_path(path),
        file_path=str(path),
        doc_kind=doc_kind,
        pages=pages,
        parse_warnings=warnings,
    )
    logger.info(
        "Parsed %s: %d synthetic pages, %d chars", parsed.file_name, parsed.page_count, parsed.total_chars
    )
    return parsed
