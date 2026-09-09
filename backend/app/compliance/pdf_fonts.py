"""Portable PDF font assets and explicit rejection of unsupported characters."""
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

FONT_ROOT = Path(__file__).parent / 'fonts'
FAMILIES = ('NotoSans', 'NotoSansDevanagari', 'NotoSansTelugu')


class UnsupportedPDFText(ValueError):
    pass


@lru_cache(maxsize=1)
def supported_characters():
    from fontTools.ttLib import TTFont
    codes = set()
    for family in FAMILIES:
        with TTFont(FONT_ROOT / f'{family}-Regular.ttf') as font:
            codes.update(font.getBestCmap())
    return frozenset(codes)


def pdf_text(value) -> str:
    text = '' if value is None else str(value)
    supported = supported_characters()
    for char in text:
        if not char.isspace() and char not in '\u200c\u200d' and ord(char) not in supported:
            raise UnsupportedPDFText(f'PDF export cannot render U+{ord(char):04X} yet. Export DOCX to preserve this text.')
    return escape(text)


def font_styles():
    return '\n'.join(
        f'@font-face {{ font-family: {family}; font-weight: {weight}; src: url("bidsense://fonts/{family}-{style}.ttf"); }}'
        for family in FAMILIES for style, weight in [('Regular',400),('Bold',700)]
    )


def fetch_font(url, **kwargs):
    """The renderer can read only our six fonts, never URLs from report data."""
    allowed = {f'bidsense://fonts/{family}-{style}.ttf': FONT_ROOT / f'{family}-{style}.ttf'
               for family in FAMILIES for style in ('Regular','Bold')}
    if url not in allowed:
        raise ValueError('External resources are not allowed in PDF exports')
    return {'string': allowed[url].read_bytes(), 'mime_type': 'font/ttf'}
