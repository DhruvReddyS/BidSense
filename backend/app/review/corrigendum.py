"""Apply typed amendments and propagate them through stored Level 1 decisions.

The substance now lives in `app.review.impact`, which handles the paths this
module used to refuse -- `eligibility_criteria` and `mandatory_documents`, the
only ones that actually change a verdict -- and which distinguishes an amendment
a bidder could respond to from one issued after the deadline. This remains the
entry point callers already use.
"""

from __future__ import annotations

from app.review.impact import CorrigendumImpact, apply


def apply_and_reevaluate(session, notification_row, corrigendum_row) -> bool:
    """Backwards-compatible shim: True when the amendment was fully applied.

    Callers that need to know WHAT the amendment did -- which bidders flipped,
    which have to be notified, whether a committee must sign it off -- should
    call `app.review.impact.apply` and read the returned CorrigendumImpact.
    A bare boolean cannot express "applied, and three bidders are now out".
    """
    return apply(session, notification_row, corrigendum_row).applied_changes != [] and \
        corrigendum_row.applied


def assess_only(session, notification_row, corrigendum_row) -> CorrigendumImpact:
    """Dry run: what would this amendment do? Writes nothing."""
    from app.review.impact import assess

    return assess(session, notification_row, corrigendum_row)
