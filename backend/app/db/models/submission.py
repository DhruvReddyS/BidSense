"""Vendor submission tables.

Normalized children (turnover, certifications, documents, past_projects) because
Level 1 elimination (5.2) and the Level 3 structured router (5.4) query them
directly -- "which vendors have turnover above ₹5Cr" should be an indexed join,
not a JSONB path scan.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, ProvenanceColumns, Timestamps, UUIDPrimaryKey
from app.schemas.common import VendorStatus

vendor_status_enum = SAEnum(
    VendorStatus,
    name="vendor_status",
    native_enum=True,
    create_type=True,
    values_callable=lambda enum: [m.value for m in enum],
)
Money = Numeric(18, 2)


class VendorSubmissionRow(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "vendor_submissions"
    __table_args__ = (
        UniqueConstraint("notification_id", "vendor_id", name="uq_vendor_per_tender"),
        # Section 5.2: an eliminated vendor without a stated reason is not a
        # defensible decision. Enforced in the DB, not just in Pydantic.
        CheckConstraint(
            "(status <> 'eliminated') OR (elimination_reason IS NOT NULL)",
            name="eliminated_requires_reason",
        ),
        Index("ix_vendor_submissions_status", "notification_id", "status"),
    )

    vendor_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    vendor_name: Mapped[str] = mapped_column(Text, nullable=False)
    notification_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tender_notifications.id", ondelete="CASCADE"), index=True
    )

    years_in_business: Mapped[float | None] = mapped_column(Float)
    pricing_summary: Mapped[str | None] = mapped_column(Text)
    quoted_price_raw: Mapped[str | None] = mapped_column(Text)
    quoted_price_inr: Mapped[Decimal | None] = mapped_column(Money)
    # Financial-capacity floors that large tenders test separately from turnover.
    liquid_assets_raw: Mapped[str | None] = mapped_column(Text)
    liquid_assets_inr: Mapped[Decimal | None] = mapped_column(Money)
    net_worth_raw: Mapped[str | None] = mapped_column(Text)
    net_worth_inr: Mapped[Decimal | None] = mapped_column(Money)

    # Section 5.8 -- hard-fail in the rule engine. Set by a reviewer from an
    # official list, or derived from the bidder's own disclosure below.
    is_blacklisted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    # The bidder's own words, kept so an elimination can quote them.
    debarment_disclosure: Mapped[str | None] = mapped_column(Text)

    status: Mapped[VendorStatus] = mapped_column(
        vendor_status_enum, nullable=False, default=VendorStatus.PENDING
    )
    elimination_reason: Mapped[str | None] = mapped_column(Text)
    elimination_clause_ref: Mapped[str | None] = mapped_column(String(120))
    elimination_source_page: Mapped[int | None] = mapped_column()
    elimination_source_snippet: Mapped[str | None] = mapped_column(Text)

    # technical_approach_text lives in Qdrant (Section 7), not here. This keeps
    # the pointer so a chunk can be traced back to its row and vice versa.
    has_technical_approach: Mapped[bool] = mapped_column(default=False, nullable=False)
    extraction_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    source_file: Mapped[str | None] = mapped_column(Text)
    #: SHA-256 of the uploaded bytes, and the key into the document store. What
    #: makes a citation clickable: without the original file, "page 5, clause
    #: 1.1" is a label a vendor has to take on trust.
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    # When a gap report was last put in front of someone (Section 5.6). Gap
    # reports are computed on demand, not stored, so this timestamp is the only
    # record that the vendor has SEEN a verdict -- and therefore the only thing a
    # later corrigendum can make out of date. NULL means never reported, which is
    # not the same as stale.
    last_gap_report_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    notification: Mapped["TenderNotificationRow | None"] = relationship(
        back_populates="submissions"
    )
    turnover: Mapped[list["VendorTurnoverRow"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", lazy="selectin"
    )
    certifications: Mapped[list["VendorCertificationRow"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", lazy="selectin"
    )
    past_projects: Mapped[list["VendorPastProjectRow"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", lazy="selectin"
    )
    documents_submitted: Mapped[list["VendorDocumentRow"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", lazy="selectin"
    )


class VendorTurnoverRow(Base, UUIDPrimaryKey, Timestamps, ProvenanceColumns):
    __tablename__ = "vendor_turnover"
    __table_args__ = (
        UniqueConstraint("submission_id", "year", name="uq_turnover_per_year"),
        Index("ix_vendor_turnover_amount", "amount_inr"),
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendor_submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(nullable=False)
    amount_raw: Mapped[str | None] = mapped_column(Text)
    # NULL means "seen but not parseable" -- must surface as needs-manual-check,
    # never be coerced to 0 by a downstream comparison.
    amount_inr: Mapped[Decimal | None] = mapped_column(Money)

    submission: Mapped[VendorSubmissionRow] = relationship(back_populates="turnover")


class VendorCertificationRow(Base, UUIDPrimaryKey, Timestamps, ProvenanceColumns):
    __tablename__ = "vendor_certifications"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendor_submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    valid_till: Mapped[date | None] = mapped_column(Date)
    doc_present: Mapped[bool] = mapped_column(default=False, nullable=False)

    submission: Mapped[VendorSubmissionRow] = relationship(back_populates="certifications")


class VendorPastProjectRow(Base, UUIDPrimaryKey, Timestamps, ProvenanceColumns):
    __tablename__ = "vendor_past_projects"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendor_submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client: Mapped[str | None] = mapped_column(Text)
    value_raw: Mapped[str | None] = mapped_column(Text)
    value_inr: Mapped[Decimal | None] = mapped_column(Money)
    year: Mapped[int | None] = mapped_column()
    # Kept in SQL for display; also chunked into Qdrant for the qualitative path.
    description: Mapped[str | None] = mapped_column(Text)

    submission: Mapped[VendorSubmissionRow] = relationship(back_populates="past_projects")


class VendorDocumentRow(Base, UUIDPrimaryKey, Timestamps, ProvenanceColumns):
    """One row per document the vendor supplied.

    `match_method` / `match_score` record *how* this was matched to a
    notification requirement (exact / alias / embedding), because Section 6
    rules out plain string matching and the audit trail (5.5) has to be able to
    show why a document counted as present.
    """

    __tablename__ = "vendor_documents"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendor_submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doc_name: Mapped[str] = mapped_column(Text, nullable=False)
    present: Mapped[bool] = mapped_column(default=False, nullable=False)
    matched_requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mandatory_documents.id", ondelete="SET NULL")
    )
    match_method: Mapped[str | None] = mapped_column(String(20))
    match_score: Mapped[float | None] = mapped_column(Float)

    submission: Mapped[VendorSubmissionRow] = relationship(
        back_populates="documents_submitted"
    )
