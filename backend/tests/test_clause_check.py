"""Clause-reference verification, and the defect that motivated it."""

from __future__ import annotations

from app.extraction.clause_check import (
    is_present,
    source_references,
    suggest_correction,
)

#: The HGCL tender as it is actually printed.
SOURCE = """
28.1 The Chief General Manager will evaluate whether each Tenderer is satisfying
vi) Liquid assets and/ or credit facilities of not less than Rs.49.855 Crores
11.I.(a) Original Non-Refundable Tender Processing Fee
11.II(a) Declaration regarding procurement of Solar Inverters
1.1 (4) Largest similar completed work
2.6 (b) Valid Class II/III Digital Signature Certificate
"""


def test_the_misplaced_dot_defect_is_detected() -> None:
    """Extraction returns "2.8.1 (vi)" where the tender prints "28.1".

    Consistent across every sub-clause, so nothing downstream looked wrong, and
    the elimination it supported was correct while its citation was not. A
    reviewer looking up 2.8.1 in that tender finds nothing.
    """
    references = source_references(SOURCE)
    assert not is_present("2.8.1 (vi)", references)
    assert suggest_correction("2.8.1", references) == "28.1"


def test_typography_is_not_a_difference() -> None:
    """"1.1 (4)" and "1.1(4)" are the same clause by any reading."""
    references = source_references(SOURCE)
    for cited in ("1.1(4)", "1.1 (4)", "2.6(b)", "2.6 (b)", "11.I.(a)", "11.II(a)"):
        assert is_present(cited, references), cited


def test_a_correct_reference_is_never_offered_a_correction() -> None:
    """Both "11.I.(a)" and "11.II(a)" reduce to the digits "11".

    Without a presence check first, each was offered the other as a
    correction -- a sound citation reported as a defect.
    """
    references = source_references(SOURCE)
    assert suggest_correction("11.I.(a)", references) is None
    assert suggest_correction("11.II(a)", references) is None


def test_a_parent_clause_is_satisfied_by_a_more_specific_child() -> None:
    """Citing "28.1" is sound when the document prints "28.1(vi)".

    The extra specificity is the document's, not an error in the citation.
    """
    assert is_present("28.1", source_references("28.1(vi) Liquid assets"))


def test_an_absent_reference_with_no_near_miss_gets_no_suggestion() -> None:
    """An ambiguous or absent suggestion is worse than none: it invites a
    reviewer to accept a citation that may still be wrong."""
    references = source_references(SOURCE)
    assert not is_present("99.9", references)
    assert suggest_correction("99.9", references) is None


def test_empty_inputs_are_safe() -> None:
    assert source_references("") == set()
    assert not is_present("", {"28.1"})
    assert suggest_correction("", {"28.1"}) is None
