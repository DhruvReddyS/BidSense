"""PDF parsing with OCR fallback (Phase 1).

Strategy per page: try the embedded text layer first (fast, exact, keeps table
structure via pdfplumber). If a page yields almost no text it is a scan, so fall
back to rendering + Tesseract for that page only. Mixed documents are the norm --
a native-text tender with scanned certificates annexed is extremely common.
"""

from __future__ import annotations

import logging
import statistics

from app.ingest.models import ExtractionMethod, PageText, ParsedDocument
from app.ingest.ocr import missing_dependencies, ocr_available, ocr_pdf_page
from app.schemas.common import DocumentKind

logger = logging.getLogger(__name__)

# A native-text page essentially always clears this. Below it, the page is either
# blank or an image -- either way OCR is the only way to find out which.
MIN_NATIVE_CHARS = 100

# Ruled tables are found by following the drawn lines. Plenty of real tender
# tables have no ruling at all, so a text-alignment pass is tried as a fallback.
_LINE_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
_TEXT_SETTINGS = {"vertical_strategy": "text", "horizontal_strategy": "text"}

# The text strategy happily "finds" a table in ordinary prose, so its output is
# only accepted when it actually looks tabular. Measured on real vs phantom
# tables, two signals separate them cleanly:
#   column-count stdev   ~0.4 for a real grid, ~2.0 for prose
#   cell density         ~0.96 for a real grid, ~0.7 for prose
# Line-detected tables skip these checks: a drawn grid is evidence in itself.
MIN_TABLE_ROWS = 2
MIN_TABLE_COLS = 2
MAX_WIDTH_STDEV = 1.0
MIN_CELL_DENSITY = 0.8
MAX_MEAN_CELL_CHARS = 80


def _clean_rows(table: list[list[str | None]]) -> list[list[str | None]]:
    return [row for row in table if any(c and c.strip() for c in row)]


def _looks_tabular(table: list[list[str | None]]) -> bool:
    """Loose check for line-detected tables -- just discard empty results."""
    rows = _clean_rows(table)
    return len(rows) >= MIN_TABLE_ROWS and max(len(r) for r in rows) >= MIN_TABLE_COLS


def _looks_tabular_strict(table: list[list[str | None]]) -> bool:
    """Strict check for text-aligned candidates, which are guilty until proven
    otherwise. A false positive injects shredded prose into the LLM's context."""
    rows = _clean_rows(table)
    if len(rows) < MIN_TABLE_ROWS or max(len(r) for r in rows) < MIN_TABLE_COLS:
        return False

    filled = [len([c for c in row if c and c.strip()]) for row in rows]
    if statistics.pstdev(filled) > MAX_WIDTH_STDEV:
        return False

    total_cells = sum(len(row) for row in rows)
    if total_cells == 0 or sum(filled) / total_cells < MIN_CELL_DENSITY:
        return False

    cells = [c.strip() for row in rows for c in row if c and c.strip()]
    return bool(cells) and (sum(len(c) for c in cells) / len(cells)) < MAX_MEAN_CELL_CHARS


def _extract_tables(page) -> list[list[list[str | None]]]:
    ruled = [t for t in (page.extract_tables(_LINE_SETTINGS) or []) if _looks_tabular(t)]
    if ruled:
        return ruled
    return [
        t for t in (page.extract_tables(_TEXT_SETTINGS) or []) if _looks_tabular_strict(t)
    ]


def parse_pdf(
    path: str,
    doc_kind: DocumentKind = DocumentKind.NOTIFICATION,
    *,
    use_ocr: bool = True,
    extract_tables: bool = True,
) -> ParsedDocument:
    import pdfplumber

    pages: list[PageText] = []
    warnings: list[str] = []

    with pdfplumber.open(path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            tables: list[list[list[str | None]]] = []

            if extract_tables:
                try:
                    tables = _extract_tables(page)
                except Exception as exc:
                    warnings.append(f"page {index}: table extraction failed ({exc})")

            method = ExtractionMethod.NATIVE
            if len(text) < MIN_NATIVE_CHARS and not tables:
                # Short text is ambiguous: it is either a scanned page whose
                # text layer is a stray artefact, or a genuinely near-empty page
                # ("THIS PAGE IS LEFT INTENTIONALLY BLANK"). OCR settles it.
                if use_ocr and ocr_available():
                    try:
                        ocr_text = ocr_pdf_page(path, index)
                        # Only prefer OCR when it actually recovered more than
                        # the text layer held -- otherwise the page really is
                        # near-empty and the native text is the better record.
                        if len(ocr_text) > len(text):
                            text, method = ocr_text, ExtractionMethod.OCR
                    except Exception as exc:
                        warnings.append(f"page {index}: OCR failed ({exc})")

                if not text:
                    # Nothing at all. Loud, not silent: an empty page reads
                    # downstream as "this clause isn't in the tender", which is
                    # a wrong answer rather than a missing feature.
                    method = ExtractionMethod.EMPTY
                    if use_ocr and not ocr_available():
                        warnings.append(
                            f"page {index}: no extractable text and OCR unavailable "
                            f"({', '.join(missing_dependencies())}) -- page content "
                            "is MISSING from extraction"
                        )
                    else:
                        warnings.append(
                            f"page {index}: no extractable text found -- page "
                            "content is MISSING from extraction"
                        )

            pages.append(
                PageText(page_number=index, text=text, method=method, tables=tables)
            )

    document = ParsedDocument(
        file_name=ParsedDocument.name_from_path(path),
        file_path=str(path),
        doc_kind=doc_kind,
        pages=pages,
        parse_warnings=warnings,
    )
    logger.info(
        "Parsed %s: %d pages, %d chars, %d OCR'd, %d warnings",
        document.file_name,
        document.page_count,
        document.total_chars,
        document.ocr_page_count,
        len(warnings),
    )
    return document
