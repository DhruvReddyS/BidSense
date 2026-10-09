"""Deterministic Part 2 Level 1 elimination decisions.

Section 5.2 makes two kinds of failure disqualifying: a mandatory eligibility
CRITERION that the bidder does not meet, and a mandatory DOCUMENT the bidder
has not enclosed. Both eliminate, and the engine treats neither as a judgement
call -- but they are not the same decision, and this module records which one
fired.

Why the distinction is load-bearing rather than cosmetic:

  CURABILITY   A turnover shortfall cannot be fixed before the deadline; an
               absent covering letter usually can. Reporting both as one
               undifferentiated "eliminated" tells a vendor nothing about
               whether to withdraw or to file a document, and tells a
               committee nothing about whether a cure period applies.
  MEASUREMENT  The two grounds have very different accuracy. On the 19-bid
               evaluation set, criteria-ground elimination is exact -- no
               compliant bidder fails a criterion -- while document-ground
               elimination carries every false positive in the set, because
               matching a bid's enclosure list against a 39-to-47 item
               checklist is a harder problem than comparing two numbers.
               A single blended precision figure hid that completely: it
               reported 75% and implicated the rule engine, which was not at
               fault.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.compliance.models import GapReport, RequirementKind
from app.schemas.common import VendorStatus


class EliminationGround(StrEnum):
    """Which kind of mandatory failure caused the elimination."""

    #: A threshold or status rule failed: turnover, experience, capacity,
    #: blacklisting, liquidation. Not curable by filing a document.
    CRITERIA = "criteria"
    #: A named mandatory document was not found. Curable before the deadline.
    DOCUMENT = "document"


@dataclass(frozen=True)
class EliminationDecision:
    status: VendorStatus
    reason: str | None
    clause_ref: str | None
    source_page: int | None
    source_snippet: str | None
    #: None when the bidder was not eliminated. CRITERIA wins when both kinds
    #: of failure are present, because it is the one that cannot be cured and
    #: therefore the one the vendor needs to hear first.
    ground: EliminationGround | None = None


def decide(report: GapReport) -> EliminationDecision:
    """Turn a gap report into the auditable Level 1 status transition."""
    blockers = report.blocking_items
    if not blockers:
        return EliminationDecision(VendorStatus.PENDING, None, None, None, None)

    # Criteria failures lead, both in the ground and in the citation order
    # below. A bid that is short on turnover AND missing a form was previously
    # reported against whichever blocker happened to come first in document
    # order, so the stated reason was often the curable one -- which is how
    # reason accuracy sat at 58% while recall was perfect.
    criteria_blockers = [
        item for item in blockers if item.kind is not RequirementKind.DOCUMENT
    ]
    ground = (
        EliminationGround.CRITERIA if criteria_blockers else EliminationGround.DOCUMENT
    )
    blockers = criteria_blockers + [
        item for item in blockers if item.kind is RequirementKind.DOCUMENT
    ]

    parts: list[str] = []
    for item in blockers:
        provenance = item.notification_provenance
        clause = provenance.clause_ref if provenance else None
        prefix = f"Clause {clause}: " if clause else "Tender requirement: "
        parts.append(prefix + item.explanation)

    primary = blockers[0].notification_provenance
    return EliminationDecision(
        status=VendorStatus.ELIMINATED,
        reason="; ".join(parts),
        clause_ref=primary.clause_ref if primary else None,
        source_page=primary.source_page if primary else None,
        source_snippet=primary.source_snippet if primary else None,
        ground=ground,
    )
