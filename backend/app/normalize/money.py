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
# Indian grouping, tolerating whitespace after a comma: real tenders print
# "Rs.3, 00, 00,000/-" (observed in the GHMC LED tender). Without the optional
# space the match stops at "3" and a Rs. 3 crore requirement becomes Rs. 3 --
# a threshold every bidder on earth clears.
#
# The space is allowed only AFTER a comma, and only before a 2-3 digit group.
# Allowing bare space-separated digits would merge "at least 2, Rs. 2 Cr" into
# a single number, and merge unrelated figures like "30 60 90 days".
_NUMBER = re.compile(r"(\d+(?:,\s*\d{2,3})*(?:\.\d+)?)")


# A numeral immediately followed by a percent sign is a rate, not an amount.
# Tenders write "EMD @ 1% of the ECV" and "turnover of 30% of the estimated
# cost"; read as absolute figures those become Rs. 1 and Rs. 30, which every
# bidder clears. Percentages are resolved against a base elsewhere, by code that
# knows what the base is -- here they are simply not amounts.
# The word boundary applies only to the spelled-out forms: "%" is already a
# non-word character, so "%\b" never matches before a space.
_PERCENT_SUFFIX = re.compile(r"^\s*(?:%|(?:per\s*cent|percent)\b)", re.IGNORECASE)


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
    candidates = list(_NUMBER.finditer(cleaned))
    if not candidates:
        raise MoneyParseError(f"no numeral found in {raw!r}")

    # A string may hold several numbers -- "At least 2 projects of Rs. 2 Cr each"
    # has a count and an amount. Taking the first numeral blindly yields a
    # threshold of Rs. 2, which every bidder on earth clears. Prefer the numeral
    # that a magnitude unit is actually attached to; fall back to the first only
    # when no numeral carries a unit.
    # Drop percentages before choosing: "1% of the ECV" holds a numeral but no
    # amount, and returning Rs. 1 would be worse than returning nothing.
    absolute = [
        match for match in candidates
        if not _PERCENT_SUFFIX.match(cleaned[match.end() :])
    ]
    if not absolute:
        raise MoneyParseError(
            f"{raw!r} states a percentage, not an absolute amount"
        )

    chosen, multiplier = None, Decimal(1)
    for match in absolute:
        factor = _find_multiplier(cleaned[match.end() :])
        if factor > 1:
            chosen, multiplier = match, factor
            break
    if chosen is None:
        chosen = absolute[0]

    # Separators carry no magnitude once removed -- the digits themselves do.
    digits = chosen.group(1).replace(",", "").replace(" ", "")
    try:
        value = Decimal(digits)
    except InvalidOperation as exc:  # pragma: no cover - guarded by the regex
        raise MoneyParseError(f"unparseable numeral in {raw!r}") from exc

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


def _trim(value: Decimal) -> str:
    """At most three decimal places, with trailing zeros removed.

    `normalize()` alone keeps every significant digit, so a threshold derived
    from a percentage rendered as "10.052488 Lakh" -- arithmetic precision
    presented as if it were the tender's own figure.

    Three rather than two, because tenders state crore figures to three places
    and rounding changes what the document says: HGCL requires "Rs. 49.855
    Crores", and an elimination notice quoting "Rs. 49.86 Cr" misstates the
    clause it is enforcing.
    """
    quantized = value.quantize(Decimal("0.001"))
    text = format(quantized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def format_inr(amount: Decimal) -> str:
    """Render a canonical amount back into readable Indian notation for the UI."""
    if amount >= 10_000_000:
        return f"₹{_trim(amount / Decimal(10_000_000))} Cr"
    if amount >= 100_000:
        return f"₹{_trim(amount / Decimal(100_000))} Lakh"
    return f"₹{_trim(amount)}"
