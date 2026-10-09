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
# Paired significance tests.
#
# These guard the claims in Section 10 that one arm beats another. The headline
# numbers are small-n, so the exact identities below are checked against
# hand-computed binomial values rather than against a library.
# --------------------------------------------------------------------------- #

from app.rag.stats import (                                      # noqa: E402
    bootstrap_mean_diff, fmt_delta_ci, fmt_p, fmt_sign_test,
    paired_counts, sign_test, significance_label,
)

import pytest                                                    # noqa: E402


def test_sign_test_matches_hand_computed_binomial():
    """p = 2 * 0.5^n for a clean sweep, which is the case the paper reports."""
    assert sign_test(6, 0) == pytest.approx(2 * 0.5**6)   # 0.03125
    assert sign_test(5, 0) == pytest.approx(0.0625)
    assert sign_test(10, 0) == pytest.approx(2 * 0.5**10)


def test_a_five_nil_sweep_does_not_clear_the_threshold():
    """The honest half of the chunking result, and the reason n=17 was expanded.

    Five improved and none regressed looks decisive and is not: the exact test
    puts it at 0.0625. Reporting that as a win would be overclaiming, so the
    label must say so.
    """
    p = sign_test(5, 0)
    assert p > 0.05
    assert "NOT significant" in significance_label(p)


def test_six_nil_does_clear_it():
    p = sign_test(6, 0)
    assert p < 0.05
    assert significance_label(p).startswith("significant")


def test_ties_carry_no_evidence():
    """A query both arms answer the same way says nothing about which is better."""
    assert sign_test(0, 0) == 1.0
    # Adding ties must not move the p-value: only discordant pairs count.
    assert sign_test(6, 0) == pytest.approx(2 * 0.5**6)
    assert "11 tied" in fmt_sign_test(6, 0, 11)


def test_a_symmetric_split_is_maximally_unconvincing():
    assert sign_test(3, 3) == 1.0
    assert sign_test(1, 1) == 1.0


def test_p_is_never_above_one():
    """The doubling in a two-sided test overshoots without the clamp."""
    for improved in range(0, 8):
        for regressed in range(0, 8):
            assert 0.0 <= sign_test(improved, regressed) <= 1.0


def test_direction_is_symmetric():
    """Swapping the arms must give the same p, only the reading changes."""
    assert sign_test(5, 2) == sign_test(2, 5)


def test_paired_counts_splits_improved_regressed_tied():
    before = [0.0, 0.0, 1.0, 1.0, 0.5]
    after = [1.0, 1.0, 1.0, 0.0, 0.5]
    assert paired_counts(before, after) == (2, 1, 2)


def test_paired_counts_honours_lower_is_better():
    """Latency and rank are metrics where down is the win."""
    assert paired_counts([2.0], [1.0], higher_is_better=False) == (1, 0, 0)


def test_unequal_lengths_are_rejected_rather_than_zipped():
    """zip() would silently truncate and quietly compare the wrong queries."""
    with pytest.raises(ValueError, match="equal-length"):
        paired_counts([1.0, 2.0, 3.0], [1.0, 2.0])


def test_bootstrap_interval_brackets_the_mean_and_excludes_zero():
    deltas = [0.0] * 8 + [0.5, 0.33, 1.0, 0.25, 0.5, 0.2, 0.75, 0.4, 0.6]
    mean, low, high, p = bootstrap_mean_diff(deltas)
    assert low < mean < high
    assert low > 0.0, "a consistently positive delta should exclude zero"
    assert p < 0.05


def test_bootstrap_is_reproducible_under_its_seed():
    """A reviewer re-running the suite must get the published interval."""
    deltas = [0.1, -0.2, 0.4, 0.0, 0.3, -0.1, 0.25]
    assert bootstrap_mean_diff(deltas) == bootstrap_mean_diff(deltas)


def test_a_different_seed_gives_a_similar_interval():
    """Reproducible must not mean seed-dependent conclusions."""
    deltas = [0.0] * 5 + [0.4, 0.5, 0.6, 0.45, 0.55, 0.5, 0.42]
    _, low_a, high_a, _ = bootstrap_mean_diff(deltas, seed=1)
    _, low_b, high_b, _ = bootstrap_mean_diff(deltas, seed=99)
    assert abs(low_a - low_b) < 0.1 and abs(high_a - high_b) < 0.1


def test_no_difference_is_not_reported_as_a_difference():
    mean, low, high, p = bootstrap_mean_diff([0.0] * 10)
    assert (mean, low, high) == (0.0, 0.0, 0.0)
    assert p == 1.0
    assert "NOT significant" in fmt_delta_ci([0.0] * 10)


def test_an_empty_comparison_is_inconclusive_not_significant():
    assert bootstrap_mean_diff([]) == (0.0, 0.0, 0.0, 1.0)


def test_p_value_does_not_claim_resolution_beyond_the_resampling():
    """0 out of 10000 resamples is p < 0.0001, not p = 0."""
    assert fmt_p(0.0, iterations=10000) == "p<0.0001"
    assert fmt_p(0.0312) == "p=0.0312"


def test_delta_format_shows_sign_interval_and_verdict():
    text = fmt_delta_ci([0.3] * 12)
    assert text.startswith("+0.300")
    assert "[" in text and "]" in text
    assert "significant" in text


# --------------------------------------------------------------------------- #
# Inter-annotator agreement.
# --------------------------------------------------------------------------- #

from app.rag.stats import cohen_kappa, fmt_kappa, kappa_band   # noqa: E402


def test_kappa_is_one_only_for_total_agreement():
    assert cohen_kappa(list("abab"), list("abab")) == 1.0


def test_kappa_strips_the_agreement_two_guessers_would_reach():
    """The whole point: 12 of 19 bids are eliminated, so two annotators who
    both just answer "eliminate" agree most of the time while sharing no
    judgement. Raw agreement rewards that; kappa must not."""
    a = ["eliminate"] * 12 + ["pass"] * 7
    b = ["eliminate"] * 19            # a rater who never says pass
    raw = sum(1 for x, y in zip(a, b) if x == y) / len(a)
    assert raw > 0.6, "raw agreement looks respectable"
    assert cohen_kappa(a, b) == 0.0, "kappa sees through it"


def test_kappa_matches_a_hand_computed_two_by_two():
    """po = 0.70, pe = 0.50 -> kappa = 0.40."""
    a = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    b = ["y"] * 20 + ["y"] * 5 + ["n"] * 10 + ["n"] * 15
    assert cohen_kappa(a, b) == pytest.approx(0.40)


def test_systematic_disagreement_goes_negative():
    """Worse than chance means the two read the definitions differently --
    a protocol bug, which the band must name rather than hide."""
    k = cohen_kappa(list("aabb"), list("bbaa"))
    assert k < 0
    assert "worse than chance" in kappa_band(k)


def test_a_single_category_used_throughout_is_not_silently_perfect():
    """Chance agreement is total here, so kappa is undefined; the fallback
    must not divide by zero and must not claim perfect reliability when the
    raters actually disagreed."""
    assert cohen_kappa(["x"] * 10, ["x"] * 10) == 1.0
    assert cohen_kappa(["x"] * 10, ["y"] * 10) == 0.0


def test_mismatched_unit_counts_are_rejected():
    with pytest.raises(ValueError, match="same units"):
        cohen_kappa(["a", "b", "c"], ["a", "b"])


def test_empty_annotation_is_zero_not_a_crash():
    assert cohen_kappa([], []) == 0.0
    assert fmt_kappa([], []) == "n/a"


def test_bands_cover_the_whole_range():
    for value in (-1.0, 0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0):
        assert kappa_band(value)


def test_format_reports_kappa_with_its_n_and_raw_agreement():
    """Reporting kappa alone hides that it moves ~0.17 per unit at n=12."""
    text = fmt_kappa(["criteria"] * 6 + ["document"] * 6,
                     ["criteria"] * 5 + ["document"] * 7)
    assert "kappa=" in text and "n=12" in text and "11/12" in text
