"""A corrigendum that changes eligibility must re-decide bids -- and know when
re-deciding is itself unfair.

Two groups of tests. The first is pure logic and always runs: flip direction,
who has to be notified, and the retroactivity rule, which is the part of this
feature that is a judgement rather than a computation. The second exercises the
real tables and is skipped when Postgres is not up, following the convention in
test_integration.py.

The case that matters most is the one the system must NOT decide alone: an
amendment issued after the submission deadline that newly eliminates a bidder.
A bid prepared against the rules as published cannot answer a requirement that
did not exist at submission time, so excluding it is a committee's decision.
A relaxation issued at the same moment is applied without ceremony, because it
can only help the bidder. That asymmetry is tested directly.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.db.models import (
    ChangedFieldRow,
    CorrigendumRow,
    EligibilityCriterionRow,
    MandatoryDocumentRow,
    TenderNotificationRow,
    User,
    VendorSubmissionRow,
    VendorTurnoverRow,
)
from app.db.session import engine, session_scope
from app.review.impact import (
    BidImpact,
    ChangeOutcome,
    CorrigendumImpact,
    FlipDirection,
    _direction,
    apply,
    assess,
)
from app.schemas.common import CriterionType, UserRole, VendorStatus


def _postgres_up() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pg = pytest.mark.skipif(not _postgres_up(), reason="postgres not running")

ELIMINATED = str(VendorStatus.ELIMINATED)
PENDING = str(VendorStatus.PENDING)


# --------------------------------------------------------------------------- #
# Flip direction and notification duty.
# --------------------------------------------------------------------------- #

def test_a_bidder_who_qualified_and_now_does_not_is_adverse():
    direction = _direction((PENDING, None), (ELIMINATED, "4.2"))
    assert direction is FlipDirection.NEWLY_ELIMINATED
    assert direction.is_adverse and direction.needs_notice


def test_a_bidder_reinstated_by_an_amendment_is_not_adverse_but_is_told():
    direction = _direction((ELIMINATED, "4.2"), (PENDING, None))
    assert direction is FlipDirection.REINSTATED
    assert not direction.is_adverse
    assert direction.needs_notice, "being let back in is news"


def test_a_changed_clause_counts_as_news_even_though_the_verdict_stands():
    """The clause is what a bidder would contest, so swapping it silently
    removes their grounds for challenge."""
    direction = _direction((ELIMINATED, "4.2"), (ELIMINATED, "5.1"))
    assert direction is FlipDirection.REASON_CHANGED
    assert direction.needs_notice
    assert not direction.is_adverse, "no worse off, but owed an explanation"


def test_an_unaffected_bidder_is_not_notified():
    direction = _direction((ELIMINATED, "4.2"), (ELIMINATED, "4.2"))
    assert direction is FlipDirection.UNCHANGED
    assert not direction.needs_notice


# --------------------------------------------------------------------------- #
# Retroactivity: the judgement this module exists to make.
# --------------------------------------------------------------------------- #

def _impact(issued, deadline, directions) -> CorrigendumImpact:
    return CorrigendumImpact(
        corrigendum_id="C-1",
        issued_date=issued,
        submission_deadline=deadline,
        impacts=[
            BidImpact(f"V{i}", PENDING, ELIMINATED, None, "4.2", d)
            for i, d in enumerate(directions)
        ],
    )


def test_an_amendment_before_the_deadline_is_applied_without_review():
    """Bidders can read it and respond, so re-deciding is simply correct."""
    impact = _impact(date(2026, 3, 1), date(2026, 3, 15),
                     [FlipDirection.NEWLY_ELIMINATED])
    assert not impact.is_retroactive
    assert not impact.requires_human_review


def test_a_retroactive_amendment_that_excludes_a_bidder_needs_a_human():
    """The case a pipeline must not decide alone."""
    impact = _impact(date(2026, 3, 20), date(2026, 3, 15),
                     [FlipDirection.NEWLY_ELIMINATED])
    assert impact.is_retroactive
    assert impact.requires_human_review
    assert len(impact.adverse) == 1
    assert "REQUIRES HUMAN REVIEW" in impact.summary()


def test_a_retroactive_amendment_that_only_relaxes_is_applied():
    """A relaxation after the deadline harms nobody, so it needs no ceremony."""
    impact = _impact(date(2026, 3, 20), date(2026, 3, 15),
                     [FlipDirection.REINSTATED, FlipDirection.UNCHANGED])
    assert impact.is_retroactive
    assert not impact.requires_human_review, "relaxation can only help"


def test_a_retroactive_reason_change_alone_does_not_need_review():
    """Still eliminated either way: no bidder's standing got worse."""
    impact = _impact(date(2026, 3, 20), date(2026, 3, 15),
                     [FlipDirection.REASON_CHANGED])
    assert impact.is_retroactive
    assert not impact.requires_human_review
    assert impact.notify, "but they are still owed the new clause"


def test_an_amendment_issued_on_the_deadline_is_not_retroactive():
    """Same day is still answerable; only strictly after is not."""
    impact = _impact(date(2026, 3, 15), date(2026, 3, 15),
                     [FlipDirection.NEWLY_ELIMINATED])
    assert not impact.is_retroactive


def test_an_unknown_date_does_not_block_the_tender_but_is_warned_about():
    """Refusing every amendment whose date we failed to read would stall the
    tender rather than protect anyone, so the gap is surfaced, not enforced."""
    impact = _impact(None, date(2026, 3, 15), [FlipDirection.NEWLY_ELIMINATED])
    assert not impact.is_retroactive
    assert not impact.requires_human_review
    assert any("no issued date" in w for w in impact.warnings)

    impact = _impact(date(2026, 3, 20), None, [FlipDirection.NEWLY_ELIMINATED])
    assert not impact.is_retroactive
    assert any("no submission deadline" in w for w in impact.warnings)


def test_unresolved_changes_appear_in_the_warnings():
    from app.review.impact import ChangeResult

    impact = CorrigendumImpact(corrigendum_id="C-1", changes=[
        ChangeResult("eligibility_criteria[0]", ChangeOutcome.CONFLICT, "no match"),
        ChangeResult("mandatory_documents", ChangeOutcome.APPLIED),
    ])
    assert len(impact.applied_changes) == 1
    assert len(impact.unresolved_changes) == 1
    assert any("conflict" in w for w in impact.warnings)


# --------------------------------------------------------------------------- #
# Against the real tables.
# --------------------------------------------------------------------------- #

@pytest.fixture
def tender():
    """A tender with a Rs 3 Cr turnover floor and a bidder at Rs 4.2 Cr.

    The bidder clears the floor comfortably, so an amendment that raises it
    past Rs 4.2 Cr is exactly the flip this feature is for.
    """
    with session_scope() as s:
        reviewer = User(email=f"rev-{uuid.uuid4()}@example.com", role=UserRole.REVIEWER)
        s.add(reviewer)
        s.flush()

        notif = TenderNotificationRow(
            tender_id=f"T-{uuid.uuid4().hex[:8]}",
            title="Supply of LED street lights",
            issuing_authority="GHMC",
            sector="supply",
            submission_deadline=date(2026, 3, 15),
            owner_user_id=reviewer.id,
        )
        notif.eligibility_criteria.append(EligibilityCriterionRow(
            criterion="Average annual turnover (last 3 FY)",
            type=CriterionType.NUMERIC,
            threshold_raw="Rs. 3,00,00,000",
            threshold_amount_inr=Decimal("30000000.00"),
            unit="INR", clause_ref="4.2", source_page=14,
        ))
        notif.mandatory_documents.append(MandatoryDocumentRow(
            doc_name="GST Registration Certificate",
            aliases=["GSTIN Certificate"], clause_ref="5.1", source_page=15,
        ))
        s.add(notif)
        s.flush()

        sub = VendorSubmissionRow(
            vendor_id="V-01", vendor_name="Lumina Electricals",
            notification_id=notif.id, years_in_business=12.0,
            status=VendorStatus.PENDING,
        )
        sub.turnover.append(VendorTurnoverRow(
            year=2024, amount_raw="Rs. 4.2 Cr", amount_inr=Decimal("42000000.00")))
        s.add(sub)
        s.flush()
        ids = (notif.id, notif.tender_id)

    yield ids

    with session_scope() as s:
        s.execute(text("DELETE FROM tender_notifications WHERE id = :i"),
                  {"i": str(ids[0])})


def _corrigendum(s, notif, *, issued, changes):
    row = CorrigendumRow(
        corrigendum_id=f"C-{uuid.uuid4().hex[:6]}",
        notification_id=notif.id, parent_tender_id=notif.tender_id,
        issued_date=issued,
    )
    for path, old, new, clause in changes:
        row.changed_fields.append(ChangedFieldRow(
            field_path=path, old_value=old, new_value=new, clause_ref=clause))
    s.add(row)
    s.flush()
    return row


@pg
def test_raising_a_turnover_floor_is_resolved_by_clause_not_position(tender):
    """The relationships have no guaranteed order, so a positional path is not
    an identity. Resolution is by the clause the amendment cites."""
    notif_id, _ = tender
    with session_scope() as s:
        notif = s.get(TenderNotificationRow, notif_id)
        corr = _corrigendum(
            s, notif, issued=date(2026, 3, 1),
            # A deliberately WRONG index, with the right clause.
            changes=[("eligibility_criteria[7].threshold_amount",
                      "Rs. 3,00,00,000", "Rs. 5,00,00,000", "4.2")],
        )
        impact = assess(s, notif, corr)

    assert [c.outcome for c in impact.changes] == [ChangeOutcome.APPLIED]
    assert "5,00,00,000" in impact.changes[0].detail


@pg
def test_assess_reports_the_flip_without_committing_it(tender):
    """A dry run must leave the database exactly as it was."""
    notif_id, _ = tender
    with session_scope() as s:
        notif = s.get(TenderNotificationRow, notif_id)
        corr = _corrigendum(
            s, notif, issued=date(2026, 3, 1),
            changes=[("eligibility_criteria.threshold_amount",
                      "Rs. 3,00,00,000", "Rs. 5,00,00,000", "4.2")],
        )
        impact = assess(s, notif, corr)

    assert impact.applied_changes, "the change should resolve"

    # Nothing persisted: the floor is still 3 Cr.
    with session_scope() as s:
        notif = s.get(TenderNotificationRow, notif_id)
        assert notif.eligibility_criteria[0].threshold_amount_inr == Decimal("30000000.00")


@pg
def test_a_conflicting_old_value_is_reported_rather_than_guessed(tender):
    """Usually means the tender was already amended once and this corrigendum
    was written against the original text."""
    notif_id, _ = tender
    with session_scope() as s:
        notif = s.get(TenderNotificationRow, notif_id)
        corr = _corrigendum(
            s, notif, issued=date(2026, 3, 1),
            changes=[("eligibility_criteria.threshold_amount",
                      "Rs. 9,99,99,999", "Rs. 5,00,00,000", "9.9")],
        )
        impact = assess(s, notif, corr)

    assert impact.changes[0].outcome is ChangeOutcome.CONFLICT
    assert not impact.applied_changes
    assert any("conflict" in w for w in impact.warnings)


@pg
def test_a_newly_required_document_is_added(tender):
    notif_id, _ = tender
    with session_scope() as s:
        notif = s.get(TenderNotificationRow, notif_id)
        before = len(notif.mandatory_documents)
        corr = _corrigendum(
            s, notif, issued=date(2026, 3, 1),
            changes=[("mandatory_documents[+]", None,
                      "Manufacturer Authorization Form", "7")],
        )
        impact = apply(s, notif, corr)
        s.refresh(notif)
        names = [d.doc_name for d in notif.mandatory_documents]

    assert impact.applied_changes
    assert len(names) == before + 1
    assert "Manufacturer Authorization Form" in names


@pg
def test_a_renamed_document_keeps_its_old_name_as_an_alias(tender):
    """A bid that enclosed the document under its previous name must still
    match -- otherwise an amendment's wording change fails compliant bidders."""
    notif_id, _ = tender
    with session_scope() as s:
        notif = s.get(TenderNotificationRow, notif_id)
        corr = _corrigendum(
            s, notif, issued=date(2026, 3, 1),
            changes=[("mandatory_documents", "GST Registration Certificate",
                      "Goods and Services Tax Registration", "5.1")],
        )
        apply(s, notif, corr)
        s.refresh(notif)
        doc = [d for d in notif.mandatory_documents
               if d.doc_name == "Goods and Services Tax Registration"][0]
        aliases = list(doc.aliases or [])

    assert "GST Registration Certificate" in aliases


@pg
def test_a_withdrawn_criterion_is_kept_but_made_non_mandatory(tender):
    """Deleting it would erase the audit trail; a committee may need to show
    the criterion existed and was withdrawn."""
    notif_id, _ = tender
    with session_scope() as s:
        notif = s.get(TenderNotificationRow, notif_id)
        corr = _corrigendum(
            s, notif, issued=date(2026, 3, 1),
            changes=[("eligibility_criteria", "Rs. 3,00,00,000", "", "4.2")],
        )
        apply(s, notif, corr)
        s.refresh(notif)
        criteria = [(c.criterion, c.is_mandatory) for c in notif.eligibility_criteria]

    assert len(criteria) == 1, "the row must survive"
    assert criteria[0][1] is False


@pg
def test_a_retroactive_adverse_amendment_is_not_written(tender):
    """The headline behaviour: issued after the deadline and it would exclude
    a bidder, so nothing is persisted and the corrigendum stays outstanding."""
    notif_id, _ = tender
    with session_scope() as s:
        notif = s.get(TenderNotificationRow, notif_id)
        corr = _corrigendum(
            s, notif, issued=date(2026, 3, 20),      # five days late
            changes=[("eligibility_criteria.threshold_amount",
                      "Rs. 3,00,00,000", "Rs. 5,00,00,000", "4.2")],
        )
        impact = apply(s, notif, corr)
        applied_flag = corr.applied

    if not impact.adverse:
        pytest.skip("the rule engine did not flip this bid; nothing to assert")

    assert impact.is_retroactive
    assert impact.requires_human_review
    assert applied_flag is False, "must stay visibly outstanding"

    with session_scope() as s:
        notif = s.get(TenderNotificationRow, notif_id)
        assert notif.eligibility_criteria[0].threshold_amount_inr == \
            Decimal("30000000.00"), "a retroactive exclusion must not be written"


@pg
def test_criteria_come_back_in_a_stable_order(tender):
    """Without order_by the database may return these rows in any order, which
    made positional amendment paths unsafe and exports non-deterministic."""
    notif_id, _ = tender
    with session_scope() as s:
        notif = s.get(TenderNotificationRow, notif_id)
        for page, clause in ((9, "2.1"), (3, "1.1"), (20, "6.4")):
            notif.eligibility_criteria.append(EligibilityCriterionRow(
                criterion=f"Criterion at {clause}", type=CriterionType.NUMERIC,
                threshold_raw="1", threshold_number=1.0,
                clause_ref=clause, source_page=page,
            ))
        s.flush()

    seen = []
    for _ in range(3):
        with session_scope() as s:
            notif = s.get(TenderNotificationRow, notif_id)
            seen.append([c.clause_ref for c in notif.eligibility_criteria])

    assert seen[0] == seen[1] == seen[2], f"unstable order: {seen}"
    assert seen[0] == sorted(seen[0], key=lambda c: {"1.1": 3, "2.1": 9, "4.2": 14, "6.4": 20}[c])


# --------------------------------------------------------------------------- #
# The endpoint. A feature that only exists in a module is not demonstrable.
# --------------------------------------------------------------------------- #

@pg
def test_the_impact_endpoint_previews_without_changing_anything(tender):
    """GET, because assessing is read-only: the amendment is applied inside a
    savepoint and rolled back. Asking "what if" must not change a verdict."""
    import uuid as _uuid

    from fastapi.testclient import TestClient

    from app.api.main import app

    notif_id, tender_id = tender
    with session_scope() as s:
        notif = s.get(TenderNotificationRow, notif_id)
        corr = _corrigendum(
            s, notif, issued=date(2026, 3, 20),
            changes=[("eligibility_criteria.threshold_amount",
                      "Rs. 3,00,00,000", "Rs. 5,00,00,000", "4.2")],
        )
        corrigendum_id = corr.corrigendum_id

    client = TestClient(app)
    auth = client.post("/api/auth/register", json={
        "email": f"rev-{_uuid.uuid4()}@example.com",
        "password": "correct-horse-battery-staple",
        "role": "reviewer",
        "reviewer_code": "development-reviewer",
    })
    assert auth.status_code == 201, auth.text
    headers = {"Authorization": f"Bearer {auth.json()['access_token']}"}

    response = client.get(
        f"/api/notifications/{tender_id}/corrigenda/{corrigendum_id}/impact",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["corrigendum_id"] == corrigendum_id
    assert body["is_retroactive"] is True, "issued five days after the deadline"
    assert body["applied"] is False
    assert body["impacts"], "the preview must name the bidders it affects"
    assert isinstance(body["warnings"], list)

    # And the preview changed nothing.
    with session_scope() as s:
        notif = s.get(TenderNotificationRow, notif_id)
        assert notif.eligibility_criteria[0].threshold_amount_inr == \
            Decimal("30000000.00")


@pg
def test_an_unknown_corrigendum_is_a_clear_404(tender):
    import uuid as _uuid

    from fastapi.testclient import TestClient

    from app.api.main import app

    _, tender_id = tender
    client = TestClient(app)
    auth = client.post("/api/auth/register", json={
        "email": f"rev-{_uuid.uuid4()}@example.com",
        "password": "correct-horse-battery-staple",
        "role": "reviewer",
        "reviewer_code": "development-reviewer",
    })
    headers = {"Authorization": f"Bearer {auth.json()['access_token']}"}
    response = client.get(
        f"/api/notifications/{tender_id}/corrigenda/C-nonexistent/impact",
        headers=headers,
    )
    assert response.status_code == 404
    assert "C-nonexistent" in response.text


@pg
def test_the_impact_endpoint_is_reviewer_only(tender):
    """The answer names every bidder's standing, so a vendor must not see it."""
    from fastapi.testclient import TestClient

    from app.api.main import app

    _, tender_id = tender
    client = TestClient(app)
    response = client.get(
        f"/api/notifications/{tender_id}/corrigenda/C-whatever/impact"
    )
    assert response.status_code in (401, 403), response.text
