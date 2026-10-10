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


# --------------------------------------------------------------------------- #
# Compositional presence -- the fix that made this wireable.
#
# Narrowing the reference set is NOT what fixed the false-finding rate: on a
# tender page, flat and structural extraction produce the same findings even
# though the reference set shrinks from 13 to 4. The flaw was that `is_present`
# demanded a concatenated reference appear verbatim, while a legitimate citation
# composes a section heading with a sub-item printed beneath it. Those
# compositions were most of the twenty findings per tender that kept this module
# out of the validation pass.
# --------------------------------------------------------------------------- #

from app.extraction.clause_check import (                      # noqa: E402
    document_sections,
    is_present_compositional,
    structural_references,
    unverifiable_citations,
)

TENDER_PAGE = """
1.1  Scope of work and eligibility
     The contractor shall meet the following:
 (4) Largest similar completed work of not less than 80% of estimated cost
28.1 The Chief General Manager will evaluate whether each Tenderer meets
 vi) Liquid assets and/ or credit facilities of not less than Rs.18.400 Crores
     0.973
     1,24,500.00    2,98,720.00    49.855
2.6 Earnest money and its forms
 (b) Earnest money shall be furnished in the form prescribed
"""


def test_structural_extraction_drops_amounts_and_keeps_clauses():
    references = structural_references(TENDER_PAGE)
    assert "28.1" in references
    assert "2.6" in references
    for noise in ("0.973", "49.855", "298720.00", "124500.00"):
        assert noise not in references, f"{noise} is an amount, not a clause"


def test_a_line_leading_amount_is_not_read_as_a_clause():
    """A table row may begin with a figure; "49.855 Crores" is not clause 49.855."""
    assert "49.855" not in structural_references("49.855 Crores\n")


def test_a_zero_leading_ratio_is_never_a_clause():
    assert "0.973" not in structural_references("0.973 is the ratio\n")


def test_sections_carry_the_sub_items_printed_under_them():
    sections = document_sections(TENDER_PAGE)
    assert sections["1.1"] == {"4"}
    assert sections["28.1"] == {"vi"}
    assert sections["2.6"] == {"b"}


def test_a_sub_item_belongs_to_the_heading_above_it_not_the_one_below():
    sections = document_sections(TENDER_PAGE)
    assert "vi" not in sections["1.1"], "vi) sits under 28.1"
    assert "4" not in sections["28.1"], "(4) sits under 1.1"


def test_a_section_plus_sub_item_citation_is_accepted():
    """civilworks_01 prints "1.1" and "(4)" separately and never "1.1 (4)".
    Reporting that as unverifiable was the bulk of the twenty false findings."""
    for citation in ("1.1(4)", "1.1 (4)", "28.1(vi)", "2.6(b)"):
        assert is_present_compositional(citation, TENDER_PAGE), citation


def test_the_misplaced_dot_is_still_caught():
    """The defect the module was built for. For "2.8.1" to be legitimate the
    document would have to print a section 2.8 with sub-item 1; it prints 28.1."""
    assert not is_present_compositional("2.8.1", TENDER_PAGE)
    findings = dict(unverifiable_citations(["2.8.1"], TENDER_PAGE))
    assert findings["2.8.1"] == "28.1", "the near-miss must be named"


def test_half_a_citation_is_not_a_citation():
    """The section must exist AND carry that sub-item. Either alone is not it."""
    assert not is_present_compositional("1.1(99)", TENDER_PAGE), "no sub-item 99"
    assert not is_present_compositional("77.7(4)", TENDER_PAGE), "no section 77.7"


def test_a_wholly_absent_clause_is_reported_without_a_suggestion():
    findings = unverifiable_citations(["9.9(z)"], TENDER_PAGE)
    assert findings == [("9.9(z)", None)], (
        "an ambiguous or invented suggestion is worse than none"
    )


def test_composition_cuts_the_findings_without_losing_the_real_one():
    """The whole case for wiring this in: 6 findings become 2, both real."""
    cited = ["1.1(4)", "1.1 (4)", "28.1(vi)", "2.6(b)", "2.8.1", "9.9(z)"]
    findings = unverifiable_citations(cited, TENDER_PAGE)
    assert [f[0] for f in findings] == ["2.8.1", "9.9(z)"]


def test_an_empty_document_reports_nothing_rather_than_everything():
    """A page that failed to parse must not indict every citation on it.

    An earlier version of this test expected the citation to be reported as
    unverifiable. That was the wrong expectation: with no text there is no
    structure, so there is no basis for the claim either way, and reporting one
    finding per citation against an unparsed page is the noise that kept this
    check out of the validation pass. Reporting nothing is the honest answer.
    """
    assert unverifiable_citations(["1.1(4)"], "") == []
    assert unverifiable_citations([], TENDER_PAGE) == []
    assert unverifiable_citations(["", "  "], TENDER_PAGE) == []


def test_a_document_with_no_clause_numbering_reports_nothing():
    """Not a test accommodation -- a real failure mode.

    A scanned tender whose OCR recovered prose but not its numbering, or a page
    that failed to parse, yields no structural references at all. Flagging every
    citation against it is unfounded and reproduces the twenty-findings-per-
    tender noise this module was held back for. "We could not read the
    structure" is an extraction-coverage problem, not a wrong citation.
    """
    featureless = "x" * 500
    assert structural_references(featureless) == set()
    assert unverifiable_citations(["4.2", "1.1(4)"], featureless) == []


def test_a_document_with_some_structure_still_flags_a_missing_clause():
    """The guard must not become a loophole: partial structure still verifies."""
    page = "4.2 Average annual turnover shall not be less than Rs. 3 Crores\n"
    assert structural_references(page)
    assert unverifiable_citations(["4.2"], page) == []
    assert unverifiable_citations(["9.9"], page) == [("9.9", None)]
