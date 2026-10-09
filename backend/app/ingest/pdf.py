"""PDF parsing with OCR fallback (Phase 1).

Strategy per page: try the embedded text layer first (fast, exact, keeps table
structure via pdfplumber). If a page yields almost no text it is a scan, so fall
back to rendering + Tesseract for that page only. Mixed documents are the norm --
a native-text tender with scanned certificates annexed is extremely common.
"""

from __future__ import annotations

import logging
import multiprocessing
import statistics
from concurrent.futures import (
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
)

from app.config import settings
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



def _parse_page_span(
    job: tuple[str, int, int, bool],
) -> list[tuple[int, str, list[list[list[str | None]]], str | None]]:
    """Native text and tables for pages [lo, hi), as picklable plain data.

    Module level and self-contained so a process pool can call it: it opens
    its own pdfplumber handle rather than sharing page objects, which are not
    picklable. Returns one tuple per page -- (1-based index, text, tables,
    table-extraction warning) -- leaving every decision about OCR candidacy
    and extraction method to the caller, so the serial and parallel paths
    cannot drift apart.
    """
    import pdfplumber

    path, lo, hi, want_tables = job
    results = []
    with pdfplumber.open(path) as pdf:
        for offset, page in enumerate(pdf.pages[lo:hi]):
            index = lo + offset + 1
            text = (page.extract_text() or "").strip()
            tables: list[list[list[str | None]]] = []
            warning: str | None = None
            if want_tables:
                try:
                    tables = _extract_tables(page)
                except Exception as exc:
                    warning = f"page {index}: table extraction failed ({exc})"
            results.append((index, text, tables, warning))
            # Release this page's cached objects: on a 380-page tender the
            # accumulated cache is the difference between a bounded and an
            # unbounded resident set.
            page.close()
    return results


def _parse_pages(
    path: str, page_count: int, want_tables: bool
) -> list[tuple[int, str, list[list[list[str | None]]], str | None]]:
    """Every page's native extraction, in page order, serial or parallel.

    Parsing is where ingestion time goes. Measured on a 172-page generated
    bid, text extraction and table detection are 99.9% of the pipeline
    (14.9s, against 11ms for chunking), and inside that the text-based table
    fallback is 56% at ~58ms per page it runs on. It is CPU-bound Python, so
    threads cannot help -- but it parallelises across page ranges perfectly,
    measured at 2.75x on four workers with byte-identical output.

    Two deliberate guards. The pool uses the "spawn" context, because the
    ingest queue can run jobs on threads and forking a threaded process is a
    documented way to deadlock. And it engages only above
    `pdf_parse_parallel_min_pages`, since spawning interpreters costs more
    than it saves on a short document.
    """
    serial = [(path, 0, page_count, want_tables)]
    workers = max(1, settings.pdf_parse_workers)
    if workers == 1 or page_count < settings.pdf_parse_parallel_min_pages:
        return _parse_page_span(serial[0])

    workers = min(workers, page_count)
    step = (page_count + workers - 1) // workers
    spans = [
        (path, lo, min(lo + step, page_count), want_tables)
        for lo in range(0, page_count, step)
    ]
    try:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=len(spans), mp_context=context) as pool:
            return [row for part in pool.map(_parse_page_span, spans) for row in part]
    except Exception:
        # A sandbox may forbid process creation. Parsing serially is slower,
        # not wrong, so this must never be the reason an ingest fails.
        logger.warning(
            "Parallel page parsing unavailable; falling back to serial.",
            exc_info=True,
        )
        return _parse_page_span(serial[0])


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
    ocr_candidates: list[int] = []

    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)

    for index, text, tables, table_warning in _parse_pages(
        path, page_count, extract_tables
    ):
        if table_warning:
            warnings.append(table_warning)

        method = ExtractionMethod.NATIVE
        if len(text) < MIN_NATIVE_CHARS and not tables:
            # OCR is run after native parsing so candidate pages can be
            # processed concurrently without sharing pdfplumber objects.
            if use_ocr and ocr_available():
                ocr_candidates.append(index)
            elif not text:
                method = ExtractionMethod.EMPTY
                warnings.append(
                    f"page {index}: no extractable text and OCR unavailable "
                    f"({', '.join(missing_dependencies())}) -- page content "
                    "is MISSING from extraction"
                )

        pages.append(
            PageText(page_number=index, text=text, method=method, tables=tables)
        )

    if ocr_candidates:
        outcomes: dict[int, tuple[str | None, Exception | None]] = {}
        with ThreadPoolExecutor(
            max_workers=min(settings.ocr_workers, len(ocr_candidates)),
            thread_name_prefix="ocr",
        ) as pool:
            futures = {pool.submit(ocr_pdf_page, path, number): number for number in ocr_candidates}
            for future in as_completed(futures):
                number = futures[future]
                try:
                    outcomes[number] = (future.result(), None)
                except Exception as exc:
                    outcomes[number] = (None, exc)

        for number in ocr_candidates:
            page = pages[number - 1]
            ocr_text, error = outcomes[number]
            if error is not None:
                warnings.append(f"page {number}: OCR failed ({error})")
            elif ocr_text is not None and len(ocr_text) > len(page.text):
                page.text = ocr_text
                page.method = ExtractionMethod.OCR
            if not page.text:
                page.method = ExtractionMethod.EMPTY
                warnings.append(
                    f"page {number}: no extractable text found -- page content is MISSING from extraction"
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
