"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.repository import get_notification_row, get_submission_row
from app.db.session import get_session

SessionDep = Depends(get_session)


def get_db() -> Iterator[Session]:
    yield from get_session()


def require_notification(session: Session, tender_id: str):
    row = get_notification_row(session, tender_id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No tender notification with id {tender_id!r}"
        )
    return row


def require_submission(session: Session, tender_id: str, vendor_id: str):
    row = get_submission_row(session, tender_id, vendor_id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No submission from vendor {vendor_id!r} against tender {tender_id!r}",
        )
    return row
