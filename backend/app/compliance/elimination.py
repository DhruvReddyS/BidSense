"""Deterministic Part 2 Level 1 elimination decisions."""

from __future__ import annotations

from dataclasses import dataclass

from app.compliance.models import GapReport
from app.schemas.common import VendorStatus


@dataclass(frozen=True)
class EliminationDecision:
    status: VendorStatus
    reason: str | None
    clause_ref: str | None
    source_page: int | None
    source_snippet: str | None


def decide(report: GapReport) -> EliminationDecision:
    """Turn a gap report into the auditable Level 1 status transition."""
    blockers = report.blocking_items
    if not blockers:
        return EliminationDecision(VendorStatus.PENDING, None, None, None, None)

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
    )
