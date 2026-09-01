"""Section 6's number-normalization requirement, tested directly.

Elimination rules compare canonical rupees, so a bug here silently misfires
disqualification decisions -- exactly the failure Section 6 warns about.
"""

from decimal import Decimal

import pytest

from app.normalize.money import MoneyParseError, format_inr, normalize_amount, try_normalize_amount


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Indian digit grouping carries no magnitude once separators are stripped.
        ("5,00,00,000", "50000000.00"),
        ("50,00,000", "5000000.00"),
        ("50000000", "50000000.00"),
        # Crore / lakh suffixes, with and without currency markers.
        ("₹5 Cr", "50000000.00"),
        ("Rs. 5 Cr", "50000000.00"),
        ("Rs 5 crore", "50000000.00"),
        ("5 Crores", "50000000.00"),
        ("INR 4.2 Cr", "42000000.00"),
        ("2.1cr", "21000000.00"),
        ("500 lakh", "50000000.00"),
        ("50 Lakhs", "5000000.00"),
        ("25 lac", "2500000.00"),
        # Western units appear in corporate RFPs.
        ("5 million", "5000000.00"),
        ("1 billion", "1000000000.00"),
        ("50 thousand", "50000.00"),
        # Noise words that must not change the value.
        ("Rupees 5 Cr only", "50000000.00"),
        ("₹ 5,00,00,000/-", "50000000.00"),
        ("approx. 5 Cr", "50000000.00"),
    ],
)
def test_normalize_amount(raw: str, expected: str) -> None:
    assert normalize_amount(raw) == Decimal(expected)


def test_the_section_6_example_figures_are_distinguished() -> None:
    """Section 6 lists these as commonly-confused notations. They are NOT equal,
    and the normalizer must not conflate them."""
    assert normalize_amount("₹5 Cr") == normalize_amount("5,00,00,000")
    assert normalize_amount("50,00,000") != normalize_amount("₹5 Cr")


def test_numeric_passthrough() -> None:
    assert normalize_amount(50_000_000) == Decimal("50000000.00")
    assert normalize_amount(Decimal("4.2")) == Decimal("4.20")


def test_unparseable_raises_and_try_variant_returns_none() -> None:
    with pytest.raises(MoneyParseError):
        normalize_amount("as per tender document")
    assert try_normalize_amount("as per tender document") is None
    assert try_normalize_amount(None) is None


def test_format_inr_round_trip() -> None:
    assert format_inr(Decimal("50000000.00")) == "₹5 Cr"
    assert format_inr(Decimal("5000000.00")) == "₹50 Lakh"
