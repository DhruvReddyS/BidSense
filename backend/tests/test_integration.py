"""Live round-trip against the real Postgres + Qdrant from docker compose.

Skipped automatically when the services aren't up, so the unit suite still runs
standalone. Run `docker compose up -d && python -m scripts.bootstrap` first.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.models import (
    EligibilityCriterionRow,
    MandatoryDocumentRow,
    TenderNotificationRow,
    User,
    VendorSubmissionRow,
    VendorTurnoverRow,
)
from app.db.session import engine, session_scope
from app.schemas.common import CriterionType, DocumentKind, UserRole, VendorStatus
from app.vector.qdrant import build_filter, collection_stats, get_client
from app.vector.schema import ChunkPayload, chunk_point_id


def _postgres_up() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _qdrant_up() -> bool:
    try:
        return bool(collection_stats().get("exists"))
    except Exception:
        return False


pg = pytest.mark.skipif(not _postgres_up(), reason="postgres not running")
qd = pytest.mark.skipif(not _qdrant_up(), reason="qdrant collection not bootstrapped")


@pytest.fixture
def tender():
    """Insert a notification + vendor, yield ids, then clean up via cascade."""
    with session_scope() as s:
        reviewer = User(email=f"rev-{uuid.uuid4()}@example.com", role=UserRole.REVIEWER)
        s.add(reviewer)
        s.flush()

        notif = TenderNotificationRow(
            tender_id=f"T-{uuid.uuid4().hex[:8]}",
            title="Supply and installation of network equipment",
            issuing_authority="Telangana State Technology Services",
            sector="IT services",
            submission_deadline=date(2026, 3, 15),
            emd_amount_raw="Rs. 2,00,000",
            emd_amount_inr=Decimal("200000.00"),
            evaluation_criteria=[{"factor": "Technical capability", "weightage_if_stated": None}],
            owner_user_id=reviewer.id,
        )
        notif.eligibility_criteria.append(
            EligibilityCriterionRow(
                criterion="Average annual turnover (last 3 FY)",
                type=CriterionType.NUMERIC,
                threshold_raw="₹5 Cr",
                threshold_amount_inr=Decimal("50000000.00"),
                unit="INR",
                clause_ref="4.2",
                source_page=14,
            )
        )
        notif.mandatory_documents.append(
            MandatoryDocumentRow(
                doc_name="GST Registration Certificate",
                aliases=["Goods & Services Tax Certificate", "GSTIN Certificate"],
                clause_ref="5.1",
            )
        )
        s.add(notif)
        s.flush()

        sub = VendorSubmissionRow(
            vendor_id="V-04",
            vendor_name="Delta Systems Pvt Ltd",
            notification_id=notif.id,
            years_in_business=8.5,
            status=VendorStatus.PENDING,
        )
        sub.turnover.append(
            VendorTurnoverRow(year=2023, amount_raw="4.2 Cr", amount_inr=Decimal("42000000.00"))
        )
        sub.turnover.append(
            VendorTurnoverRow(year=2024, amount_raw="as per annexure", amount_inr=None)
        )
        s.add(sub)
        s.flush()
        ids = (notif.id, sub.id, notif.tender_id)

    yield ids

    with session_scope() as s:
        s.execute(text("DELETE FROM tender_notifications WHERE id = :i"), {"i": str(ids[0])})


@pg
def test_notification_round_trip_with_cascade(tender):
    notif_id, sub_id, _ = tender
    with session_scope() as s:
        notif = s.get(TenderNotificationRow, notif_id)
        assert notif.eligibility_criteria[0].threshold_amount_inr == Decimal("50000000.00")
        assert notif.eligibility_criteria[0].clause_ref == "4.2"
        # JSONB half of the hybrid survives the round trip.
        assert notif.evaluation_criteria[0]["weightage_if_stated"] is None
        assert "GSTIN Certificate" in notif.mandatory_documents[0].aliases


@pg
def test_the_level_3_structured_query_actually_works(tender):
    """Section 5.4: 'which vendors have turnover above ₹5Cr' must be a real
    indexed SQL query over normalized rows -- this is the hybrid shape's whole
    justification."""
    _, sub_id, _ = tender
    with session_scope() as s:
        above = s.scalars(
            select(VendorSubmissionRow.vendor_name)
            .join(VendorTurnoverRow)
            .where(VendorTurnoverRow.amount_inr >= Decimal("50000000.00"))
        ).all()
        assert "Delta Systems Pvt Ltd" not in above  # 4.2 Cr < 5 Cr

        below = s.scalars(
            select(VendorSubmissionRow.vendor_name)
            .join(VendorTurnoverRow)
            .where(VendorTurnoverRow.amount_inr < Decimal("50000000.00"))
        ).all()
        assert "Delta Systems Pvt Ltd" in below


@pg
def test_unresolved_turnover_stays_null_not_zero(tender):
    """A NULL amount must not be swept into a `< threshold` comparison as 0 --
    that would auto-eliminate a vendor whose figure merely failed to parse."""
    _, sub_id, _ = tender
    with session_scope() as s:
        rows = s.scalars(
            select(VendorTurnoverRow).where(VendorTurnoverRow.submission_id == sub_id)
        ).all()
        unresolved = [r for r in rows if r.amount_inr is None]
        assert len(unresolved) == 1
        assert unresolved[0].amount_raw == "as per annexure"

        matched = s.scalars(
            select(VendorTurnoverRow.year).where(
                VendorTurnoverRow.submission_id == sub_id,
                VendorTurnoverRow.amount_inr < Decimal("50000000.00"),
            )
        ).all()
        assert matched == [2023]  # SQL NULL semantics exclude the unparsed row


@pg
def test_db_rejects_elimination_without_a_reason(tender):
    """Section 5.2, enforced at the database level, not just in Pydantic."""
    _, sub_id, _ = tender
    with pytest.raises(IntegrityError, match="eliminated_requires_reason"):
        with session_scope() as s:
            s.execute(
                text(
                    "UPDATE vendor_submissions SET status='eliminated' "
                    "WHERE id = :i"
                ),
                {"i": str(sub_id)},
            )


@pg
def test_enum_labels_match_the_pydantic_values():
    """Postgres labels must be the enum *values* ('eliminated'), so hand-written
    SQL in the Level 3 router matches instead of silently returning nothing."""
    with engine.connect() as conn:
        labels = set(
            conn.execute(
                text(
                    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid "
                    "WHERE t.typname='vendor_status'"
                )
            ).scalars()
        )
    assert labels == {s.value for s in VendorStatus}


@qd
def test_qdrant_scoped_retrieval_by_vendor_and_status(tender):
    """Section 7's metadata tagging: chunks must be filterable by vendor_id and
    status without touching the vector side."""
    _, sub_id, tender_id = tender
    client = get_client()
    sub_id_s = str(sub_id)

    points = [
        {
            "id": chunk_point_id(sub_id_s, i),
            "vector": [0.0] * settings.embedding_dim,
            "payload": ChunkPayload(
                doc_kind=DocumentKind.SUBMISSION,
                text=f"chunk {i}",
                tender_id=tender_id,
                vendor_id="V-04",
                submission_id=sub_id_s,
                status=VendorStatus.PENDING,
                chunk_index=i,
            ).to_qdrant(),
        }
        for i in range(3)
    ]
    client.upsert(settings.qdrant_collection, points=points, wait=True)

    try:
        found, _ = client.scroll(
            settings.qdrant_collection,
            scroll_filter=build_filter(vendor_id="V-04", statuses=[VendorStatus.PENDING]),
            limit=10,
        )
        assert len(found) == 3

        # Eliminated-only scope must not see a pending vendor's chunks.
        none_found, _ = client.scroll(
            settings.qdrant_collection,
            scroll_filter=build_filter(vendor_id="V-04", statuses=[VendorStatus.ELIMINATED]),
            limit=10,
        )
        assert none_found == []

        # Re-upserting the same chunk indexes overwrites rather than duplicates.
        client.upsert(settings.qdrant_collection, points=points, wait=True)
        again, _ = client.scroll(
            settings.qdrant_collection,
            scroll_filter=build_filter(submission_id=sub_id_s),
            limit=10,
        )
        assert len(again) == 3
    finally:
        client.delete(
            settings.qdrant_collection,
            points_selector=build_filter(submission_id=sub_id_s),
            wait=True,
        )


@qd
def test_retag_status_keeps_qdrant_in_sync(tender):
    """Status lives in two stores; retag_status is what stops scoped retrieval
    from answering off a stale tag after elimination."""
    from app.vector.qdrant import retag_status

    _, sub_id, tender_id = tender
    client = get_client()
    sub_id_s = str(sub_id)

    client.upsert(
        settings.qdrant_collection,
        points=[
            {
                "id": chunk_point_id(sub_id_s, 0),
                "vector": [0.0] * settings.embedding_dim,
                "payload": ChunkPayload(
                    doc_kind=DocumentKind.SUBMISSION,
                    text="technical approach",
                    submission_id=sub_id_s,
                    vendor_id="V-04",
                    status=VendorStatus.PENDING,
                ).to_qdrant(),
            }
        ],
        wait=True,
    )
    try:
        retag_status(sub_id_s, VendorStatus.ELIMINATED)
        found, _ = client.scroll(
            settings.qdrant_collection,
            scroll_filter=build_filter(
                submission_id=sub_id_s, statuses=[VendorStatus.ELIMINATED]
            ),
            limit=10,
        )
        assert len(found) == 1
        assert found[0].payload["status"] == "eliminated"
    finally:
        client.delete(
            settings.qdrant_collection,
            points_selector=build_filter(submission_id=sub_id_s),
            wait=True,
        )
