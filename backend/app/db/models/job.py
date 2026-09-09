"""Ingestion jobs (production concern, not a Section 12 feature).

Extracting a real tender takes two to three minutes: six LLM calls, paced by a
free-tier quota. Doing that inside the HTTP request means the browser, and any
proxy in front of the API, is holding a connection open for minutes with no
progress and no way to recover from a dropped connection.

So uploads return immediately with a job id and the work continues in the
background. Job state lives in Postgres rather than in process memory: a restart
mid-extraction must leave a visible failed job, not a request that silently
never completes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    # The extraction produced usable output but some field groups failed. A
    # distinct state from FAILED: the data is stored and worth looking at.
    PARTIAL = "partial"
    FAILED = "failed"


class JobKind(StrEnum):
    NOTIFICATION = "notification"
    SUBMISSION = "submission"
    CORRIGENDUM = "corrigendum"


job_status_enum = SAEnum(
    JobStatus, name="job_status", native_enum=True, create_type=True,
    values_callable=lambda enum: [m.value for m in enum],
)
job_kind_enum = SAEnum(
    JobKind, name="job_kind", native_enum=True, create_type=True,
    values_callable=lambda enum: [m.value for m in enum],
)


class IngestJob(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "ingest_jobs"

    kind: Mapped[JobKind] = mapped_column(job_kind_enum, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        job_status_enum, nullable=False, default=JobStatus.QUEUED, index=True
    )

    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    tender_id: Mapped[str | None] = mapped_column(String(255), index=True)
    vendor_id: Mapped[str | None] = mapped_column(String(255))

    # Human-readable stage, so the UI can say "extracting eligibility criteria"
    # rather than spinning for three minutes with no explanation.
    stage: Mapped[str | None] = mapped_column(String(120))
    pages_total: Mapped[int | None] = mapped_column()
    steps_done: Mapped[int] = mapped_column(default=0, nullable=False)
    steps_total: Mapped[int | None] = mapped_column()

    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    row_id: Mapped[uuid.UUID | None] = mapped_column()
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in (JobStatus.SUCCEEDED, JobStatus.PARTIAL, JobStatus.FAILED)

    @property
    def progress(self) -> float:
        if self.is_terminal:
            return 1.0
        if not self.steps_total:
            return 0.0
        return min(0.99, self.steps_done / self.steps_total)
