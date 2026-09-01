"""Indian-notation currency normalization (Section 6, "Number normalization note").

Tender documents express the same figure as "Rs. 5 Cr", "5,00,00,000" or
"500 lakh". Elimination rules (Section 5.2) compare extracted numbers against
thresholds, so every amount MUST be canonicalized to absolute rupees before it
reaches the rule engine, or comparisons silently misfire.

Canonical form: `Decimal` absolute rupees, quantized to 2 places (paise).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

__all__ = ["MoneyParseError", "normalize_amount", "try_normalize_amount", "format_inr"]

# Multipliers, longest-first so "crore" wins over a bare "cr" prefix match.
_MULTIPLIERS: list[tuple[str, Decimal]] = [
    ("thousand", Decimal(1_000)),
    ("billion", Decimal(1_000_000_000)),
    ("million", Decimal(1_000_000)),
    ("crores", Decimal(10_000_000)),
    ("crore", Decimal(10_000_000)),
    ("cr", Decimal(10_000_000)),
    ("lakhs", Decimal(100_000)),
    ("lakh", Decimal(100_000)),
    ("lacs", Decimal(100_000)),
    ("lac", Decimal(100_000)),
    ("mn", Decimal(1_000_000)),
    ("bn", Decimal(1_000_000_000)),
    ("k", Decimal(1_000)),
    ("l", Decimal(100_000)),
]

# Currency markers and noise words stripped before parsing.
_CURRENCY_NOISE = re.compile(
    r"(?:₹|rs\.?|inr|rupees?|only|/-|\bapprox(?:imately)?\b|\bupto\b|\bup\s+to\b)",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)")


class MoneyParseError(ValueError):
    """Raised when a string cannot be resolved to an unambiguous rupee amount."""


def _find_multiplier(tail: str) -> Decimal:
    """Resolve the unit suffix following the numeral. Bare numbers are rupees."""
    tail = tail.strip().lstrip(".").strip()
    if not tail:
        return Decimal(1)
    for token, factor in _MULTIPLIERS:
        # Word-boundary match so "crore" doesn't match inside another word.
        if re.match(rf"{token}\b", tail, re.IGNORECASE):
            return factor
    return Decimal(1)


def normalize_amount(raw: str | int | float | Decimal) -> Decimal:
    """Convert a raw amount expression to absolute rupees.

    >>> normalize_amount("Rs. 5 Cr")
    Decimal('50000000.00')
    >>> normalize_amount("5,00,00,000")
    Decimal('50000000.00')
    >>> normalize_amount("50,00,000")
    Decimal('5000000.00')

    Raises MoneyParseError if no numeral is present.
    """
    if isinstance(raw, (int, float, Decimal)):
        return Decimal(str(raw)).quantize(Decimal("0.01"))

    if raw is None:
        raise MoneyParseError("cannot normalize None")

    cleaned = _CURRENCY_NOISE.sub(" ", str(raw)).strip()
    match = _NUMBER.search(cleaned)
    if not match:
        raise MoneyParseError(f"no numeral found in {raw!r}")

    # Indian digit grouping (5,00,00,000) carries no magnitude information once
    # the separators are removed -- strip and read the digits literally.
    digits = match.group(1).replace(",", "")
    try:
        value = Decimal(digits)
    except InvalidOperation as exc:  # pragma: no cover - guarded by the regex
        raise MoneyParseError(f"unparseable numeral in {raw!r}") from exc

    multiplier = _find_multiplier(cleaned[match.end() :])
    return (value * multiplier).quantize(Decimal("0.01"))


def try_normalize_amount(raw: str | int | float | Decimal | None) -> Decimal | None:
    """Non-raising variant: returns None when the input can't be resolved.

    Extraction should prefer this and keep the raw text alongside, so an
    unparseable figure surfaces as "needs manual check" rather than a wrong
    comparison.
    """
    if raw is None:
        return None
    try:
        return normalize_amount(raw)
    except MoneyParseError:
        return None


def format_inr(amount: Decimal) -> str:
    """Render a canonical amount back into readable Indian notation for the UI."""
    if amount >= 10_000_000:
        return f"₹{(amount / Decimal(10_000_000)).normalize():f} Cr"
    if amount >= 100_000:
        return f"₹{(amount / Decimal(100_000)).normalize():f} Lakh"
    return f"₹{amount.normalize():f}"
