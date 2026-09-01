"""Phase 2 API routes (Part 1: the vendor tool)."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_notification, require_submission
from app.api.schemas import (
    AskRequest,
    AskResponse,
    GapReportRequest,
    GapReportResponse,
    HealthResponse,
    IngestResponse,
    NotificationSummary,
)
from app.compliance.gap import build_gap_report
from app.config import settings
from app.db.repository import (
    list_notifications,
    list_submissions,
    to_notification_schema,
    to_submission_schema,
)
from app.extraction import ingest_notification, ingest_submission
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


@router.post("/notifications", response_model=IngestResponse, status_code=201)
def upload_notification(file: UploadFile = File(...)) -> IngestResponse:
    """Section 4.1 -- ingest the official tender notification."""
    path = _save_upload(file)
    try:
        return _to_response(ingest_notification(path))
    except UnsupportedDocumentError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


@router.post("/submissions", response_model=IngestResponse, status_code=201)
def upload_submission(
    file: UploadFile = File(...),
    vendor_id: str = Form(...),
    tender_id: str = Form(...),
) -> IngestResponse:
    """Section 4.2 -- ingest a vendor's draft bid against a notification."""
    path = _save_upload(file)
    try:
        return _to_response(
            ingest_submission(path, vendor_id=vendor_id, tender_id=tender_id)
        )
    except UnsupportedDocumentError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Reading extracted data
# --------------------------------------------------------------------------- #
@router.get("/notifications", response_model=list[NotificationSummary])
def get_notifications(session: Session = Depends(get_db)) -> list[NotificationSummary]:
    return [
        NotificationSummary(
            tender_id=row.tender_id,
            title=row.title,
            issuing_authority=row.issuing_authority,
            sector=row.sector,
            submission_deadline=row.submission_deadline,
            emd_amount_inr=row.emd_amount_inr,
            eligibility_count=len(row.eligibility_criteria),
            document_count=len(row.mandatory_documents),
            submission_count=len(list_submissions(session, row.id)),
        )
        for row in list_notifications(session)
    ]


@router.get("/notifications/{tender_id:path}")
def get_notification(tender_id: str, session: Session = Depends(get_db)):
    """Full extracted Section 6 notification, provenance included."""
    return to_notification_schema(require_notification(session, tender_id))


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
