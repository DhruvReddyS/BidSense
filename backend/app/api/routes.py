"""Phase 2 API routes (Part 1: the vendor tool)."""

from __future__ import annotations

import logging
import hmac
import importlib.util
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.quality import quality_for, provider_label
from app.api.deps import get_db, require_notification, require_submission, current_user, reviewer_user, ensure_submission_access
from app.api import jobs as job_runner
from app.api.schemas import (
    AskRequest,
    AskResponse,
    ChangedFieldOut,
    CompletionOut,
    CorrigendumOut,
    DataQualityOut,
    ValidationFindingOut,
    GapReportRequest,
    GapReportResponse,
    HealthResponse,
    JobAccepted,
    JobStatusResponse,
    Level1RunRequest,
    Level1RunResponse,
    Level1VendorResult,
    Level2RunRequest,
    Level2RunResponse,
    ShortlistCandidateOut,
    PoolQueryRequest,
    PoolQueryResponse,
    PoolCitationOut,
    NotificationList,
    NotificationSummary,
    Page,
    PerformanceSummary,
    SourceDocuments,
    StalenessOut,
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    UserOut,
)
from app.db.models import IngestJob, JobKind, JobStatus
from app.compliance.gap import build_gap_report
from app.compliance.elimination import decide
from app.corrigendum.diff import FIELD_LABELS
from app.corrigendum.staleness import mark_report_generated, staleness_for
from app.extraction.validate import (
    Finding,
    Severity as ValidationSeverity,
    summarise,
    validate_notification,
    validate_submission,
)
from app.config import settings
from app.db.repository import (
    count_notifications,
    list_notifications,
    list_submissions,
    submission_counts,
    to_notification_schema,
    to_submission_schema,
)
from app.ingest import missing_dependencies, ocr_available
from app.ingest.loader import SUPPORTED_SUFFIXES, UnsupportedDocumentError
from app.rag import answer_question, retrieve, retrieve_for_pair
from app.schemas.common import ChunkSection, DocumentKind
from app.schemas.common import VendorStatus
from app.review import build_candidate, choose_shortlist, classify_query, structured_answer
from app.documents import store_document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # tender PDFs are large but not unbounded


def _user_out(user) -> UserOut:
    return UserOut(id=str(user.id), email=user.email, full_name=user.full_name, organisation=user.organisation, role=user.role)


@router.post("/auth/register", response_model=TokenResponse, status_code=201)
def register(request: RegisterRequest, session: Session = Depends(get_db)) -> TokenResponse:
    from sqlalchemy import func, select
    from app.auth import create_token, hash_password
    from app.db.models import User
    email = request.email.strip().casefold()
    from app.schemas.common import UserRole
    if request.role == UserRole.REVIEWER and not hmac.compare_digest(request.reviewer_code or "", settings.reviewer_registration_code):
        raise HTTPException(status_code=403, detail="A valid reviewer invitation code is required")
    if session.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(email=email, full_name=request.full_name, organisation=request.organisation, role=request.role, hashed_password=hash_password(request.password))
    session.add(user); session.commit(); session.refresh(user)
    return TokenResponse(access_token=create_token(str(user.id), user.role.value), user=_user_out(user))


@router.post("/auth/login", response_model=TokenResponse)
def login(request: LoginRequest, session: Session = Depends(get_db)) -> TokenResponse:
    from sqlalchemy import func, select
    from app.auth import create_token, verify_password
    from app.db.models import User
    user = session.scalar(select(User).where(func.lower(User.email) == request.email.strip().casefold()))
    if user is None or not user.is_active or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    return TokenResponse(access_token=create_token(str(user.id), user.role.value), user=_user_out(user))


@router.get("/auth/me", response_model=UserOut)
def me(user=Depends(current_user)) -> UserOut:
    return _user_out(user)


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Reports each dependency separately so a partial outage is diagnosable
    rather than surfacing as a generic failure later in a user flow."""
    from sqlalchemy import text

    from app.db.session import engine
    from app.vector.qdrant import collection_stats

    postgres = qdrant = embeddings = llm_ok = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        postgres = True
    except Exception as exc:
        logger.warning("postgres unhealthy: %s", exc)
    try:
        qdrant = bool(collection_stats().get("exists"))
    except Exception as exc:
        logger.warning("qdrant unhealthy: %s", exc)
    # Liveness must not trigger a 440 MB model load or accelerator warm-up.
    # Those are intentionally lazy on the first search/index operation. Here we
    # report whether the configured embedding runtime is installed; ingestion
    # itself still performs the dimension/runtime checks before using it.
    embeddings = (
        importlib.util.find_spec("sentence_transformers") is not None
        and settings.embedding_dim > 0
    )
    try:
        from app.llm import get_llm

        get_llm()
        llm_ok = True
    except Exception as exc:
        logger.warning("llm unavailable: %s", exc)

    healthy = postgres and qdrant
    return HealthResponse(
        status="ok" if healthy else "degraded",
        postgres=postgres,
        qdrant=qdrant,
        embeddings=embeddings,
        llm_provider=settings.llm_provider,
        llm_reachable=llm_ok,
        ocr_available=ocr_available(),
        ocr_missing=missing_dependencies(),
    )


# --------------------------------------------------------------------------- #
# Upload
# --------------------------------------------------------------------------- #
def _save_upload(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file type {suffix!r}. Upload a PDF or DOCX.",
        )
    temp = Path(tempfile.mkdtemp()) / Path(upload.filename).name
    size = 0
    with temp.open("wb") as handle:
        while chunk := upload.file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                shutil.rmtree(temp.parent, ignore_errors=True)
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.",
                )
            handle.write(chunk)
    return temp


def _to_response(report) -> IngestResponse:
    return IngestResponse(
        ok=report.ok,
        file_name=report.file_name,
        identifier=report.identifier,
        pages=report.pages,
        ocr_pages=report.ocr_pages,
        chunks_indexed=report.chunks_indexed,
        parse_warnings=report.parse_warnings,
        extraction_errors=report.extraction_errors,
        seconds=round(report.total_seconds, 2),
        extracted_by=report.extracted_by,
        from_cache=report.from_cache,
        timing={
            "parse": round(report.parse_seconds, 2),
            "extract": round(report.extract_seconds, 2),
            "persist": round(report.persist_seconds, 2),
            "index": round(report.index_seconds, 2),
        },
    )


def _accept(job_id, file_name: str) -> JobAccepted:
    return JobAccepted(
        job_id=str(job_id),
        status="queued",
        file_name=file_name,
        poll_url=f"/api/jobs/{job_id}",
    )


@router.post("/notifications", response_model=JobAccepted, status_code=202)
def upload_notification(file: UploadFile = File(...), reviewer=Depends(reviewer_user)) -> JobAccepted:
    """Section 4.1 -- ingest the official tender notification.

    Returns 202 immediately; poll `poll_url` for progress.
    """
    path = _save_upload(file)
    try:
        digest = store_document(path)
        job_id = job_runner.create_job(JobKind.NOTIFICATION, path.name, owner_user_id=reviewer.id, source_hash=digest)
        job_runner.submit(job_id, JobKind.NOTIFICATION, path, owner_user_id=reviewer.id)
    except Exception:
        # The worker deletes the upload when it finishes. If queueing itself
        # fails there is no worker, so the temp directory would be orphaned --
        # a tens-of-megabytes leak per failed upload.
        shutil.rmtree(path.parent, ignore_errors=True)
        raise
    return _accept(job_id, path.name)


@router.post("/submissions", response_model=JobAccepted, status_code=202)
def upload_submission(
    file: UploadFile = File(...),
    vendor_id: str = Form(..., min_length=1, max_length=255),
    tender_id: str = Form(..., min_length=1, max_length=255),
    session: Session = Depends(get_db),
    user=Depends(current_user),
) -> JobAccepted:
    """Section 4.2 -- ingest a vendor's draft bid against a notification."""
    # Validated before the job is queued: a bid filed against a tender that does
    # not exist would otherwise fail three minutes later with nothing useful to
    # tell the user.
    require_notification(session, tender_id)

    path = _save_upload(file)
    try:
        digest = store_document(path)
        job_id = job_runner.create_job(
            JobKind.SUBMISSION, path.name, tender_id=tender_id, vendor_id=vendor_id, owner_user_id=user.id, source_hash=digest
        )
        job_runner.submit(
            job_id, JobKind.SUBMISSION, path, vendor_id=vendor_id, tender_id=tender_id, owner_user_id=user.id
        )
    except Exception:
        shutil.rmtree(path.parent, ignore_errors=True)
        raise
    return _accept(job_id, path.name)


@router.post("/corrigenda", response_model=JobAccepted, status_code=202)
def upload_corrigendum(
    file: UploadFile = File(...),
    tender_id: str = Form(..., min_length=1, max_length=255),
    session: Session = Depends(get_db),
    reviewer=Depends(reviewer_user),
) -> JobAccepted:
    """Section 5.6 (Part 1 slice) -- amend a notification already extracted.

    Validated before queueing for the same reason a bid is: an amendment to a
    tender we have never read cannot be diffed against anything, and finding
    that out three minutes later helps nobody.
    """
    require_notification(session, tender_id)

    path = _save_upload(file)
    try:
        digest = store_document(path)
        job_id = job_runner.create_job(
            JobKind.CORRIGENDUM, path.name, tender_id=tender_id, owner_user_id=reviewer.id, source_hash=digest
        )
        job_runner.submit(job_id, JobKind.CORRIGENDUM, path, tender_id=tender_id)
    except Exception:
        shutil.rmtree(path.parent, ignore_errors=True)
        raise
    return _accept(job_id, path.name)


# --------------------------------------------------------------------------- #
# Section 4.3 / 4.5 -- citation click-through
# --------------------------------------------------------------------------- #
@router.get("/documents/{content_hash}/page/{page}")
def document_page(
    content_hash: str,
    page: int,
    highlight: str | None = Query(default=None, max_length=2000),
    dpi: int = Query(default=0, ge=0, le=200),
):
    """Render one page of a source document, marking a cited passage.

    Rendered on the server so the highlight is computed from the same word
    coordinates the extractor read. A browser-side text search over a
    re-extracted text layer can disagree with the backend about where a phrase
    sits, and a citation that points at the wrong clause is worse than one that
    is merely a label.
    """
    from fastapi.responses import Response

    from app.documents import path_for, render_page

    path = path_for(content_hash)
    if path is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "That source document is not retained. Documents ingested before "
            "citation click-through was added have no stored copy; re-upload it "
            "to enable it.",
        )
    try:
        rendered = render_page(
            path, page, highlight=highlight, dpi=dpi or settings.page_render_dpi
        )
    except Exception as exc:
        logger.warning("could not render %s p%s: %s", content_hash[:12], page, exc)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Could not render that page: {exc}"
        ) from exc

    return Response(
        content=rendered.png,
        media_type="image/png",
        headers={
            # Content-addressed, so a given hash+page+highlight never changes.
            "Cache-Control": "public, max-age=86400, immutable",
            "X-Page": str(rendered.page),
            "X-Page-Count": str(rendered.page_count),
            # Zero is a real answer: the passage could not be located, and the
            # UI says so rather than implying the page was marked.
            "X-Highlights": str(rendered.highlights),
            "X-Highlight-At": (
                "" if rendered.highlight_at is None else str(rendered.highlight_at)
            ),
            "Access-Control-Expose-Headers":
                "X-Page, X-Page-Count, X-Highlights, X-Highlight-At",
        },
    )


@router.get("/documents/{content_hash}")
def document_file(content_hash: str, download: bool = Query(default=False)):
    """The original PDF, for a vendor who wants the whole thing."""
    from fastapi.responses import FileResponse

    from app.documents import path_for

    path = path_for(content_hash)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That source document is not retained.")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name if download else None,
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def job_status(job_id: str, session: Session = Depends(get_db)) -> JobStatusResponse:
    try:
        key = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed job id") from None

    job = session.get(IngestJob, key)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No job {job_id}")

    # A wedged job would otherwise report RUNNING for ever, and a client polling
    # it has no way to tell "slow" from "stuck".
    if job_runner.fail_if_stuck(job):
        session.commit()

    elapsed = None
    if job.started_at:
        end = job.finished_at or datetime.now(timezone.utc)
        elapsed = round((end - job.started_at).total_seconds(), 1)

    return JobStatusResponse(
        job_id=str(job.id),
        kind=job.kind.value,
        status=job.status.value,
        stage=job.stage,
        progress=job.progress,
        steps_done=job.steps_done,
        steps_total=job.steps_total,
        file_name=job.file_name,
        tender_id=job.tender_id,
        vendor_id=job.vendor_id,
        result=job.result,
        error=job.error,
        seconds_elapsed=elapsed,
    )


@router.get("/review/performance", response_model=PerformanceSummary)
def review_performance(
    session: Session = Depends(get_db), reviewer=Depends(reviewer_user)
) -> PerformanceSummary:
    """A compact operational pulse over recent completed document jobs."""
    rows = session.scalars(
        select(IngestJob)
        .where(
            IngestJob.status.in_([JobStatus.SUCCEEDED, JobStatus.PARTIAL]),
            IngestJob.result.is_not(None),
        )
        .order_by(IngestJob.finished_at.desc())
        .limit(200)
    ).all()
    samples = []
    cached = 0
    total_pages = 0
    total_seconds = 0.0
    for row in rows:
        result = row.result or {}
        # Deferred Level-3 indexing may finish after Level-1 review is ready;
        # report the user-visible decision latency, not background tail work.
        seconds = result.get("decision_ready_seconds", result.get("seconds"))
        if isinstance(seconds, (int, float)) and seconds >= 0:
            samples.append(float(seconds))
            pages = result.get("pages")
            if isinstance(pages, int) and pages > 0 and seconds > 0:
                total_pages += pages
                total_seconds += float(seconds)
        cached += int(bool(result.get("from_cache")))
    samples.sort()

    def percentile(fraction: float) -> float | None:
        if not samples:
            return None
        position = (len(samples) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(samples) - 1)
        value = samples[lower] + (samples[upper] - samples[lower]) * (position - lower)
        return round(value, 1)

    return PerformanceSummary(
        completed_jobs=len(samples),
        median_seconds=percentile(0.5),
        p95_seconds=percentile(0.95),
        cache_reuse_percent=round(cached / len(rows) * 100, 1) if rows else 0.0,
        pages_per_second=round(total_pages / total_seconds, 2) if total_seconds else None,
    )


# --------------------------------------------------------------------------- #
# Reading extracted data
# --------------------------------------------------------------------------- #
@router.get("/notifications", response_model=NotificationList)
def get_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> NotificationList:
    rows = list_notifications(session, limit=limit, offset=offset)
    # One grouped query for every tender's bid count, rather than one query per
    # tender inside the loop.
    counts = submission_counts(session, [row.id for row in rows])
    return NotificationList(
        items=[
            NotificationSummary(
                tender_id=row.tender_id,
                title=row.title,
                issuing_authority=row.issuing_authority,
                sector=row.sector,
                submission_deadline=row.submission_deadline,
                emd_amount_inr=row.emd_amount_inr,
                eligibility_count=len(row.eligibility_criteria),
                document_count=len(row.mandatory_documents),
                submission_count=counts.get(row.id, 0),
                created_at=row.created_at,
            )
            for row in rows
        ],
        page=Page(total=count_notifications(session), limit=limit, offset=offset),
    )


# NOTE: this route MUST be declared before the bare /{tender_id:path} route
# below. Real tender ids contain slashes -- "TENDER No.01/SE(Electrical)/GHMC/
# 2024-25" -- so the path converter is required, and a greedy converter matched
# first would swallow the "/submissions" suffix into the id.
@router.get("/notifications/{tender_id:path}/submissions")
def get_submissions(tender_id: str, session: Session = Depends(get_db), reviewer=Depends(reviewer_user)):
    row = require_notification(session, tender_id)
    return [
        {
            "vendor_id": s.vendor_id,
            "vendor_name": s.vendor_name,
            "status": s.status,
            "is_blacklisted": s.is_blacklisted,
            "elimination_reason": s.elimination_reason,
        }
        for s in list_submissions(session, row.id)
    ]


# --------------------------------------------------------------------------- #
# Part 2, Level 1 — deterministic pool elimination
# --------------------------------------------------------------------------- #
@router.post("/review/level1", response_model=Level1RunResponse)
def run_level1(
    request: Level1RunRequest,
    session: Session = Depends(get_db),
    _reviewer=Depends(reviewer_user),
) -> Level1RunResponse:
    """Evaluate every bid against hard tender criteria and persist the result.

    The LLM is deliberately absent: this consumes already extracted structured
    fields and the same auditable rule engine used by the vendor gap report.
    """
    from app.vector.qdrant import retag_status

    notification_row = require_notification(session, request.tender_id)
    notification = to_notification_schema(notification_row)
    rows = list_submissions(session, notification_row.id)
    results: list[Level1VendorResult] = []
    originals: list[tuple[object, VendorStatus]] = []
    retagged: list[tuple[str, VendorStatus]] = []

    try:
        for row in rows:
            report = build_gap_report(notification, to_submission_schema(row))
            decision = decide(report)
            originals.append((row, row.status))
            row.status = decision.status
            row.elimination_reason = decision.reason
            row.elimination_clause_ref = decision.clause_ref
            row.elimination_source_page = decision.source_page
            row.elimination_source_snippet = decision.source_snippet
            results.append(
                Level1VendorResult(
                    vendor_id=row.vendor_id,
                    vendor_name=row.vendor_name,
                    status=decision.status.value,
                    elimination_reason=decision.reason,
                    clause_ref=decision.clause_ref,
                    source_page=decision.source_page,
                )
            )

        session.flush()
        for row, old_status in originals:
            retag_status(str(row.id), row.status)
            retagged.append((str(row.id), old_status))
        session.commit()
    except Exception:
        session.rollback()
        for submission_id, old_status in retagged:
            try:
                retag_status(submission_id, old_status)
            except Exception:
                logger.critical("Could not compensate Qdrant status for %s", submission_id)
        raise

    eliminated = sum(result.status == VendorStatus.ELIMINATED.value for result in results)
    return Level1RunResponse(
        tender_id=request.tender_id,
        total=len(results),
        eliminated=eliminated,
        pending=len(results) - eliminated,
        results=results,
    )


@router.post("/review/level2", response_model=Level2RunResponse)
def run_level2(request: Level2RunRequest, session: Session = Depends(get_db), _reviewer=Depends(reviewer_user)) -> Level2RunResponse:
    """Create a reviewer-sized qualified pool without publishing a ranking."""
    from app.vector.qdrant import retag_status

    notification_row = require_notification(session, request.tender_id)
    rows = list_submissions(session, notification_row.id)
    eligible_rows = [row for row in rows if row.status != VendorStatus.ELIMINATED]
    candidates = [build_candidate(row) for row in eligible_rows]
    selected = choose_shortlist(candidates, min(request.target_count, len(candidates)), request.factor_weights)
    selected_ids = {candidate.vendor_id for candidate in selected}
    originals = [(row, row.status) for row in eligible_rows]
    retagged: list[tuple[str, VendorStatus]] = []
    try:
        for row in eligible_rows:
            row.status = VendorStatus.SHORTLISTED if row.vendor_id in selected_ids else VendorStatus.PENDING
        session.flush()
        for row, old_status in originals:
            retag_status(str(row.id), row.status)
            retagged.append((str(row.id), old_status))
        session.commit()
    except Exception:
        session.rollback()
        for submission_id, old_status in retagged:
            try:
                retag_status(submission_id, old_status)
            except Exception:
                logger.critical("Could not compensate Qdrant shortlist status for %s", submission_id)
        raise

    output = []
    for candidate in selected:
        evidence = [f"{candidate.experience:g} years in business"]
        if candidate.project_scale is not None:
            evidence.append(f"Largest recorded project ₹{candidate.project_scale:,.0f}")
        if candidate.pricing is not None:
            evidence.append(f"Quoted price ₹{candidate.pricing:,.0f}")
        if candidate.technical_approach:
            evidence.append("Technical approach present")
        output.append(ShortlistCandidateOut(
            vendor_id=candidate.vendor_id,
            vendor_name=candidate.vendor_name,
            status=VendorStatus.SHORTLISTED.value,
            summary="Selected into the qualified pool from the reviewer-chosen factors and recorded bid facts.",
            evidence=evidence,
        ))
    return Level2RunResponse(
        tender_id=request.tender_id,
        eligible=len(candidates),
        shortlisted=len(output),
        requested=request.target_count,
        factors=list(request.factor_weights) or ["experience", "project_scale", "technical_approach", "pricing"],
        candidates=output,
    )


@router.post("/review/query", response_model=PoolQueryResponse)
def query_vendor_pool(request: PoolQueryRequest, session: Session = Depends(get_db), _reviewer=Depends(reviewer_user)) -> PoolQueryResponse:
    """Route audit/structured questions to SQL facts and narrative questions to Qdrant."""
    notification_row = require_notification(session, request.tender_id)
    rows = list_submissions(session, notification_row.id)
    candidates = [build_candidate(row) for row in rows]
    statuses = {row.vendor_id: row.status.value for row in rows}
    reasons = {row.vendor_id: row.elimination_reason for row in rows}
    route = classify_query(request.question)
    citations: list[PoolCitationOut] = []

    if route in {"qualitative", "hybrid"}:
        chunks = retrieve(
            request.question,
            tender_id=request.tender_id,
            doc_kind=DocumentKind.SUBMISSION,
            sections=[ChunkSection.TECHNICAL_APPROACH, ChunkSection.PAST_PERFORMANCE],
            top_k=8,
        )
        citations = [PoolCitationOut(
            vendor_id=chunk.vendor_id,
            source_file=chunk.source_file,
            source_page=chunk.source_page,
            clause_ref=chunk.clause_ref,
            snippet=chunk.text[:500],
        ) for chunk in chunks]
        narrative = " ".join(
            f"{chunk.vendor_id or 'Submission'} records: {chunk.text[:240].strip()}"
            for chunk in chunks[:4]
        ) or "No sufficiently relevant narrative evidence was found."
        if route == "hybrid":
            facts = structured_answer(request.question, candidates, statuses, reasons)
            answer = f"Recorded facts: {facts}\n\nNarrative evidence: {narrative}"
        else:
            answer = narrative
    else:
        answer = structured_answer(request.question, candidates, statuses, reasons)
        if route == "audit":
            for row in rows:
                if row.elimination_reason and (row.vendor_name.casefold() in request.question.casefold() or row.vendor_id.casefold() in request.question.casefold()):
                    citations.append(PoolCitationOut(
                        vendor_id=row.vendor_id,
                        source_page=row.elimination_source_page,
                        clause_ref=row.elimination_clause_ref,
                        snippet=row.elimination_source_snippet or row.elimination_reason,
                    ))
    return PoolQueryResponse(route=route, answer=answer, citations=citations)


@router.get("/review/committee-report")
def committee_report(
    tender_id: str,
    fmt: str = Query(default="pdf", pattern="^(pdf|docx)$"),
    session: Session = Depends(get_db),
    _reviewer=Depends(reviewer_user),
):
    """Export the full status register and decision audit for a committee meeting."""
    from fastapi.responses import Response
    from app.review.export import export_docx, export_pdf

    notification_row = require_notification(session, tender_id)
    notification = to_notification_schema(notification_row)
    rows = list_submissions(session, notification_row.id)
    body = export_pdf(notification, rows) if fmt == "pdf" else export_docx(notification, rows)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", tender_id)[:100]
    return Response(
        content=body,
        media_type="application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="committee_{safe}.{fmt}"'},
    )


# Also before the greedy route below -- same reason as /submissions.
@router.get("/notifications/{tender_id:path}/corrigenda", response_model=list[CorrigendumOut])
def get_corrigenda(tender_id: str, session: Session = Depends(get_db)):
    """Every amendment filed against this tender, newest first.

    Not collapsed into one "current state": a tender amended twice was amended
    twice, and the audit trail (5.5) needs both. Superseding them into a single
    view is Part 2 work.
    """
    row = require_notification(session, tender_id)
    return [
        CorrigendumOut(
            corrigendum_id=c.corrigendum_id,
            parent_tender_id=c.parent_tender_id,
            issued_date=c.issued_date,
            source_file=c.source_file,
            uploaded_at=c.created_at,
            changed_fields=[
                ChangedFieldOut(
                    field_path=f.field_path,
                    label=_field_label(f.field_path),
                    old_value=f.old_value,
                    new_value=f.new_value,
                    clause_ref=f.clause_ref,
                    source_page=f.source_page,
                )
                for f in c.changed_fields
            ],
            applied=c.applied,
        )
        for c in sorted(row.corrigenda, key=lambda c: c.created_at, reverse=True)
    ]


def _field_label(field_path: str) -> str:
    if field_path.startswith("unmapped:"):
        return field_path.split(":", 1)[1]
    return FIELD_LABELS.get(field_path, field_path.replace("_", " ").replace(".", " — "))


# Declared last: {tender_id:path} matches anything, including the paths of the
# more specific routes above.
@router.get("/notifications/{tender_id:path}")
def get_notification(tender_id: str, session: Session = Depends(get_db)):
    """Full extracted Section 6 notification, provenance included."""
    return to_notification_schema(require_notification(session, tender_id))


# --------------------------------------------------------------------------- #
# Section 4.3 / 4.4 / 4.6 -- gap report
# --------------------------------------------------------------------------- #
@router.post("/gap-report", response_model=GapReportResponse)
def gap_report(
    request: GapReportRequest, session: Session = Depends(get_db), user=Depends(current_user)
) -> GapReportResponse:
    notification_row = require_notification(session, request.tender_id)
    submission_row = require_submission(session, request.tender_id, request.vendor_id)
    ensure_submission_access(user, submission_row)

    notification = to_notification_schema(notification_row)
    submission = to_submission_schema(submission_row)
    report = build_gap_report(notification, submission)

    quality = quality_for(notification_row, notification, submission_row, submission)

    # Stamped on the FIRST report and on an explicit re-check, never on every
    # read. Stamping on every read would clear the staleness banner the instant
    # it rendered -- exactly when the vendor has not yet acted on it.
    first_time = submission_row.last_gap_report_at is None
    if first_time or request.acknowledge_amendments:
        mark_report_generated(submission_row)
        session.commit()

    state = staleness_for(session, notification_row.id, submission_row)
    return GapReportResponse(
        report=report,
        verdict=report.verdict,
        counts=report.counts,
        data_quality=quality,
        action_counts=report.action_counts,
        sources=SourceDocuments(
            notification=notification_row.content_hash,
            bid=submission_row.content_hash,
        ),
        completion=CompletionOut(
            satisfied=report.completion.satisfied,
            total=report.completion.total,
            undetermined=report.completion.undetermined,
            label=report.completion.label,
            caveat=report.completion.caveat,
        ),
        staleness=StalenessOut(
            stale=state.stale,
            banner=state.banner,
            corrigendum_id=state.corrigendum_id,
            issued_date=state.issued_date,
            changed_fields=list(state.changed_fields),
            last_checked_at=state.last_checked_at,
        ),
    )


@router.post("/gap-report/export")
def export_gap_report(
    request: GapReportRequest,
    fmt: str = Query(default="pdf", pattern="^(pdf|docx)$"),
    session: Session = Depends(get_db),
    user=Depends(current_user),
):
    """Section 4.6 -- the report as a file the vendor can hand to their team.

    The people who actually attach the documents are usually not the person who
    ran the check, and a compliance report quoted from memory is how a
    requirement gets missed.

    Rebuilt from the stored rows rather than from anything the client posts, so
    an exported report cannot disagree with the one on screen.
    """
    from fastapi.responses import Response

    from app.compliance.export import ExportContext, export_docx, export_pdf

    notification_row = require_notification(session, request.tender_id)
    submission_row = require_submission(session, request.tender_id, request.vendor_id)
    ensure_submission_access(user, submission_row)
    notification = to_notification_schema(notification_row)
    submission = to_submission_schema(submission_row)
    report = build_gap_report(notification, submission)

    quality = quality_for(notification_row, notification, submission_row, submission)
    state = staleness_for(session, notification_row.id, submission_row)

    context = ExportContext(
        tender_title=notification.title,
        issuing_authority=notification.issuing_authority,
        submission_deadline=notification.submission_deadline,
        data_quality_banner=quality.banner,
        extracted_by=provider_label(quality),
        staleness_banner=state.banner,
    )

    from app.compliance.pdf_fonts import UnsupportedPDFText
    try:
        body = export_pdf(report, context) if fmt == "pdf" else export_docx(report, context)
    except UnsupportedPDFText as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{request.tender_id}_{request.vendor_id}")[:120]
    return Response(
        content=body,
        media_type=(
            "application/pdf" if fmt == "pdf"
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={"Content-Disposition": f'attachment; filename="compliance_{safe}.{fmt}"'},
    )


# --------------------------------------------------------------------------- #
# Section 4.5 -- RAG Q&A
# --------------------------------------------------------------------------- #
@router.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, session: Session = Depends(get_db), user=Depends(current_user)) -> AskResponse:
    notification_row = require_notification(session, request.tender_id)
    submission_row = None

    if request.vendor_id:
        submission_row = require_submission(session, request.tender_id, request.vendor_id)
        ensure_submission_access(user, submission_row)
        chunks = retrieve_for_pair(
            request.question,
            tender_id=request.tender_id,
            vendor_id=request.vendor_id,
            top_k=request.top_k,
        )
    else:
        chunks = retrieve(
            request.question,
            tender_id=request.tender_id,
            doc_kind=DocumentKind.NOTIFICATION,
            top_k=request.top_k,
        )

    answer = answer_question(request.question, chunks)
    return AskResponse(
        data_quality=quality_for(notification_row, to_notification_schema(notification_row),
                                 submission_row, to_submission_schema(submission_row) if submission_row else None),
        answer=answer,
        grounded=answer.is_grounded,
        confidence=answer.confidence.value,
        sources=SourceDocuments(
            notification=notification_row.content_hash,
            bid=submission_row.content_hash if submission_row is not None else None,
        ),
    )
