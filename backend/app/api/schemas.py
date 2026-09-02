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
    #: high | low | none. Lifted out of the answer so the UI can style the
    #: whole response, not just append a sentence to it.
    confidence: str


class GapReportRequest(BaseModel):
    tender_id: str
    vendor_id: str
    acknowledge_amendments: bool = Field(
        default=False,
        description=(
            "The one-click re-check (5.6). Viewing a report does not clear its "
            "staleness banner -- the vendor may not have read it yet -- but "
            "explicitly re-checking does."
        ),
    )


class ChangedFieldOut(BaseModel):
    field_path: str
    label: str
    old_value: str | None
    new_value: str | None
    clause_ref: str | None = None
    source_page: int | None = None


class CorrigendumOut(BaseModel):
    corrigendum_id: str
    parent_tender_id: str
    issued_date: date | None
    source_file: str | None = None
    uploaded_at: datetime
    changed_fields: list[ChangedFieldOut] = Field(default_factory=list)


class StalenessOut(BaseModel):
    """Section 5.6, Part 1 slice: the tender moved, the report has not.

    `stale` is deliberately separate from the verdict. The verdict is still the
    honest answer to the question that was asked; it was just asked about an
    earlier version of the tender.
    """

    stale: bool
    banner: str | None = None
    corrigendum_id: str | None = None
    issued_date: date | None = None
    changed_fields: list[str] = Field(default_factory=list)
    last_checked_at: datetime | None = None


class ValidationFindingOut(BaseModel):
    field: str
    severity: str
    message: str
    value: str | None = None
    affects_confidence: bool = True
    #: Which document the finding is about, so the UI can say whose data is thin.
    source: str          # "notification" | "bid"


class DataQualityOut(BaseModel):
    """How much the figures below can be trusted (Section 10).

    Separate from the verdict on purpose. The verdict answers "does this bid
    meet the tender"; this answers "how good was our reading of either
    document". A confident verdict computed from a notification whose deadline
    and EMD were never extracted is the failure this exists to make visible.
    """

    ok: bool
    banner: str | None = None
    findings: list[ValidationFindingOut] = Field(default_factory=list)


class CompletionOut(BaseModel):
    satisfied: int
    total: int
    undetermined: int
    label: str
    caveat: str


class GapReportResponse(BaseModel):
    report: GapReport
    verdict: str
    counts: dict[str, int]
    staleness: StalenessOut
    data_quality: DataQualityOut
    #: Section 4.4/4.6 -- a factual count, with the copy that keeps it from
    #: being read as a score travelling alongside it.
    completion: CompletionOut
    #: Section 4.6 -- the split the UI leads with, so twenty "check this" items
    #: do not make a clean bid look like a disaster.
    action_counts: dict[str, int] = Field(default_factory=dict)


NotificationList.model_rebuild()
