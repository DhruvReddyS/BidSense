"""Phase 2 API routes (Part 1: the vendor tool)."""

from __future__ import annotations

import logging
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
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_notification, require_submission
from app.api import jobs as job_runner
from app.api.schemas import (
    AskRequest,
    AskResponse,
    GapReportRequest,
    GapReportResponse,
    HealthResponse,
    JobAccepted,
    JobStatusResponse,
    NotificationList,
    NotificationSummary,
    Page,
)
from app.db.models import IngestJob, JobKind
from app.compliance.gap import build_gap_report
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # tender PDFs are large but not unbounded


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
    try:
        from app.vector.embeddings import get_model

        get_model()
        embeddings = True
    except Exception as exc:
        logger.warning("embeddings unavailable: %s", exc)
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
    )


def _accept(job_id, file_name: str) -> JobAccepted:
    return JobAccepted(
        job_id=str(job_id),
        status="queued",
        file_name=file_name,
        poll_url=f"/api/jobs/{job_id}",
    )


@router.post("/notifications", response_model=JobAccepted, status_code=202)
def upload_notification(file: UploadFile = File(...)) -> JobAccepted:
    """Section 4.1 -- ingest the official tender notification.

    Returns 202 immediately; poll `poll_url` for progress.
    """
    path = _save_upload(file)
    try:
        job_id = job_runner.create_job(JobKind.NOTIFICATION, path.name)
        job_runner.submit(job_id, JobKind.NOTIFICATION, path)
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
) -> JobAccepted:
    """Section 4.2 -- ingest a vendor's draft bid against a notification."""
    # Validated before the job is queued: a bid filed against a tender that does
    # not exist would otherwise fail three minutes later with nothing useful to
    # tell the user.
    require_notification(session, tender_id)

    path = _save_upload(file)
    try:
        job_id = job_runner.create_job(
            JobKind.SUBMISSION, path.name, tender_id=tender_id, vendor_id=vendor_id
        )
        job_runner.submit(
            job_id, JobKind.SUBMISSION, path, vendor_id=vendor_id, tender_id=tender_id
        )
    except Exception:
        shutil.rmtree(path.parent, ignore_errors=True)
        raise
    return _accept(job_id, path.name)


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
def get_submissions(tender_id: str, session: Session = Depends(get_db)):
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
    request: GapReportRequest, session: Session = Depends(get_db)
) -> GapReportResponse:
    notification_row = require_notification(session, request.tender_id)
    submission_row = require_submission(session, request.tender_id, request.vendor_id)

    report = build_gap_report(
        to_notification_schema(notification_row),
        to_submission_schema(submission_row),
    )
    return GapReportResponse(
        report=report, verdict=report.verdict, counts=report.counts
    )


# --------------------------------------------------------------------------- #
# Section 4.5 -- RAG Q&A
# --------------------------------------------------------------------------- #
@router.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, session: Session = Depends(get_db)) -> AskResponse:
    require_notification(session, request.tender_id)

    if request.vendor_id:
        require_submission(session, request.tender_id, request.vendor_id)
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
    return AskResponse(answer=answer, grounded=answer.is_grounded)
