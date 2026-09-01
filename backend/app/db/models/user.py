"""Users and roles (Section 5.7 -- confidentiality between competing bidders).

Phase 0 lays down the table and ownership FKs only; no auth logic yet. Having
the columns now means access control lands as route guards, not as a migration
against populated tables.
"""

from __future__ import annotations

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.schemas.common import UserRole

# values_callable keeps the Postgres labels identical to the Pydantic enum
# *values* ('vendor'), not the member names ('VENDOR'). Without it the two
# halves of the system disagree and hand-written SQL silently matches nothing.
user_role_enum = SAEnum(
    UserRole,
    name="user_role",
    native_enum=True,
    create_type=True,
    values_callable=lambda enum: [m.value for m in enum],
)


class User(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(200))
    organisation: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[UserRole] = mapped_column(user_role_enum, nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
