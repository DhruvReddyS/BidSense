"""OCR path tests (Section 8: Tesseract, local).

These only run when Tesseract and poppler are installed. Until this build the
OCR branch had never been executed against a real scan -- only its
degradation path was covered.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingest import parse_document
from app.ingest.models import ExtractionMethod
from app.ingest.ocr import missing_dependencies, ocr_available
from app.schemas.common import DocumentKind

needs_ocr = pytest.mark.skipif(
    not ocr_available(),
    reason=f"OCR unavailable: {', '.join(missing_dependencies())}",
)

CLAUSE = (
    "4.2 The bidder shall have an average annual turnover of not less than "
    "Rs. 5 Cr during the last three financial years."
)


def make_scanned_pdf(path: Path, text: str = CLAUSE) -> Path:
    """Render text to an image, then wrap the image in a PDF.

    This is what a scanned tender actually is: pixels, no text layer. Drawing
    text directly into the PDF would leave an extractable text layer and the
    OCR branch would never run.
    """
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    image = Image.new("RGB", (2480, 3508), "white")   # A4 at 300dpi
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Supplemental/Arial.ttf", size=64
        )
    except OSError:  # pragma: no cover - font layout varies by machine
        font = ImageFont.load_default()

    y = 300
    for line in text.split(" | "):
        draw.text((200, y), line, fill="black", font=font)
        y += 120

    image_path = path.with_suffix(".png")
    image.save(image_path, dpi=(300, 300))

    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.drawImage(str(image_path), 0, 0, width=A4[0], height=A4[1])
    pdf.showPage()
    pdf.save()
    return path


@needs_ocr
def test_scanned_page_is_ocrd_and_the_clause_is_recovered(tmp_path):
    """The real thing this exists for: a scan whose text is only pixels must
    still yield the clause a compliance check depends on."""
    scanned = make_scanned_pdf(tmp_path / "scanned.pdf")
    parsed = parse_document(scanned, DocumentKind.NOTIFICATION)

    page = parsed.page(1)
    assert page.method is ExtractionMethod.OCR, "the OCR branch should have run"
    assert parsed.is_scanned is True
    assert parsed.ocr_page_count == 1

    text = " ".join(page.text.split())
    assert "turnover" in text.lower()
    # The figure is the whole point -- a clause recovered without its number is
    # useless to the rule engine.
    assert "5 Cr" in text or "5Cr" in text


@needs_ocr
def test_ocrd_amount_normalizes_to_the_right_rupee_value(tmp_path):
    """OCR output feeds the same normalizer as native text. If the two disagree,
    scanned tenders silently produce different thresholds from identical text."""
    from decimal import Decimal

    from app.normalize.money import try_normalize_amount

    scanned = make_scanned_pdf(tmp_path / "amount.pdf", "EMD of Rs. 2,00,000 is payable")
    parsed = parse_document(scanned, DocumentKind.NOTIFICATION)
    text = " ".join(parsed.page(1).text.split())

    assert "2,00,000" in text, f"OCR did not recover the figure: {text!r}"
    assert try_normalize_amount("Rs. 2,00,000") == Decimal("200000.00")


@needs_ocr
def test_native_text_pages_still_skip_ocr(tmp_path):
    """OCR is expensive. A page with a real text layer must not be rendered and
    re-read -- on a 382-page tender that would be the difference between minutes
    and hours."""
    from tests.doc_factory import make_notification_pdf

    parsed = parse_document(
        make_notification_pdf(tmp_path / "native.pdf"), DocumentKind.NOTIFICATION
    )
    assert parsed.ocr_page_count == 0
    assert all(p.method is ExtractionMethod.NATIVE for p in parsed.pages)


@needs_ocr
def test_truly_blank_scan_reports_missing_content(tmp_path):
    """With OCR available, a blank page yields nothing and must still warn --
    the fix for false 'empty' warnings must not have silenced the real case."""
    from tests.doc_factory import make_blank_pdf

    parsed = parse_document(make_blank_pdf(tmp_path / "blank.pdf", pages=1))
    assert parsed.page(1).method is ExtractionMethod.EMPTY
    assert len(parsed.parse_warnings) == 1
    assert "MISSING from extraction" in parsed.parse_warnings[0]


@needs_ocr
def test_chunks_from_an_ocrd_page_keep_their_page_number(tmp_path):
    """Citation provenance must survive the OCR path, or scanned tenders produce
    answers that cannot be checked."""
    from app.ingest import chunk_document

    parsed = parse_document(make_scanned_pdf(tmp_path / "cite.pdf"))
    chunks = chunk_document(parsed)
    assert chunks
    assert all(c.page_number == 1 for c in chunks)
