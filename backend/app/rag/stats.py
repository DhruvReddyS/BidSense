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
