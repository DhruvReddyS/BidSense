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
from app.documents import store_document
from app.extraction import cache as extraction_cache
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
from app.schemas.notification import TenderNotification
from app.schemas.submission import VendorSubmission

logger = logging.getLogger(__name__)


def _safe_store_document(path: Path, digest: str) -> None:
    """Keeping the source must never break ingestion. A citation that cannot be
    opened is a degraded feature; a failed upload is a lost document."""
    try:
        store_document(path, digest=digest)
    except Exception as exc:      # noqa: BLE001 - deliberately broad
        logger.warning("could not retain %s for citation click-through: %s", path.name, exc)


def _safe_lookup(digest: str, kind: DocumentKind):
    """Cache reads must never be load-bearing.

    `cache.lookup` already swallows a database failure, but this is an
    optimisation and the guarantee should not depend on the optimisation being
    bug-free. The cost of a miss is an API call; the cost of raising here is a
    failed upload of a document that extracted perfectly well.
    """
    try:
        return extraction_cache.lookup(digest, kind)
    except Exception as exc:      # noqa: BLE001 - deliberately broad
        logger.warning("extraction cache lookup failed, extracting normally: %s", exc)
        return None


def _safe_store(digest: str, kind: DocumentKind, payload: dict, **kwargs) -> None:
    try:
        extraction_cache.store(digest, kind, payload, **kwargs)
    except Exception as exc:      # noqa: BLE001 - deliberately broad
        logger.warning("could not cache extraction: %s", exc)


def _provider_label(llm: "LLMProvider | None") -> str:
    """Name the model that produced an extraction.

    Worth recording because a run served by a different tier is a different run,
    and nothing else in the report says which one answered. Not because the local
    tier is weaker -- with few-shot prompting all three tiers extract the same
    101-page tender at 6/6 -- but because latency, quota and failure modes differ
    per tier, and "which tier produced this" is the first question when a result
    looks wrong.
    """
    from app.llm import get_llm

    provider = llm or get_llm()
    # The chain knows which TIER answered, which is the thing worth recording --
    # "chain" alone would hide a run that fell through to the local model.
    active = getattr(provider, "active_provider", None)
    if active:
        return active
    model = getattr(provider, "last_model_used", None) or getattr(provider, "_model", None)
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
    #: True when the LLM was not called because these exact bytes had already
    #: been extracted. Reported rather than hidden: a cache hit inherits the
    #: quality of whatever wrote the entry, including a local fallback model.
    from_cache: bool = False
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
        cached = " [cached]" if self.from_cache else ""
        return (
            f"[{state}]{cached} {self.file_name}: {self.identifier} | {self.pages}p "
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
    use_cache: bool = True,
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
    digest = extraction_cache.content_hash(path)
    # Retained here, before the worker deletes the temp upload. A citation that
    # cannot be opened at its page is a label the vendor has to take on trust.
    _safe_store_document(path, digest)
    hit = _safe_lookup(digest, DocumentKind.NOTIFICATION) if use_cache else None

    if hit is not None:
        # Six LLM requests skipped. Against a free tier of twenty per model per
        # day, one accidental re-upload of a tender is nearly a third of a
        # model's quota -- and during a demo the same file gets uploaded again
        # and again.
        notification = TenderNotification.model_validate(hit.payload)
        result = {"errors": [], "timings": [], "parse_warnings": document.parse_warnings}
        report.from_cache = True
        report.extracted_by = hit.model
        logger.info(
            "cache hit for %s (extracted by %s, served %d time(s))",
            path.name, hit.model, hit.hits,
        )
    else:
        notification, result = extract_notification(
            document, llm=llm, on_node_complete=on_node_complete
        )
        report.extracted_by = _provider_label(llm)
        if use_cache and not result["errors"]:
            # Only a clean extraction is cached. Storing a partial one would
            # make a transient API failure permanent for those bytes.
            _safe_store(
                digest, DocumentKind.NOTIFICATION, notification.model_dump(mode="json"),
                model=report.extracted_by, source_file=path.name,
            )

    report.extract_seconds = time.perf_counter() - started
    report.extraction_errors = result["errors"]
    report.node_timings = result["timings"]
    report.identifier = notification.tender_id
    # Run BEFORE persisting, so the findings describe exactly what was stored.
    # The pages the model actually read, so the pattern backstop answers the
    # same question the model was asked. Searching pages it never saw would
    # produce "the regex found it and you didn't" for text never in front of it.
    from app.extraction.selection import select_pages

    try:
        _, header_pages = select_pages(document, "header")
    except Exception:
        header_pages = None
    report.validation = validate_notification(
        notification, document, selected_pages=header_pages
    )

    started = time.perf_counter()
    with session_scope() as session:
        row = save_notification(
            session, notification, source_file=str(path),
            owner_user_id=owner_user_id, content_hash=digest,
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
    use_cache: bool = True,
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
    digest = extraction_cache.content_hash(path)
    _safe_store_document(path, digest)
    hit = _safe_lookup(digest, DocumentKind.SUBMISSION) if use_cache else None

    if hit is not None:
        submission = VendorSubmission.model_validate(hit.payload)
        # The cached extraction is of the DOCUMENT; who is filing it and against
        # which tender are arguments, not content. The same bid PDF can legitimately
        # be filed by a different vendor id or against a different tender, so these
        # are re-applied rather than restored from the entry.
        submission.vendor_id = vendor_id
        submission.tender_id = tender_id
        result = {"errors": [], "timings": [], "parse_warnings": document.parse_warnings}
        report.from_cache = True
        report.extracted_by = hit.model
        logger.info("cache hit for %s (extracted by %s)", path.name, hit.model)
    else:
        submission, result = extract_submission(
            document,
            vendor_id=vendor_id,
            tender_id=tender_id,
            llm=llm,
            on_node_complete=on_node_complete,
        )
        report.extracted_by = _provider_label(llm)
        if use_cache and not result["errors"]:
            _safe_store(
                digest, DocumentKind.SUBMISSION, submission.model_dump(mode="json"),
                model=report.extracted_by, source_file=path.name,
            )

    report.extract_seconds = time.perf_counter() - started
    report.extraction_errors = result["errors"]
    report.node_timings = result["timings"]
    report.identifier = submission.vendor_id
    report.validation = validate_submission(submission, document)

    started = time.perf_counter()
    with session_scope() as session:
        row = save_submission(
            session, submission, source_file=str(path),
            owner_user_id=owner_user_id, content_hash=digest,
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
