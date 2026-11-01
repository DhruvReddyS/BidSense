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


# --------------------------------------------------------------------------- #
# Paired comparisons between two arms.
# --------------------------------------------------------------------------- #
from app.rag.stats import bootstrap_diff, fmt_test, mcnemar


def test_mcnemar_ignores_pairs_the_arms_agree_on():
    """Only discordant pairs carry information about which arm is better."""
    a = [True, True, False, False]
    b = [True, True, False, False]
    result = mcnemar(a, b)
    assert result["discordant"] == 0
    assert result["p_value"] == 1.0


def test_mcnemar_counts_improvements_and_regressions_separately():
    a = [False, False, True, True, True]
    b = [True, True, False, True, True]
    result = mcnemar(a, b)
    assert result["b"] == 2, "two queries improved"
    assert result["c"] == 1, "one regressed"


def test_a_one_query_improvement_is_not_significant():
    """The property that matters for this project's sample sizes.

    The chunking sweep moved hit@3 by exactly one query on n=17. Reporting that
    as a win would be indefensible, and this test pins that the machinery says
    so rather than leaving it to a reader's judgement.
    """
    a = [True] * 16 + [False]
    b = [True] * 17
    assert mcnemar(a, b)["p_value"] > 0.05


def test_a_large_consistent_improvement_is_significant():
    """Twelve improvements and no regressions must clear 0.05."""
    a = [False] * 12 + [True] * 5
    b = [True] * 17
    result = mcnemar(a, b)
    assert result["b"] == 12 and result["c"] == 0
    assert result["p_value"] < 0.05


def test_mcnemar_is_symmetric_in_magnitude():
    a = [False, True, True]
    b = [True, False, True]
    assert mcnemar(a, b)["p_value"] == mcnemar(b, a)["p_value"]


def test_bootstrap_is_reproducible_and_brackets_the_observed_effect():
    """An unseeded bootstrap is indistinguishable from fiddling with it."""
    a = [0.0, 0.5, 0.2, 1.0, 0.3]
    b = [1.0, 1.0, 0.5, 1.0, 0.8]
    first = bootstrap_diff(a, b, iterations=2000)
    second = bootstrap_diff(a, b, iterations=2000)
    assert first == second
    assert first["low"] <= first["observed"] <= first["high"]
    assert first["observed"] > 0


def test_bootstrap_on_identical_arms_finds_no_effect():
    scores = [0.1, 0.4, 0.9, 0.2]
    result = bootstrap_diff(scores, scores, iterations=1000)
    assert result["observed"] == 0.0
    assert result["p_value"] == 1.0


def test_paired_tests_reject_mismatched_lengths():
    import pytest

    with pytest.raises(ValueError):
        mcnemar([True], [True, False])
    with pytest.raises(ValueError):
        bootstrap_diff([0.1], [0.1, 0.2])


def test_fmt_test_states_the_verdict():
    line = fmt_test("hit@5", mcnemar([False] * 12 + [True] * 5, [True] * 17))
    assert "significant at 0.05" in line
    assert "NOT" not in line
