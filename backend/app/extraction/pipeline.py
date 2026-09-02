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
from app.extraction.validate import (
    Finding,
    affects_confidence,
    summarise,
    validate_notification,
    validate_submission,
)
from app.ingest import parse_document
from app.llm import LLMProvider
from app.schemas.common import DocumentKind

logger = logging.getLogger(__name__)


def _provider_label(llm: "LLMProvider | None") -> str:
    """Name the model that produced an extraction.

    Worth recording because the failure this enables is provider-shaped: the
    same 101-page tender yields a full header from gemini-3.5-flash and an empty
    one from a local qwen3:4b, both reporting zero errors. Without this, the
    only evidence of which ran is the wall-clock time.
    """
    from app.llm import get_llm

    provider = llm or get_llm()
    model = getattr(provider, "_model", None)
    return f"{provider.name}:{model}" if model else provider.name


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
    #: Plausibility findings (Section 10). Distinct from `extraction_errors`:
    #: those are nodes that FAILED, these are nodes that succeeded and returned
    #: something that cannot be right, or returned nothing where a value was
    #: expected. A run with no errors and six findings is the dangerous case --
    #: it reports as a clean success.
    validation: list[Finding] = field(default_factory=list)
    #: Which provider and model produced this. Degraded output is only
    #: attributable if we record what produced it.
    extracted_by: str | None = None
    parse_seconds: float = 0.0
    extract_seconds: float = 0.0
    persist_seconds: float = 0.0

    @property
    def total_seconds(self) -> float:
        return self.parse_seconds + self.extract_seconds + self.persist_seconds

    @property
    def ok(self) -> bool:
        return not self.extraction_errors and self.row_id is not None

    @property
    def needs_review(self) -> bool:
        """True when the run succeeded but produced something implausible.

        `ok` deliberately stays True for these -- the rows were written and are
        worth reading. But a caller that only looks at `ok` would present a
        notification missing its deadline, its EMD and its issuing authority as
        a clean extraction, which is how this failure stayed invisible.
        """
        return affects_confidence(self.validation)

    @property
    def validation_summary(self) -> str | None:
        return summarise(self.validation)

    def summary(self) -> str:
        state = "OK" if self.ok else "PARTIAL"
        return (
            f"[{state}] {self.file_name}: {self.identifier} | {self.pages}p "
            f"({self.ocr_pages} OCR) | {self.chunks_indexed} chunks | "
            f"{self.total_seconds:.1f}s | {len(self.extraction_errors)} errors, "
            f"{len(self.parse_warnings)} warnings, "
            f"{len(self.validation)} validation finding(s)"
        )


def ingest_notification(
    path: str | Path,
    *,
    llm: LLMProvider | None = None,
    owner_user_id: uuid.UUID | None = None,
    index: bool = True,
    on_node_complete=None,
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
    notification, result = extract_notification(
        document, llm=llm, on_node_complete=on_node_complete
    )
    report.extract_seconds = time.perf_counter() - started
    report.extraction_errors = result["errors"]
    report.node_timings = result["timings"]
    report.identifier = notification.tender_id
    report.extracted_by = _provider_label(llm)
    # Run BEFORE persisting, so the findings describe exactly what was stored.
    report.validation = validate_notification(notification, document)

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
    on_node_complete=None,
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
        document,
        vendor_id=vendor_id,
        tender_id=tender_id,
        llm=llm,
        on_node_complete=on_node_complete,
    )
    report.extract_seconds = time.perf_counter() - started
    report.extraction_errors = result["errors"]
    report.node_timings = result["timings"]
    report.identifier = submission.vendor_id
    report.extracted_by = _provider_label(llm)
    report.validation = validate_submission(submission, document)

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


def ingest_corrigendum(
    path: str | Path,
    *,
    tender_id: str,
    llm: LLMProvider | None = None,
    on_node_complete=None,
) -> IngestReport:
    """Section 5.6 (Part 1 slice): amend an already-extracted notification.

    The parent must already be in the database -- an amendment to a tender we
    have never read cannot be diffed against anything, and storing it anyway
    would produce a staleness banner naming changes we could not describe.
    """
    from app.corrigendum.staleness import Staleness  # noqa: F401  (documents intent)
    from app.db.repository import to_notification_schema
    from app.db.models import TenderNotificationRow
    from app.extraction.graph import extract_corrigendum
    from app.extraction.persist import save_corrigendum
    from sqlalchemy import select

    path = Path(path)
    report = IngestReport(file_name=path.name, doc_kind=DocumentKind.NOTIFICATION)

    started = time.perf_counter()
    document = parse_document(path, DocumentKind.NOTIFICATION)
    report.parse_seconds = time.perf_counter() - started
    report.pages = document.page_count
    report.ocr_pages = document.ocr_page_count
    report.parse_warnings = document.parse_warnings

    with session_scope() as session:
        row = session.scalar(
            select(TenderNotificationRow).where(
                TenderNotificationRow.tender_id == tender_id
            )
        )
        if row is None:
            raise ValueError(
                f"No notification {tender_id!r} to amend. Upload the original "
                "tender before its corrigendum."
            )
        parent = to_notification_schema(row)

    started = time.perf_counter()
    corrigendum, result = extract_corrigendum(
        document, parent, llm=llm, on_node_complete=on_node_complete
    )
    report.extract_seconds = time.perf_counter() - started
    report.extraction_errors = result["errors"]
    report.node_timings = result["timings"]
    report.identifier = corrigendum.corrigendum_id

    started = time.perf_counter()
    with session_scope() as session:
        notification_row = session.scalar(
            select(TenderNotificationRow).where(
                TenderNotificationRow.tender_id == tender_id
            )
        )
        saved = save_corrigendum(
            session, corrigendum, notification_row, source_file=str(path)
        )
        report.row_id = saved.id
    report.persist_seconds = time.perf_counter() - started

    # Not indexed into Qdrant. A corrigendum's text is short and its substance is
    # the structured diff; chunking it would put amendment prose into retrieval
    # alongside the clauses it amends, and a RAG answer citing both would read as
    # a contradiction rather than a correction. Surfacing amendments in Q&A is
    # Part 2 work and needs supersession handling, not just more chunks.
    report.chunks_indexed = 0

    logger.info(report.summary())
    return report
