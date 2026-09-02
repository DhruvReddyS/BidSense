"""Render one page of a stored document, with a cited passage highlighted.

Rendered on the server rather than in the browser, for two reasons that both
come down to trust. The highlight is computed from the SAME word coordinates
pdfplumber gives the extractor, so what the vendor sees marked is what the
citation actually points at -- a browser-side text search over a re-extracted
text layer can disagree with the server about where a phrase is. And it works
without a PDF stack in the frontend, so the page a vendor sees is a page the
backend can be held to.

The matching is deliberately forgiving. A `source_snippet` is the model's
verbatim copy of a sentence, and "verbatim" survives a trip through PDF text
extraction with its whitespace, hyphenation and ligatures rearranged. An exact
run of words is tried first, then the best-overlapping window; below a floor,
nothing is highlighted and the page is returned plain, because a confidently
wrong highlight is worse than none -- it points a vendor at the wrong clause.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["render_page", "PageRender", "find_highlight_boxes"]

DEFAULT_DPI = 110
# Below this share of the snippet's words matched in a window, no highlight is
# drawn. Tuned so a genuinely different sentence never lights up.
MIN_MATCH_RATIO = 0.55
# Highlight colours: a marker-pen yellow that survives being screenshotted, with
# a darker edge so it is visible in a dark-themed viewer too.
FILL = (255, 214, 0, 90)
EDGE = (201, 148, 0, 255)
PAD = 3


@dataclass(frozen=True)
class PageRender:
    png: bytes
    page: int
    page_count: int
    width: int
    height: int
    #: How many passages were highlighted. Zero is a legitimate answer, and the
    #: UI says so rather than implying the page was marked.
    highlights: int


_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(text or "")]


def find_highlight_boxes(words: list[dict], snippet: str) -> list[tuple[float, float, float, float]]:
    """Locate a snippet among a page's words, returning boxes in PDF points.

    `words` is pdfplumber's `extract_words()` output: dicts with x0/x1/top/bottom
    in points, top-left origin.
    """
    target = _tokens(snippet)
    if len(target) < 2 or not words:
        return []

    normalised = [_tokens(w["text"]) for w in words]
    flat: list[tuple[str, int]] = []
    for index, tokens in enumerate(normalised):
        for token in tokens:
            flat.append((token, index))
    if not flat:
        return []

    size = len(target)
    wanted = set(target)
    best_score, best_span = 0.0, None

    # A sliding window the length of the snippet. Scored on set overlap rather
    # than exact sequence, because PDF extraction reorders words across a line
    # break often enough that an exact-sequence-only matcher misses real hits.
    for start in range(0, max(1, len(flat) - size + 1)):
        window = flat[start : start + size]
        score = sum(1 for token, _ in window if token in wanted) / size
        if score > best_score:
            best_score, best_span = score, (window[0][1], window[-1][1])

    if best_span is None or best_score < MIN_MATCH_RATIO:
        logger.debug("no highlight: best window scored %.2f", best_score)
        return []

    first, last = best_span
    run = words[first : last + 1]
    if not run:
        return []

    # One box per line, not one box around the whole run: a snippet spanning
    # three lines would otherwise be a rectangle covering everything between
    # them, including the text either side.
    boxes: list[tuple[float, float, float, float]] = []
    line: list[dict] = []
    for word in run:
        if line and abs(word["top"] - line[0]["top"]) > 3:
            boxes.append(_bbox(line))
            line = []
        line.append(word)
    if line:
        boxes.append(_bbox(line))
    return boxes


def _bbox(words: list[dict]) -> tuple[float, float, float, float]:
    return (
        min(w["x0"] for w in words),
        min(w["top"] for w in words),
        max(w["x1"] for w in words),
        max(w["bottom"] for w in words),
    )


@lru_cache(maxsize=64)
def _page_words(path_str: str, page: int) -> tuple[tuple, ...]:
    """Word boxes for one page, cached: opening a 382-page PDF is not free and a
    vendor clicking through several citations hits the same pages repeatedly."""
    import pdfplumber

    with pdfplumber.open(path_str) as pdf:
        if not 1 <= page <= len(pdf.pages):
            return ()
        words = pdf.pages[page - 1].extract_words()
    return tuple(
        (w["text"], w["x0"], w["top"], w["x1"], w["bottom"]) for w in words
    )


@lru_cache(maxsize=8)
def _page_count(path_str: str) -> int:
    import pdfplumber

    with pdfplumber.open(path_str) as pdf:
        return len(pdf.pages)


def render_page(
    path: str | Path,
    page: int,
    *,
    highlight: str | None = None,
    dpi: int = DEFAULT_DPI,
) -> PageRender:
    """Render `page` to PNG, marking `highlight` if it can be located."""
    from pdf2image import convert_from_path
    from PIL import Image, ImageDraw

    path = Path(path)
    total = _page_count(str(path))
    page = max(1, min(page, total or 1))

    images = convert_from_path(path, dpi=dpi, first_page=page, last_page=page)
    if not images:
        raise ValueError(f"page {page} could not be rendered")
    image = images[0]

    boxes: list[tuple[float, float, float, float]] = []
    if highlight:
        raw = _page_words(str(path), page)
        words = [
            {"text": t, "x0": x0, "top": top, "x1": x1, "bottom": bottom}
            for t, x0, top, x1, bottom in raw
        ]
        boxes = find_highlight_boxes(words, highlight)

    if boxes:
        scale = dpi / 72.0
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for x0, top, x1, bottom in boxes:
            draw.rectangle(
                [x0 * scale - PAD, top * scale - PAD, x1 * scale + PAD, bottom * scale + PAD],
                fill=FILL,
                outline=EDGE,
                width=2,
            )
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return PageRender(
        png=buffer.getvalue(),
        page=page,
        page_count=total,
        width=image.width,
        height=image.height,
        highlights=len(boxes),
    )
