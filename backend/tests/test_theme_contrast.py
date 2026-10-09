"""Both themes must stay readable, measured rather than eyeballed.

This lives in the backend suite because that is the suite that runs; it reads
the frontend stylesheet as data and never imports anything from it.

It exists because the stylesheet carries three `:root` blocks. Two sit outside
`@layer base`, unlayered CSS beats layered CSS, and the last unlayered block
wins -- so the carefully documented first palette is NOT what renders, and a
contrast fix applied there would have no effect at all. The merge below
reproduces that cascade, which is the only way to check the colours a user
actually sees.

WCAG 2.1 AA: 4.5:1 for normal text. Decorative separators are deliberately not
checked -- the 3:1 rule covers UI components that convey state or bounds, not
hairlines between rows.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS_PATH = (
    Path(__file__).resolve().parents[2] / "frontend" / "app" / "globals.css"
)
AA_NORMAL_TEXT = 4.5

#: (foreground token, background token, what the user is reading)
TEXT_PAIRS = [
    ("fg", "bg", "body text"),
    ("fg", "surface", "text on a card"),
    ("fg-muted", "bg", "muted text on the page"),
    ("fg-muted", "surface", "muted text on a card"),
    ("fg-muted", "surface-2", "muted text on a raised surface"),
    ("fg-subtle", "bg", "subtle text on the page"),
    ("fg-subtle", "surface", "subtle text on a card"),
    ("accent", "bg", "link on the page"),
    ("accent", "surface", "link on a card"),
    ("accent", "surface-2", "link on a raised surface"),
    ("accent-fg", "accent", "primary button label"),
    ("ok", "ok-soft", "pass chip"),
    ("warn", "warn-soft", "warning chip"),
    ("bad", "bad-soft", "fail chip"),
    ("pending", "pending-soft", "pending chip"),
    ("info", "info-soft", "info chip"),
    ("ok", "surface", "pass text on a card"),
    ("warn", "surface", "warning text on a card"),
    ("bad", "surface", "fail text on a card"),
    ("pending", "surface", "pending text on a card"),
]

_DECL = re.compile(r"--([\w-]+):\s*([\d.]+ [\d.]+% [\d.]+%)")


def _blocks(css: str, selector: str) -> list[dict[str, str]]:
    """Every block for a selector, in source order, brace-matched."""
    found = []
    for match in re.finditer(selector + r"\s*\{", css):
        depth, i = 1, match.end()
        while i < len(css) and depth:
            depth += (css[i] == "{") - (css[i] == "}")
            i += 1
        found.append(dict(_DECL.findall(css[match.end(): i - 1])))
    return found


def _hsl_to_rgb(value: str) -> tuple[float, float, float]:
    hue, sat, light = (float(p.rstrip("%")) for p in value.split())
    hue, sat, light = hue / 360, sat / 100, light / 100
    if sat == 0:
        return (light, light, light)
    q = light * (1 + sat) if light < 0.5 else light + sat - light * sat
    p = 2 * light - q

    def channel(t: float) -> float:
        t %= 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    return (channel(hue + 1 / 3), channel(hue), channel(hue - 1 / 3))


def _luminance(value: str) -> float:
    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in _hsl_to_rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(foreground: str, background: str) -> float:
    a, b = _luminance(foreground), _luminance(background)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


@pytest.fixture(scope="module")
def palettes() -> dict[str, dict[str, str]]:
    """The tokens as the browser resolves them, per theme."""
    css = CSS_PATH.read_text()
    light: dict[str, str] = {}
    for block in _blocks(css, r":root"):
        light.update(block)                     # later declarations win
    dark = dict(light)
    for block in _blocks(css, r"\[data-theme=\"?dark\"?\]"):
        dark.update(block)
    return {"light": light, "dark": dark}


def test_the_stylesheet_is_where_we_think_it_is():
    assert CSS_PATH.is_file(), f"no stylesheet at {CSS_PATH}"


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("fg,bg,what", TEXT_PAIRS)
def test_text_meets_wcag_aa(palettes, theme, fg, bg, what):
    tokens = palettes[theme]
    if fg not in tokens or bg not in tokens:
        pytest.skip(f"{theme}: no token for {fg if fg not in tokens else bg}")
    got = contrast(tokens[fg], tokens[bg])
    assert got >= AA_NORMAL_TEXT, (
        f"{theme}: {what} ({fg} on {bg}) is {got:.2f}:1, "
        f"below AA {AA_NORMAL_TEXT}:1. Adjust the token in the LAST "
        f"unlayered block -- earlier blocks do not render."
    )


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_pairing_resolves_to_a_real_token(palettes, theme):
    """A typo'd token name silently renders as transparent, not as an error."""
    tokens = palettes[theme]
    missing = sorted({
        name for fg, bg, _ in TEXT_PAIRS for name in (fg, bg)
        if name not in tokens
    })
    assert not missing, f"{theme}: unresolved tokens {missing}"


def test_contrast_maths_matches_known_values():
    """Black on white is 21:1; a colour against itself is 1:1."""
    assert contrast("0 0% 0%", "0 0% 100%") == pytest.approx(21.0, abs=0.05)
    assert contrast("0 0% 50%", "0 0% 50%") == pytest.approx(1.0)
