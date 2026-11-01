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
# Comparing two systems on the SAME queries.
#
# The evaluators report point estimates with Wilson intervals, which says how
# precisely each arm is measured but nothing about whether the difference
# between two arms is real. On seventeen queries an improvement of one query is
# roughly six percentage points, and reporting that as a win would be
# indefensible -- so a comparison needs a paired test, not two intervals the
# reader is invited to eyeball.
#
# Both tests below are PAIRED, because the arms are run on identical queries.
# Treating them as independent samples throws away the pairing that makes a
# small evaluation set informative at all.
# --------------------------------------------------------------------------- #


def mcnemar(a_hits: list[bool], b_hits: list[bool]) -> dict:
    """Exact McNemar test on paired binary outcomes (hit@k, grounded, ...).

    Only the DISCORDANT pairs carry information: queries both arms get right,
    or both get wrong, say nothing about which arm is better. With b wins and c
    losses the exact two-sided p-value is the binomial probability of a split
    at least this lopsided under p = 0.5.

    The exact form rather than the chi-square approximation, because the
    approximation is unreliable below about 25 discordant pairs and this corpus
    produces far fewer.
    """
    if len(a_hits) != len(b_hits):
        raise ValueError("paired tests need equal-length outcome lists")
    b = sum(1 for x, y in zip(a_hits, b_hits) if y and not x)   # b improved
    c = sum(1 for x, y in zip(a_hits, b_hits) if x and not y)   # b regressed
    n = b + c
    if n == 0:
        return {"b": 0, "c": 0, "discordant": 0, "p_value": 1.0,
                "note": "no discordant pairs: the arms agree on every query"}

    # Two-sided exact binomial: P(X <= min(b,c)) + P(X >= max(b,c)) at p=0.5.
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    p = min(1.0, 2 * tail)
    return {
        "b": b, "c": c, "discordant": n, "p_value": p,
        "note": (
            f"{b} queries improved, {c} regressed, {len(a_hits) - n} unchanged"
        ),
    }


def bootstrap_diff(
    a: list[float], b: list[float], *, iterations: int = 10000, seed: int = 20260101
) -> dict:
    """Paired bootstrap CI for mean(b) - mean(a). For MRR and other means.

    Resamples QUERIES, not scores, so the pairing is preserved in every
    replicate. The seed is fixed and stated so the interval is reproducible:
    an unseeded bootstrap gives a slightly different answer each run, which is
    indistinguishable from fiddling with it.
    """
    import random

    if len(a) != len(b):
        raise ValueError("paired tests need equal-length score lists")
    n = len(a)
    if n == 0:
        return {"observed": 0.0, "low": 0.0, "high": 0.0, "p_value": 1.0}

    observed = (sum(b) / n) - (sum(a) / n)
    rng = random.Random(seed)
    diffs: list[float] = []
    for _ in range(iterations):
        picks = [rng.randrange(n) for _ in range(n)]
        diffs.append(
            sum(b[i] for i in picks) / n - sum(a[i] for i in picks) / n
        )
    diffs.sort()
    low = diffs[int(0.025 * iterations)]
    high = diffs[min(iterations - 1, int(0.975 * iterations))]
    # Fraction of replicates on the opposite side of zero from the observed
    # effect, doubled: a bootstrap analogue of a two-sided p-value.
    opposite = (
        sum(1 for d in diffs if d <= 0) if observed > 0
        else sum(1 for d in diffs if d >= 0)
    )
    return {
        "observed": observed,
        "low": low,
        "high": high,
        "p_value": min(1.0, 2 * opposite / iterations),
        "iterations": iterations,
        "seed": seed,
    }


def fmt_test(name: str, result: dict) -> str:
    """One line a reader can check, with the verdict spelled out."""
    p = result["p_value"]
    verdict = "significant at 0.05" if p < 0.05 else "NOT significant at 0.05"
    if "observed" in result:
        return (
            f"{name}: {result['observed']:+.3f} "
            f"[{result['low']:+.3f}, {result['high']:+.3f}] "
            f"p={p:.4f} -- {verdict}"
        )
    return (
        f"{name}: {result['b']} improved / {result['c']} regressed "
        f"(n={result['discordant']} discordant) p={p:.4f} -- {verdict}"
    )
