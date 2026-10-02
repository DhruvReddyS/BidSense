"""Query-side domain expansion (Section 4.5)."""

from __future__ import annotations

from app.rag.expand import expand_query


def test_the_abbreviation_a_tender_uses_is_added_to_the_long_form():
    """"earnest money" must reach chunks that only ever say "EMD".

    This is the defect's actual shape: the GHMC notice records the figure as
    `emd @ 1% | rs. 2,98,720.00`, so a vendor asking about earnest money was
    0.18 cosine away from their own answer.
    """
    expanded = expand_query("What is the earnest money payable for this tender?")
    assert "emd" in expanded.casefold()
    # The user's own wording leads; expansion is additive, never a rewrite.
    assert expanded.startswith("What is the earnest money payable for this tender?")


def test_expansion_works_in_both_directions():
    assert "earnest money deposit" in expand_query("How much EMD?").casefold()
    assert "emd" in expand_query("What earnest money deposit applies?").casefold()


def test_synonyms_are_treated_as_equivalent_not_merely_abbreviations():
    """"bid security" and "EMD" are the same instrument under two names."""
    assert "emd" in expand_query("What bid security is required?").casefold()


def test_a_query_with_no_domain_term_is_returned_untouched():
    """Expansion must be a no-op rather than a distortion.

    Measured: appending an irrelevant "EMD" to "By when must I upload my bid?"
    moved the correct deadline chunk from 0.6941 to 0.6090. A wrong expansion
    is worse than none, so absence of a match must mean absence of a change.
    """
    question = "By when must I upload my bid?"
    assert expand_query(question) == question


def test_terms_are_matched_whole_not_as_substrings():
    """"pan" inside "expansion" must not pull in "permanent account number"."""
    assert expand_query("What is the expansion plan?") == "What is the expansion plan?"
    assert "permanent account number" in expand_query("Do I need a PAN card?").casefold()


def test_the_longest_matching_form_is_expanded_once():
    """"earnest money deposit" must not also fire the "earnest money" entry."""
    expanded = expand_query("Is the earnest money deposit refundable?").casefold()
    assert expanded.count("earnest money deposit") == 1


def test_expansion_is_bounded():
    """A query naming several domain terms cannot grow without limit.

    The cap counts TERMS, not words -- one term ("earnest money deposit") is
    three words -- so the property under test is that raising the cap adds
    monotonically more and that a cap of zero adds nothing at all.
    """
    noisy = "earnest money, bank guarantee, joint venture, bill of quantities, GST, PAN"
    lengths = [len(expand_query(noisy, max_additions=n)) for n in (0, 1, 3, 10)]
    assert lengths[0] == len(noisy), "a cap of zero must leave the query alone"
    assert lengths[0] < lengths[1] < lengths[2] < lengths[3]
    # And the cap genuinely binds: ten additions is not unbounded growth.
    assert lengths[3] < len(noisy) * 4


def test_empty_and_blank_queries_are_safe():
    assert expand_query("") == ""
    assert expand_query("   ") == "   "
