"""Tender notification tables.

Hybrid shape (Section 7 "structured fields in SQL"):
  normalized  -> eligibility_criteria, mandatory_documents  (read by the Level 1
                 rule engine 5.2 and the Level 3 structured router 5.4)
  JSONB       -> evaluation_criteria, technical_requirements,
                 submission_format_rules (display / RAG context only)
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, ProvenanceColumns, Timestamps, UUIDPrimaryKey
from app.schemas.common import CriterionType

criterion_type_enum = SAEnum(
    CriterionType,
    name="criterion_type",
    native_enum=True,
    create_type=True,
    values_callable=lambda enum: [m.value for m in enum],
)

# Rupee amounts: 18 digits is comfortably past the largest realistic contract
# value; 2 decimal places keeps paise so normalization is lossless.
Money = Numeric(18, 2)


class TenderNotificationRow(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "tender_notifications"
    __table_args__ = (
        Index("ix_tender_notifications_tender_id", "tender_id", unique=True),
    )

    tender_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    issuing_authority: Mapped[str | None] = mapped_column(String(300))
    sector: Mapped[str | None] = mapped_column(String(120), index=True)

    submission_deadline: Mapped[date | None] = mapped_column(Date)
    pre_bid_query_deadline: Mapped[date | None] = mapped_column(Date)

    # Text, not a bounded VARCHAR: these hold whatever the extractor read off
    # the page. A model that over-captures ("Rs. 12,50,00,000 (Rupees Twelve
    # Crore only). Bids shall remain valid for 180 days...") is an extraction
    # quality problem -- it must not also be an insert failure that discards the
    # whole document.
    emd_amount_raw: Mapped[str | None] = mapped_column(Text)
    emd_amount_inr: Mapped[Decimal | None] = mapped_column(Money)
    contract_value_raw: Mapped[str | None] = mapped_column(Text)
    contract_value_inr: Mapped[Decimal | None] = mapped_column(Money)

    # JSONB half of the hybrid: not filtered on, rendered or fed to RAG as-is.
    evaluation_criteria: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    technical_requirements: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    submission_format_rules: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    source_file: Mapped[str | None] = mapped_column(Text)
    #: SHA-256 of the uploaded bytes, and the key into the document store. What
    #: makes a citation clickable: without the original file, "page 5, clause
    #: 1.1" is a label a vendor has to take on trust.
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    eligibility_criteria: Mapped[list["EligibilityCriterionRow"]] = relationship(
        back_populates="notification", cascade="all, delete-orphan", lazy="selectin"
    )
    mandatory_documents: Mapped[list["MandatoryDocumentRow"]] = relationship(
        back_populates="notification", cascade="all, delete-orphan", lazy="selectin"
    )
    corrigenda: Mapped[list["CorrigendumRow"]] = relationship(
        back_populates="notification", cascade="all, delete-orphan", lazy="selectin"
    )
    submissions: Mapped[list["VendorSubmissionRow"]] = relationship(
        back_populates="notification", cascade="all, delete-orphan"
    )


class EligibilityCriterionRow(Base, UUIDPrimaryKey, Timestamps, ProvenanceColumns):
    """Normalized: the Level 1 rule engine reads thresholds straight off these rows."""

    __tablename__ = "eligibility_criteria"
    __table_args__ = (
        CheckConstraint(
            "type <> 'numeric' OR threshold_amount_inr IS NOT NULL "
            "OR threshold_number IS NOT NULL OR threshold_raw IS NOT NULL",
            name="numeric_criterion_has_threshold",
        ),
    )

    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tender_notifications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    criterion: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[CriterionType] = mapped_column(criterion_type_enum, nullable=False)
    threshold_raw: Mapped[str | None] = mapped_column(Text)
    threshold_amount_inr: Mapped[Decimal | None] = mapped_column(Money)
    threshold_number: Mapped[float | None] = mapped_column()
    unit: Mapped[str | None] = mapped_column(String(60))
    is_mandatory: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)

    notification: Mapped[TenderNotificationRow] = relationship(
        back_populates="eligibility_criteria"
    )


class MandatoryDocumentRow(Base, UUIDPrimaryKey, Timestamps, ProvenanceColumns):
    """Normalized: presence checks (4.3 / 5.2) join against these."""

    __tablename__ = "mandatory_documents"

    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tender_notifications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doc_name: Mapped[str] = mapped_column(Text, nullable=False)
    # Alias list for the synonym-resolution path in Section 6's doc-name note.
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")

    notification: Mapped[TenderNotificationRow] = relationship(
        back_populates="mandatory_documents"
    )
