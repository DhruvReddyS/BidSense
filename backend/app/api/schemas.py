"""API request/response models (Phase 2)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.compliance.models import GapReport
from app.rag.answer import GroundedAnswer
from app.schemas.common import UserRole


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=10, max_length=128)
    full_name: str | None = Field(default=None, max_length=200)
    organisation: str | None = Field(default=None, max_length=200)
    role: UserRole
    reviewer_code: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str | None
    organisation: str | None
    role: UserRole


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


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
    extracted_by: str | None = None
    from_cache: bool = False
    timing: dict[str, float] = Field(default_factory=dict)


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
    data_quality: "DataQualityOut | None" = None
    answer: GroundedAnswer
    #: Lets each citation be opened on its page. A citation maps to a document
    #: by its `doc_kind`.
    sources: "SourceDocuments" = Field(default_factory=lambda: SourceDocuments())
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


class Level1RunRequest(BaseModel):
    tender_id: str


class Level1VendorResult(BaseModel):
    vendor_id: str
    vendor_name: str
    status: str
    elimination_reason: str | None = None
    clause_ref: str | None = None
    source_page: int | None = None


class Level1RunResponse(BaseModel):
    tender_id: str
    total: int
    eliminated: int
    pending: int
    results: list[Level1VendorResult]


class PerformanceSummary(BaseModel):
    completed_jobs: int
    median_seconds: float | None
    p95_seconds: float | None
    cache_reuse_percent: float
    pages_per_second: float | None


class Level2RunRequest(BaseModel):
    tender_id: str
    target_count: int = Field(ge=1, le=100)
    factor_weights: dict[str, float] = Field(default_factory=dict)


class ShortlistCandidateOut(BaseModel):
    vendor_id: str
    vendor_name: str
    status: str
    summary: str
    evidence: list[str] = Field(default_factory=list)


class Level2RunResponse(BaseModel):
    tender_id: str
    eligible: int
    shortlisted: int
    requested: int
    factors: list[str]
    candidates: list[ShortlistCandidateOut]
    caveat: str = "Qualified pool, not a ranking. Final selection remains with the evaluation committee."


class PoolQueryRequest(BaseModel):
    tender_id: str
    question: str = Field(min_length=3, max_length=1000)


class PoolCitationOut(BaseModel):
    vendor_id: str | None = None
    source_file: str | None = None
    source_page: int | None = None
    clause_ref: str | None = None
    snippet: str


class PoolQueryResponse(BaseModel):
    route: str
    answer: str
    citations: list[PoolCitationOut] = Field(default_factory=list)
    caveat: str = "This assistant summarizes recorded evidence; it does not select a winner."


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
    applied: bool = False


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
    providers: dict[str, str | None] = Field(default_factory=dict)


class CompletionOut(BaseModel):
    satisfied: int
    total: int
    undetermined: int
    label: str
    caveat: str


class SourceDocuments(BaseModel):
    """Where each side's citations can be opened.

    Returned as hashes rather than URLs so the client composes them, and null
    when a document predates the store -- the UI then shows page and clause
    without a page image instead of a broken link.
    """

    notification: str | None = None
    bid: str | None = None


class GapReportResponse(BaseModel):
    report: GapReport
    verdict: str
    counts: dict[str, int]
    staleness: StalenessOut
    data_quality: DataQualityOut
    sources: SourceDocuments
    #: Section 4.4/4.6 -- a factual count, with the copy that keeps it from
    #: being read as a score travelling alongside it.
    completion: CompletionOut
    #: Section 4.6 -- the split the UI leads with, so twenty "check this" items
    #: do not make a clean bid look like a disaster.
    action_counts: dict[str, int] = Field(default_factory=dict)


NotificationList.model_rebuild()
