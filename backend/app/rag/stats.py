"""Interval estimates for small evaluation sets.

Every accuracy figure in this project rests on tens of observations, not
thousands. A bare "100%" from seventeen trials and a bare "100%" from two
thousand are different claims, and reporting them identically is the single
easiest way to overstate a result -- so the evaluators quote an interval beside
every proportion.

Wilson rather than the textbook normal approximation, because the normal
interval is worst exactly where this project lives: at n below ~40 and at
proportions near 0 or 1, where it produces bounds below zero or above one and
collapses to zero width at p = 1. Wilson stays inside [0, 1] and keeps a
sensible width at the extremes, which is why 17/17 reports a lower bound near
80% instead of claiming certainty.
"""

from __future__ import annotations

import math
import random

#: 1.959964 ~ the two-sided 95% normal quantile.
Z_95 = 1.959963984540054


def wilson(successes: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion."""
    if total <= 0:
        return (0.0, 1.0)
    p = successes / total
    denominator = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denominator
    half = (z / denominator) * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2))
    return (max(0.0, centre - half), min(1.0, centre + half))


def fmt_pct_ci(successes: int, total: int) -> str:
    """"76.5% [50.1-91.3%, n=17]" -- the figure and its honest width."""
    if total <= 0:
        return "n/a"
    low, high = wilson(successes, total)
    return (
        f"{successes / total * 100:.1f}% "
        f"[{low * 100:.1f}-{high * 100:.1f}%, n={total}]"
    )


# --------------------------------------------------------------------------- #
# Paired comparisons.
#
# An interval says how precisely one arm was measured. It does not say whether
# two arms differ -- and because every arm here is scored on *the same* labelled
# queries, the two interval overlap is the wrong test anyway: it throws away the
# pairing that makes the comparison sensitive. A query that both arms get right
# carries no information about which is better; only the queries they disagree
# on do. These functions test the disagreements.
#
# No scipy: it is a 300MB dependency for two closed forms, and the exact
# binomial below is a dozen lines of math.comb.
# --------------------------------------------------------------------------- #


def sign_test(improved: int, regressed: int) -> float:
    """Exact two-sided p for a paired win/loss count (McNemar's exact test).

    Under the null hypothesis that the two arms are equally good, each query
    they disagree on is a coin flip, so the number of wins is Binomial(n, 0.5)
    where n counts only the discordant queries. Ties are excluded rather than
    split: a query both arms answer identically is evidence about the queries,
    not about the arms.

    Exact rather than the normal approximation because n is small -- at the
    n = 5 and n = 6 this project actually observes, the approximation is simply
    wrong. 6-0 gives p = 2 x 0.5^6 = 0.0312 and 5-0 gives p = 0.0625: the second
    is the more interesting number, because a clean five-nil sweep still does
    not clear 0.05, and reporting it as a win would be overclaiming.
    """
    n = improved + regressed
    if n == 0:
        return 1.0                      # no disagreement, no evidence
    tail = sum(math.comb(n, k) for k in range(min(improved, regressed) + 1))
    return min(1.0, 2.0 * tail / 2**n)


def bootstrap_mean_diff(
    deltas: list[float],
    *,
    iterations: int = 10000,
    seed: int = 20260907,
    z: float = Z_95,
) -> tuple[float, float, float, float]:
    """Mean paired difference, its 95% percentile CI, and a two-sided p.

    For a continuous per-query metric such as MRR the sign test discards the
    magnitudes, so resample the paired differences instead. Percentile bootstrap
    rather than a t-interval because 17 to 39 per-query deltas are nowhere near
    normal -- MRR deltas are a spike at zero with a few large jumps.

    The p-value is the fraction of resampled means that fall on the other side
    of zero, doubled. It cannot resolve below 1/iterations, so a p that comes
    back as 0.0 is reported as that floor by `fmt_delta_ci` rather than as
    certainty. `seed` is fixed so a reviewer re-running the suite gets the same
    interval; it is recorded in the evaluation manifest.

    Returns (mean, low, high, p).
    """
    del z                               # percentile method needs no quantile
    n = len(deltas)
    if n == 0:
        return (0.0, 0.0, 0.0, 1.0)
    mean = sum(deltas) / n
    if all(d == 0.0 for d in deltas):
        return (0.0, 0.0, 0.0, 1.0)

    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(iterations):
        total = 0.0
        for _ in range(n):
            total += deltas[rng.randrange(n)]
        means.append(total / n)
    means.sort()

    low = means[int(0.025 * iterations)]
    high = means[min(iterations - 1, int(0.975 * iterations))]
    at_or_below = sum(1 for m in means if m <= 0.0) / iterations
    at_or_above = sum(1 for m in means if m >= 0.0) / iterations
    p = min(1.0, 2.0 * min(at_or_below, at_or_above))
    return (mean, low, high, p)


def paired_counts(
    before: list[float], after: list[float], *, higher_is_better: bool = True
) -> tuple[int, int, int]:
    """(improved, regressed, tied) over per-query scores from the same queries."""
    if len(before) != len(after):
        raise ValueError(
            f"paired comparison needs equal-length scores, got "
            f"{len(before)} and {len(after)}"
        )
    improved = regressed = tied = 0
    for b, a in zip(before, after):
        if a == b:
            tied += 1
        elif (a > b) == higher_is_better:
            improved += 1
        else:
            regressed += 1
    return (improved, regressed, tied)


def significance_label(p: float, alpha: float = 0.05) -> str:
    """"significant" / "not significant", stated rather than left to the reader."""
    return f"{'significant' if p < alpha else 'NOT significant'} at {alpha:g}"


def fmt_p(p: float, iterations: int | None = None) -> str:
    """Format a p-value without claiming more resolution than it has."""
    if iterations and p < 1.0 / iterations:
        return f"p<{1.0 / iterations:.4f}"
    return f"p={p:.4f}"


def fmt_sign_test(improved: int, regressed: int, tied: int = 0) -> str:
    """"6 improved / 0 regressed / 11 tied, p=0.0312, significant at 0.05"."""
    p = sign_test(improved, regressed)
    tie_text = f" / {tied} tied" if tied else ""
    return (
        f"{improved} improved / {regressed} regressed{tie_text}, "
        f"{fmt_p(p)}, {significance_label(p)}"
    )


def fmt_delta_ci(
    deltas: list[float], *, iterations: int = 10000, seed: int = 20260907
) -> str:
    """"+0.353 [+0.147, +0.574], p<0.0001, significant at 0.05"."""
    mean, low, high, p = bootstrap_mean_diff(
        deltas, iterations=iterations, seed=seed
    )
    return (
        f"{mean:+.3f} [{low:+.3f}, {high:+.3f}], "
        f"{fmt_p(p, iterations)}, {significance_label(p)}"
    )


# --------------------------------------------------------------------------- #
# Inter-annotator agreement.
#
# Every number in Section 10 is measured against labels, so the labels are part
# of the method and need their own reliability figure. Raw agreement is not it:
# on a set where 12 of 19 bids are eliminated, two annotators who both just
# guess "eliminate" agree 63% of the time while sharing no judgement at all.
# Cohen's kappa subtracts exactly that chance agreement.
#
# The one thing kappa cannot do is rate a single annotator against themselves.
# A second pass by the same person reproduces their own reading of an ambiguous
# clause, so it measures consistency and reports it as reliability. The second
# rater has to be a different person; scripts/double_label.py prepares the sheet
# for one.
# --------------------------------------------------------------------------- #


def cohen_kappa(rater_a: list[str], rater_b: list[str]) -> float:
    """Chance-corrected agreement between two annotators on the same units.

    kappa = (observed - expected) / (1 - expected), where `expected` is the
    agreement two annotators would reach by chance given how often each uses
    each category.

    1.0 is perfect agreement, 0.0 is chance, and negative values mean the two
    disagree more than chance -- usually a sign the label definitions are read
    differently, which is a protocol bug rather than a bad annotator.
    """
    if len(rater_a) != len(rater_b):
        raise ValueError(
            f"kappa needs the same units from both raters, got "
            f"{len(rater_a)} and {len(rater_b)}"
        )
    n = len(rater_a)
    if n == 0:
        return 0.0

    observed = sum(1 for a, b in zip(rater_a, rater_b) if a == b) / n
    categories = set(rater_a) | set(rater_b)
    expected = sum(
        (rater_a.count(c) / n) * (rater_b.count(c) / n) for c in categories
    )
    if expected >= 1.0:
        # Both raters used a single category throughout. Chance agreement is
        # total, so kappa is undefined; report the honest reading rather than
        # dividing by zero.
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1 - expected)


#: Landis & Koch (1977) bands. Widely used and widely criticised as arbitrary --
#: quoted here so a number is not left to the reader's taste, not because the
#: cutoffs are principled.
KAPPA_BANDS = (
    (0.81, "almost perfect"),
    (0.61, "substantial"),
    (0.41, "moderate"),
    (0.21, "fair"),
    (0.01, "slight"),
    (float("-inf"), "poor (worse than chance)"),
)


def kappa_band(kappa: float) -> str:
    for floor, label in KAPPA_BANDS:
        if kappa >= floor:
            return label
    return "poor (worse than chance)"


def fmt_kappa(rater_a: list[str], rater_b: list[str]) -> str:
    """"kappa=0.85 (almost perfect), 18/19 agreed, n=19"."""
    if len(rater_a) != len(rater_b) or not rater_a:
        return "n/a"
    k = cohen_kappa(rater_a, rater_b)
    agreed = sum(1 for a, b in zip(rater_a, rater_b) if a == b)
    return (
        f"kappa={k:.2f} ({kappa_band(k)}), "
        f"{agreed}/{len(rater_a)} agreed, n={len(rater_a)}"
    )
