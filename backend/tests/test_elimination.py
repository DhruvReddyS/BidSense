from app.compliance.elimination import decide
from app.compliance.models import (
    CheckStatus,
    GapItem,
    GapReport,
    RequirementKind,
    ScorePreview,
    Severity,
)
from app.schemas.common import Provenance, VendorStatus


def report(*items):
    return GapReport(
        tender_id="T-1",
        vendor_id="V-1",
        items=list(items),
        score_preview=ScorePreview(available=False),
    )


def test_level1_passes_a_pool_member_to_pending():
    decision = decide(report())
    assert decision.status is VendorStatus.PENDING
    assert decision.reason is None


def test_level1_elimination_keeps_clause_and_failed_value():
    item = GapItem(
        requirement="Average annual turnover",
        kind=RequirementKind.NUMERIC,
        status=CheckStatus.MISSING,
        severity=Severity.DISQUALIFYING,
        required_value="₹5 crore",
        found_value="₹2.1 crore",
        explanation="Your turnover is ₹2.1 crore, below the required ₹5 crore.",
        notification_provenance=Provenance(
            clause_ref="4.2", source_page=7, source_snippet="Minimum turnover ₹5 crore"
        ),
    )
    decision = decide(report(item))
    assert decision.status is VendorStatus.ELIMINATED
    assert decision.clause_ref == "4.2"
    assert decision.source_page == 7
    assert "₹2.1 crore" in decision.reason
    assert "Clause 4.2" in decision.reason
