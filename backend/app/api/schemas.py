"""API request/response models (Phase 2)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.compliance.models import GapReport
from app.rag.answer import GroundedAnswer


class HealthResponse(BaseModel):
    status: str
    postgres: bool
    qdrant: bool
    embeddings: bool
    llm_provider: str
    llm_reachable: bool
    ocr_available: bool
    ocr_missing: list[str] = Field(default_factory=list)


class JobAccepted(BaseModel):
    """202 response: the work continues in the background.

    Extraction takes minutes (six LLM calls, paced by a free-tier quota). Doing
    it inside the request would hold an HTTP connection open with no progress
    and no way to recover from a dropped connection.
    """

    job_id: str
    status: str
    file_name: str
    poll_url: str


class JobStatusResponse(BaseModel):
    job_id: str
    kind: str
    status: str
    stage: str | None
    progress: float = Field(ge=0.0, le=1.0)
    steps_done: int
    steps_total: int | None
    file_name: str
    tender_id: str | None
    vendor_id: str | None
    result: dict | None
    error: str | None
    seconds_elapsed: float | None


class Page(BaseModel):
    total: int
    limit: int
    offset: int


class IngestResponse(BaseModel):
    """Mirrors IngestReport. `ok=False` with rows written is a real state: a
    partial extraction is stored and flagged, not discarded."""

    ok: bool
    file_name: str
    identifier: str | None
    pages: int
    ocr_pages: int
    chunks_indexed: int
    parse_warnings: list[str]
    extraction_errors: list[str]
    seconds: float


class NotificationList(BaseModel):
    items: list["NotificationSummary"]
    page: Page


class NotificationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tender_id: str
    title: str
    issuing_authority: str | None
    sector: str | None
    submission_deadline: date | None
    emd_amount_inr: Decimal | None
    eligibility_count: int
    document_count: int
    submission_count: int
    created_at: datetime


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    tender_id: str
    vendor_id: str | None = Field(
        default=None,
        description="Scopes retrieval to this bid plus the notification (Part 1, 4.5).",
    )
    top_k: int = Field(default=6, ge=1, le=20)


class AskResponse(BaseModel):
    answer: GroundedAnswer
    # Surfaced so the UI can show a warning rather than presenting an
    # ungrounded answer as if it were verified.
    grounded: bool


class GapReportRequest(BaseModel):
    tender_id: str
    vendor_id: str


class GapReportResponse(BaseModel):
    report: GapReport
    verdict: str
    counts: dict[str, int]


NotificationList.model_rebuild()
