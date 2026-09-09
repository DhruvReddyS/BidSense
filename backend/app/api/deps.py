"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.repository import get_notification_row, get_submission_row
from app.db.session import get_session

SessionDep = Depends(get_session)
bearer = HTTPBearer(auto_error=False)


def get_db() -> Iterator[Session]:
    yield from get_session()


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), session: Session = Depends(get_db)):
    from app.auth import verify_token
    from app.db.models import User
    claims = verify_token(credentials.credentials) if credentials and credentials.scheme.lower() == "bearer" else None
    user = session.scalar(select(User).where(User.id == claims.get("sub"))) if claims else None
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Valid authentication is required", headers={"WWW-Authenticate": "Bearer"})
    return user


def reviewer_user(user=Depends(current_user)):
    from app.schemas.common import UserRole
    if user.role != UserRole.REVIEWER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Company reviewer role required")
    return user


def ensure_submission_access(user, submission) -> None:
    from app.schemas.common import UserRole
    if user.role == UserRole.REVIEWER:
        return
    if submission.owner_user_id != user.id:
        # 404 avoids confirming that a competing bidder's record exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")


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
