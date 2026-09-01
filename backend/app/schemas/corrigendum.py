"""Notification Amendment (Corrigendum) schema (Section 6 / feature 5.6)."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from app.schemas.common import Provenanced, SchemaModel


class ChangedField(Provenanced):
    """Section 6: { field_path, old_value, new_value, clause_ref }.

    `field_path` is a dotted path into TenderNotification, e.g.
    'submission_deadline' or 'eligibility_criteria[0].threshold_amount', so the
    diff can be replayed against already-extracted evaluations (5.6).
    Values are kept as strings: a corrigendum may change a field's shape, and
    the audit trail should record what was printed, not a coerced value.
    """

    field_path: str
    old_value: str | None = None
    new_value: str | None = None


class Corrigendum(SchemaModel):
    """The full Section 6 Corrigendum Schema."""

    corrigendum_id: str
    parent_tender_id: str
    issued_date: date | None = None
    changed_fields: list[ChangedField] = Field(default_factory=list)
