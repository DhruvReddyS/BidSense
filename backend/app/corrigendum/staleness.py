"""Is this vendor's gap report older than the tender it was checked against?

Gap reports are computed on demand rather than stored, so there is no document
to go and mark stale. What can go stale is the vendor's *knowledge*: they read a
report saying they were compliant, and the tender has since changed underneath
it. That is what `vendor_submissions.last_gap_report_at` records -- the moment a
report was last put in front of someone -- and a corrigendum filed after it
makes what they read out of date.

Deliberately NOT done here: re-deciding anything. The amended threshold is not
applied to the stored verdict, no vendor is re-eliminated, and nothing is
recomputed in the background. Section 5.6's propagation across a pool of vendors
is Part 2. The Part 1 slice is to say plainly that the ground moved, name what
moved, and offer a button -- because a compliance answer silently changing
between two viewings is worse than one that admits it is out of date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.corrigendum.diff import FIELD_LABELS, UNMAPPED
from app.db.models import CorrigendumRow, VendorSubmissionRow

__all__ = ["Staleness", "staleness_for", "mark_report_generated"]


@dataclass(frozen=True)
class Staleness:
    """Why a report is out of date, in terms a vendor can act on."""

    stale: bool
    corrigendum_id: str | None = None
    issued_date: date | None = None
    changed_fields: tuple[str, ...] = ()
    last_checked_at: datetime | None = None

    @property
    def banner(self) -> str | None:
        if not self.stale:
            return None
        when = self.issued_date.strftime("%d %B %Y") if self.issued_date else "recently"
        message = f"This tender was updated on {when} — recheck your compliance."
        if self.changed_fields:
            message += " Changed: " + ", ".join(self.changed_fields) + "."
        return message


def _label(field_path: str) -> str:
    if field_path.startswith("unmapped:"):
        return field_path.split(":", 1)[1]
    if field_path == UNMAPPED:
        return "an unidentified term"
    return FIELD_LABELS.get(field_path, field_path.replace("_", " ").replace(".", " — "))


def staleness_for(
    session: Session, notification_id, submission_row: VendorSubmissionRow
) -> Staleness:
    """Whether a corrigendum landed after this vendor last saw a report.

    A vendor who has never run a report is not stale: there is nothing out of
    date, and a banner saying otherwise on a first visit would be noise.
    """
    last_checked = submission_row.last_gap_report_at
    if last_checked is None:
        return Staleness(stale=False)

    corrigenda = session.scalars(
        select(CorrigendumRow)
        .where(CorrigendumRow.notification_id == notification_id)
        .order_by(CorrigendumRow.created_at.desc())
    ).all()

    # Compared on created_at -- when we learned of the amendment -- not on
    # issued_date. A corrigendum issued last month but uploaded today still
    # invalidates a report run yesterday, and issued_date is frequently absent.
    newer = [c for c in corrigenda if _aware(c.created_at) > _aware(last_checked)]
    if not newer:
        return Staleness(stale=False, last_checked_at=last_checked)

    latest = newer[0]
    labels: list[str] = []
    for corrigendum in newer:
        for change in corrigendum.changed_fields:
            label = _label(change.field_path)
            if label not in labels:
                labels.append(label)

    return Staleness(
        stale=True,
        corrigendum_id=latest.corrigendum_id,
        issued_date=latest.issued_date,
        changed_fields=tuple(labels),
        last_checked_at=last_checked,
    )


def _aware(value: datetime) -> datetime:
    """Postgres columns come back naive in this schema; compare in UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def mark_report_generated(submission_row: VendorSubmissionRow) -> None:
    """Stamp the moment a report was put in front of someone.

    Called on first generation and on an explicit re-check, never on every read:
    stamping on every read would clear the banner the instant it was rendered,
    which is exactly when the vendor has not yet acted on it.
    """
    submission_row.last_gap_report_at = datetime.now(timezone.utc)
