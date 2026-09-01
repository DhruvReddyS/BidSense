"""End-to-end ingestion: file -> parse -> extract -> Postgres + Qdrant.

The single entry point the API (Phase 2+) and the CLI both call, so there is one
definition of "a document has been ingested" rather than two that drift.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.db.session import session_scope
from app.extraction.graph import extract_notification, extract_submission
from app.extraction.persist import (
    index_notification,
    index_submission,
    save_notification,
    save_submission,
)
from app.ingest import parse_document
from app.llm import LLMProvider
from app.schemas.common import DocumentKind

logger = logging.getLogger(__name__)


@dataclass
class IngestReport:
    """What happened, in enough detail to debug a bad extraction after the fact
    and to feed Section 10's latency metric."""

    file_name: str
    doc_kind: DocumentKind
    row_id: uuid.UUID | None = None
    identifier: str | None = None          # tender_id or vendor_id
    pages: int = 0
    ocr_pages: int = 0
    chunks_indexed: int = 0
    parse_warnings: list[str] = field(default_factory=list)
    extraction_errors: list[str] = field(default_factory=list)
    node_timings: list[tuple[str, float]] = field(default_factory=list)
    parse_seconds: float = 0.0
    extract_seconds: float = 0.0
    persist_seconds: float = 0.0

    @property
    def total_seconds(self) -> float:
        return self.parse_seconds + self.extract_seconds + self.persist_seconds

    @property
    def ok(self) -> bool:
        return not self.extraction_errors and self.row_id is not None

    def summary(self) -> str:
        state = "OK" if self.ok else "PARTIAL"
        return (
            f"[{state}] {self.file_name}: {self.identifier} | {self.pages}p "
            f"({self.ocr_pages} OCR) | {self.chunks_indexed} chunks | "
            f"{self.total_seconds:.1f}s | {len(self.extraction_errors)} errors, "
            f"{len(self.parse_warnings)} warnings"
        )


def ingest_notification(
    path: str | Path,
    *,
    llm: LLMProvider | None = None,
    owner_user_id: uuid.UUID | None = None,
    index: bool = True,
) -> IngestReport:
    path = Path(path)
    report = IngestReport(file_name=path.name, doc_kind=DocumentKind.NOTIFICATION)

    started = time.perf_counter()
    document = parse_document(path, DocumentKind.NOTIFICATION)
    report.parse_seconds = time.perf_counter() - started
    report.pages = document.page_count
    report.ocr_pages = document.ocr_page_count
    report.parse_warnings = document.parse_warnings

    started = time.perf_counter()
    notification, result = extract_notification(document, llm=llm)
    report.extract_seconds = time.perf_counter() - started
    report.extraction_errors = result["errors"]
    report.node_timings = result["timings"]
    report.identifier = notification.tender_id

    started = time.perf_counter()
    with session_scope() as session:
        row = save_notification(
            session, notification, source_file=str(path), owner_user_id=owner_user_id
        )
        report.row_id = row.id
    if index:
        report.chunks_indexed = index_notification(document, notification, report.row_id)
    report.persist_seconds = time.perf_counter() - started

    logger.info(report.summary())
    return report


def ingest_submission(
    path: str | Path,
    *,
    vendor_id: str,
    tender_id: str | None = None,
    llm: LLMProvider | None = None,
    owner_user_id: uuid.UUID | None = None,
    index: bool = True,
) -> IngestReport:
    path = Path(path)
    report = IngestReport(file_name=path.name, doc_kind=DocumentKind.SUBMISSION)

    started = time.perf_counter()
    document = parse_document(path, DocumentKind.SUBMISSION)
    report.parse_seconds = time.perf_counter() - started
    report.pages = document.page_count
    report.ocr_pages = document.ocr_page_count
    report.parse_warnings = document.parse_warnings

    started = time.perf_counter()
    submission, result = extract_submission(
        document, vendor_id=vendor_id, tender_id=tender_id, llm=llm
    )
    report.extract_seconds = time.perf_counter() - started
    report.extraction_errors = result["errors"]
    report.node_timings = result["timings"]
    report.identifier = submission.vendor_id

    started = time.perf_counter()
    with session_scope() as session:
        row = save_submission(
            session, submission, source_file=str(path), owner_user_id=owner_user_id
        )
        report.row_id = row.id
        notification_id = row.notification_id
    if index:
        report.chunks_indexed = index_submission(
            document,
            submission,
            report.row_id,
            notification_id=notification_id,
            owner_user_id=owner_user_id,
        )
    report.persist_seconds = time.perf_counter() - started

    logger.info(report.summary())
    return report
