"""Ingestion pipeline tests, run against real generated PDF/DOCX binaries."""

from __future__ import annotations

import pytest

from app.ingest import (
    ExtractionMethod,
    UnsupportedDocumentError,
    chunk_document,
    chunk_text,
    ocr_available,
    parse_document,
)
from app.ingest.chunking import DEFAULT_CHUNK_SIZE
from app.schemas.common import ChunkSection, DocumentKind
from tests.doc_factory import (
    NOTIFICATION_TRUTH,
    make_blank_pdf,
    make_notification_docx,
    make_notification_pdf,
)


@pytest.fixture(scope="module")
def notification_pdf(tmp_path_factory):
    return make_notification_pdf(tmp_path_factory.mktemp("docs") / "NOTIF_ITservices_01.pdf")


@pytest.fixture(scope="module")
def notification_docx(tmp_path_factory):
    return make_notification_docx(tmp_path_factory.mktemp("docs") / "NOTIF_ITservices_01.docx")


@pytest.fixture(scope="module")
def parsed_pdf(notification_pdf):
    return parse_document(notification_pdf, DocumentKind.NOTIFICATION)


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
def test_pdf_page_count_and_native_extraction(parsed_pdf):
    assert parsed_pdf.page_count == 3
    assert all(p.method is ExtractionMethod.NATIVE for p in parsed_pdf.pages)
    assert parsed_pdf.is_scanned is False
    assert parsed_pdf.parse_warnings == []


def test_pdf_clauses_land_on_the_right_page(parsed_pdf):
    """Page attribution is the citation anchor -- if this drifts, every cited
    answer in 4.5 points at the wrong page."""
    page1 = parsed_pdf.page(1).text
    page2 = parsed_pdf.page(2).text
    page3 = parsed_pdf.page(3).text

    assert NOTIFICATION_TRUTH["tender_id"] in page1
    assert "Earnest Money Deposit" in page1
    # The turnover threshold (clause 4.2) is on page 2 and nowhere else.
    assert "Rs. 5 Cr" in page2
    assert "Rs. 5 Cr" not in page1
    assert "GST Registration Certificate" in page3


def test_pdf_table_is_captured_with_structure(parsed_pdf):
    """Eligibility grids are tabular; flattening them loses the row pairing that
    makes 'turnover | Rs. 5 Cr | 4.2' meaningful."""
    page2 = parsed_pdf.page(2)
    assert page2.tables, "expected the eligibility table on page 2"
    rendered = page2.tables_as_text()
    assert "Average annual turnover" in rendered
    assert "4.2" in rendered
    # Cells from one row stay on one line.
    row = next(line for line in rendered.splitlines() if "Average annual turnover" in line)
    assert "Rs. 5 Cr" in row and "4.2" in row


def test_full_text_carries_page_markers(parsed_pdf):
    text = parsed_pdf.full_text()
    assert "[PAGE 1]" in text and "[PAGE 2]" in text and "[PAGE 3]" in text
    assert text.index("[PAGE 1]") < text.index("[PAGE 2]") < text.index("[PAGE 3]")


def test_scanned_pdf_without_ocr_warns_loudly(tmp_path):
    """A page that yielded nothing must be reported. Silently returning empty
    reads downstream as 'the clause is not in this tender' -- a wrong answer,
    not a missing feature."""
    blank = make_blank_pdf(tmp_path / "scan.pdf", pages=2)
    parsed = parse_document(blank, DocumentKind.NOTIFICATION)

    assert parsed.total_chars == 0
    if ocr_available():
        pytest.skip("OCR installed; the degradation path is not exercised")
    assert len(parsed.parse_warnings) == 2
    assert all("MISSING from extraction" in w for w in parsed.parse_warnings)
    assert all(p.method is ExtractionMethod.EMPTY for p in parsed.pages)


# --------------------------------------------------------------------------- #
# DOCX
# --------------------------------------------------------------------------- #
def test_docx_respects_explicit_page_breaks(notification_docx):
    parsed = parse_document(notification_docx, DocumentKind.NOTIFICATION)
    assert parsed.page_count == 3
    assert NOTIFICATION_TRUTH["tender_id"] in parsed.page(1).text
    assert "Rs. 5 Cr" in parsed.page(2).text


def test_docx_table_extracted_and_position_caveat_recorded(notification_docx):
    parsed = parse_document(notification_docx, DocumentKind.NOTIFICATION)
    assert "Average annual turnover" in parsed.page(3).tables_as_text()
    assert any("does not preserve table position" in w for w in parsed.parse_warnings)


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def test_unsupported_formats_are_rejected_clearly(tmp_path):
    stray = tmp_path / "notes.txt"
    stray.write_text("plain text")
    with pytest.raises(UnsupportedDocumentError, match="Unsupported format"):
        parse_document(stray)

    legacy = tmp_path / "old.doc"
    legacy.write_bytes(b"\xd0\xcf")
    with pytest.raises(UnsupportedDocumentError, match="convert to .docx"):
        parse_document(legacy)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_document(tmp_path / "nope.pdf")


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #
def test_chunks_never_span_a_page_boundary(parsed_pdf):
    """A chunk covering pages 7-8 cannot honestly cite either one."""
    chunks = chunk_document(parsed_pdf)
    assert chunks
    for chunk in chunks:
        page = parsed_pdf.page(chunk.page_number)
        assert page is not None
        # Every chunk's opening line must exist on the page it claims.
        first_line = chunk.text.splitlines()[0].strip()
        assert first_line[:40] in page.combined_text()


def test_chunk_indexes_are_contiguous_and_ordered(parsed_pdf):
    chunks = chunk_document(parsed_pdf)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert [c.page_number for c in chunks] == sorted(c.page_number for c in chunks)


def test_chunks_respect_the_size_budget(parsed_pdf):
    for chunk in chunk_document(parsed_pdf):
        assert len(chunk.text) <= DEFAULT_CHUNK_SIZE


def test_clause_ref_detected_from_leading_number():
    chunks = chunk_text(
        "4.2 The bidder shall have an average annual turnover of not less than Rs. 5 Cr."
    )
    assert chunks[0].clause_ref == "4.2"
    assert chunk_text("General instructions to bidders.")[0].clause_ref is None


def test_long_text_splits_without_dropping_content():
    body = " ".join(f"Sentence number {i} about tender compliance." for i in range(400))
    chunks = chunk_text(body, section=ChunkSection.TECHNICAL_APPROACH)
    assert len(chunks) > 1
    assert all(len(c.text) <= DEFAULT_CHUNK_SIZE for c in chunks)
    assert all(c.section is ChunkSection.TECHNICAL_APPROACH for c in chunks)
    # No content silently lost in the split.
    assert "Sentence number 0 " in chunks[0].text
    assert "Sentence number 399" in " ".join(c.text for c in chunks)


def test_empty_pages_produce_no_chunks(tmp_path):
    blank = make_blank_pdf(tmp_path / "blank.pdf", pages=2)
    assert chunk_document(parse_document(blank)) == []


# --------------------------------------------------------------------------- #
# Borderless tables (Section 13: "tables, multi-column" format risk)
# --------------------------------------------------------------------------- #
def test_borderless_table_found_by_text_fallback(tmp_path):
    """Many real tender tables have no ruling lines. Line-based detection misses
    them entirely, so a text-alignment pass has to pick them up."""
    from tests.doc_factory import make_borderless_table_pdf

    parsed = parse_document(make_borderless_table_pdf(tmp_path / "borderless.pdf"))
    rendered = parsed.page(1).tables_as_text()
    assert parsed.page(1).tables, "text-strategy fallback should find the unruled table"
    assert "Average annual turnover" in rendered
    row = next(line for line in rendered.splitlines() if "Average annual turnover" in line)
    assert "Rs. 5 Cr" in row and "4.2" in row


def test_prose_pages_do_not_yield_phantom_tables(parsed_pdf):
    """The text strategy will 'find' a table in running prose. Pages 1 and 3 are
    pure prose -- if the guard leaks, every clause page grows a fake grid."""
    assert parsed_pdf.page(1).tables == []
    assert parsed_pdf.page(3).tables == []
