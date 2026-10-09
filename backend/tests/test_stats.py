"""Wilson intervals for the evaluation reports."""

from __future__ import annotations

from app.rag.stats import fmt_pct_ci, wilson


def test_a_perfect_small_sample_does_not_claim_certainty():
    """17/17 must not be reported as "100%, no uncertainty".

    This is the whole reason the module exists: the extraction evaluator scores
    17 of 17 header fields, and the normal approximation gives that a
    zero-width interval -- a claim of certainty from seventeen observations.
    """
    low, high = wilson(17, 17)
    assert high == 1.0
    assert 0.75 < low < 0.95, low


def test_intervals_stay_inside_zero_and_one():
    for successes, total in ((0, 5), (5, 5), (1, 100), (99, 100)):
        low, high = wilson(successes, total)
        assert 0.0 <= low <= high <= 1.0


def test_more_evidence_narrows_the_interval():
    narrow = wilson(80, 100)
    wide = wilson(8, 10)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_zero_successes_has_a_lower_bound_of_zero():
    low, high = wilson(0, 17)
    assert low == 0.0
    assert high > 0.0


def test_empty_sample_is_maximally_uncertain():
    assert wilson(0, 0) == (0.0, 1.0)
    assert fmt_pct_ci(0, 0) == "n/a"


def test_format_shows_the_figure_its_bounds_and_n():
    text = fmt_pct_ci(13, 17)
    assert "76.5%" in text
    assert "n=17" in text
    assert "-" in text
