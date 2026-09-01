"""Corrigendum tables (Section 5.6 -- amendments must not be silently ignored)."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, ProvenanceColumns, Timestamps, UUIDPrimaryKey


class CorrigendumRow(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "corrigenda"

    corrigendum_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tender_notifications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_tender_id: Mapped[str] = mapped_column(String(255), nullable=False)
    issued_date: Mapped[date | None] = mapped_column(Date)
    source_file: Mapped[str | None] = mapped_column(Text)
    # Set once the diff has been propagated to affected vendor evaluations (5.6).
    applied: Mapped[bool] = mapped_column(default=False, nullable=False)

    notification: Mapped["TenderNotificationRow"] = relationship(back_populates="corrigenda")
    changed_fields: Mapped[list["ChangedFieldRow"]] = relationship(
        back_populates="corrigendum", cascade="all, delete-orphan", lazy="selectin"
    )


class ChangedFieldRow(Base, UUIDPrimaryKey, Timestamps, ProvenanceColumns):
    __tablename__ = "corrigendum_changed_fields"

    corrigendum_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("corrigenda.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Dotted path into TenderNotification, e.g. 'submission_deadline'.
    field_path: Mapped[str] = mapped_column(String(200), nullable=False)
    # Text, not typed: a corrigendum may change a field's shape, and the audit
    # trail should record what was printed rather than a coerced value.
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)

    corrigendum: Mapped[CorrigendumRow] = relationship(back_populates="changed_fields")
