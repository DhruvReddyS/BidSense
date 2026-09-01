"""Tesseract OCR (Section 8: local, free, offline).

Kept behind availability checks so the whole pipeline degrades to native-text-only
rather than crashing on a machine without Tesseract installed. A scanned page that
could not be OCR'd must be reported as a warning, never silently returned empty --
an empty page reads downstream as "the clause isn't in this tender".
"""

from __future__ import annotations

import logging
import shutil
from functools import lru_cache

logger = logging.getLogger(__name__)

# Tesseract page-segmentation mode 3 = fully automatic, no orientation detection.
# Tender scans are single-column-ish text pages; PSM 3 handles them without the
# aggressive assumptions of the column-aware modes.
DEFAULT_CONFIG = "--oem 3 --psm 3"
DEFAULT_DPI = 300  # below ~250 Tesseract accuracy drops sharply on 10pt text


@lru_cache(maxsize=1)
def tesseract_available() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def poppler_available() -> bool:
    """pdf2image shells out to poppler's pdftoppm to rasterise PDF pages."""
    return shutil.which("pdftoppm") is not None


def ocr_available() -> bool:
    return tesseract_available() and poppler_available()


def missing_dependencies() -> list[str]:
    missing = []
    if not tesseract_available():
        missing.append("tesseract")
    if not poppler_available():
        missing.append("poppler (pdftoppm)")
    return missing


def ocr_image(image, lang: str = "eng") -> str:
    import pytesseract

    return pytesseract.image_to_string(image, lang=lang, config=DEFAULT_CONFIG).strip()


def ocr_pdf_page(pdf_path: str, page_number: int, dpi: int = DEFAULT_DPI) -> str:
    """Rasterise one 1-indexed PDF page and OCR it.

    Rendered one page at a time on purpose: a 200-page scanned tender rendered
    in one go at 300dpi will exhaust memory.
    """
    if not ocr_available():
        raise RuntimeError(
            f"OCR unavailable, missing: {', '.join(missing_dependencies())}. "
            "Install with: brew install tesseract poppler"
        )
    from pdf2image import convert_from_path

    images = convert_from_path(
        pdf_path, dpi=dpi, first_page=page_number, last_page=page_number
    )
    if not images:
        return ""
    try:
        return ocr_image(images[0])
    finally:
        for image in images:
            image.close()
