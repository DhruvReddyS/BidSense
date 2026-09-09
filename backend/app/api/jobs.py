"""Background ingestion runner.

Uploads return a job id immediately and the extraction runs on a worker thread.
A thread pool rather than a task queue is a deliberate choice for this system's
scale: the work is I/O-bound (waiting on the LLM), the bottleneck is a free-tier
quota of a few requests per minute, and adding a broker would be infrastructure
without benefit. The job table is in Postgres, so swapping the executor for
Celery or RQ later is a change to this file only.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.db.models import IngestJob, JobKind, JobStatus
from app.db.session import session_scope
from app.config import settings
from app.extraction import ingest_corrigendum, ingest_notification, ingest_submission
from app.extraction.graph import (
    corrigendum_node_names,
    notification_node_names,
    vendor_node_names,
)
from app.documents import path_for

logger = logging.getLogger(__name__)

# Small on purpose. Concurrent extractions all contend for the same LLM quota,
# so more workers would not finish sooner -- they would just queue inside the
# rate limiter while holding database sessions open.
_executor = ThreadPoolExecutor(
    max_workers=settings.ingest_workers, thread_name_prefix="ingest"
)
_index_executor = ThreadPoolExecutor(
    max_workers=settings.index_workers, thread_name_prefix="vector-index"
)
_lock = threading.Lock()


# Which extractor set each job kind runs, so the progress bar's denominator is
# right for all three rather than assuming every job is a six-node notification.
_NODE_NAMES = {
    JobKind.NOTIFICATION: notification_node_names,
    JobKind.SUBMISSION: vendor_node_names,
    JobKind.CORRIGENDUM: corrigendum_node_names,
}


def create_job(
    kind: JobKind,
    file_name: str,
    *,
    tender_id: str | None = None,
    vendor_id: str | None = None,
    pages_total: int | None = None,
    owner_user_id: uuid.UUID | None = None,
    source_hash: str | None = None,
) -> uuid.UUID:
    steps = len(_NODE_NAMES[kind]())
    with session_scope() as session:
        job = IngestJob(
            kind=kind,
            status=JobStatus.QUEUED,
            file_name=file_name,
            source_hash=source_hash,
            tender_id=tender_id,
            vendor_id=vendor_id,
            pages_total=pages_total,
            steps_total=steps,
            stage="queued",
            owner_user_id=owner_user_id,
        )
        session.add(job)
        session.flush()
        return job.id


def _update(job_id: uuid.UUID, **fields) -> None:
    with session_scope() as session:
        job = session.get(IngestJob, job_id)
        if job is None:      # pragma: no cover - job deleted mid-run
            return
        for key, value in fields.items():
            setattr(job, key, value)


_STAGE_LABELS = {
    "header": "tender details and deadlines",
    "eligibility": "eligibility criteria",
    "documents": "required documents",
    "evaluation": "evaluation criteria",
    "technical": "technical requirements",
    "format_rules": "submission rules",
    "vendor_header": "bidder details",
    "turnover": "turnover figures",
    "certifications": "certifications",
    "past_projects": "past projects",
    "submitted_documents": "enclosed documents",
    "corrigendum_header": "amendment details",
    "corrigendum_changes": "what changed",
}


def _progress_callback(job_id: uuid.UUID):
    """Report extractor starts and completions.

    Completions alone leave the bar at 0% for the two minutes the first
    extractor can take under free-tier pacing, which reads as a hung request.
    Reporting starts lets the UI name what is in flight straight away.
    """
    state = {"done": 0, "running": set()}

    def report(node: str, event: str = "complete") -> None:
        with _lock:
            label = _STAGE_LABELS.get(node, node.replace("_", " "))
            if event == "start":
                state["running"].add(node)
                stage = f"reading {label}"
            else:
                state["done"] += 1
                state["running"].discard(node)
                remaining = sorted(state["running"])
                stage = (
                    f"reading {_STAGE_LABELS.get(remaining[0], remaining[0])}"
                    if remaining
                    else f"finished {label}"
                )
            _update(job_id, steps_done=state["done"], stage=stage)

    return report


_RUNNERS = {
    JobKind.NOTIFICATION: ingest_notification,
    JobKind.SUBMISSION: ingest_submission,
    JobKind.CORRIGENDUM: ingest_corrigendum,
}


def _run(job_id: uuid.UUID, kind: JobKind, path: Path, **kwargs) -> None:
    _update(
        job_id,
        status=JobStatus.RUNNING,
        stage="parsing document",
        started_at=datetime.now(timezone.utc),
    )
    try:
        runner = _RUNNERS[kind]
        report = _progress_callback(job_id)
        _update(job_id, stage="extracting")
        run_options = dict(kwargs)
        if kind in (JobKind.NOTIFICATION, JobKind.SUBMISSION):
            run_options["defer_index"] = settings.defer_vector_indexing
        result = runner(path, on_node_complete=report, **run_options)

        # A partial extraction is stored and flagged, never discarded: the
        # fields that did land are still worth reviewing.
        #
        # A run with no errors but implausible output is PARTIAL too. It is the
        # more dangerous of the two: nothing raised, so without this it reports
        # as a clean success while the notification has no deadline and no EMD.
        status = (
            JobStatus.PARTIAL
            if result.extraction_errors or result.needs_review
            else JobStatus.SUCCEEDED
        )
        _update(
            job_id,
            status=status,
            stage="done",
            steps_done=result_steps(result),
            row_id=result.row_id,
            tender_id=(
                result.identifier
                if kind is JobKind.NOTIFICATION
                else kwargs.get("tender_id")
            ),
            result={
                "ok": result.ok,
                "identifier": result.identifier,
                "pages": result.pages,
                "ocr_pages": result.ocr_pages,
                "chunks_indexed": result.chunks_indexed,
                "parse_warnings": result.parse_warnings,
                "extraction_errors": result.extraction_errors,
                "extracted_by": result.extracted_by,
                "from_cache": result.from_cache,
                "content_hash": result.content_hash,
                "timing": {
                    "parse": round(result.parse_seconds, 2),
                    "extract": round(result.extract_seconds, 2),
                    "persist": round(result.persist_seconds, 2),
                    "index": round(result.index_seconds, 2),
                },
                "index_state": "pending" if result.index_deferred else "ready",
                "validation_summary": result.validation_summary,
                "validation": [
                    {
                        "field": f.field,
                        "severity": f.severity.value,
                        "message": f.message,
                        "value": f.value,
                    }
                    for f in result.validation
                ],
                "seconds": round(result.total_seconds, 2),
                # Keep the review SLA immutable when deferred semantic indexing
                # later adds its own elapsed time to the end-to-end receipt.
                "decision_ready_seconds": round(result.total_seconds, 2),
                "node_timings": {k: round(v, 2) for k, v in result.node_timings},
            },
            finished_at=datetime.now(timezone.utc),
        )
        if result._index_task is not None:
            _index_executor.submit(_finish_index, job_id, result._index_task)
        logger.info("job %s finished: %s", job_id, status)
    except Exception as exc:
        logger.exception("job %s failed", job_id)
        _update(
            job_id,
            status=JobStatus.FAILED,
            stage="failed",
            error=_explain(exc),
            finished_at=datetime.now(timezone.utc),
        )
    finally:
        # The upload was written to a temp directory; it is not needed once the
        # text is extracted and indexed.
        shutil.rmtree(path.parent, ignore_errors=True)


def _finish_index(job_id: uuid.UUID, task) -> None:
    """Build Level-3 search after Level-1 structured review is already ready."""
    started = datetime.now(timezone.utc)
    try:
        chunks = task()
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        with session_scope() as session:
            job = session.get(IngestJob, job_id)
            if job is None or job.result is None:
                return
            result = dict(job.result)
            timing = dict(result.get("timing") or {})
            timing["index"] = round(elapsed, 2)
            result.update(
                chunks_indexed=chunks,
                index_state="ready",
                timing=timing,
                seconds=round(float(result.get("seconds") or 0) + elapsed, 2),
            )
            job.result = result
    except Exception as exc:  # structured facts remain valid and reviewable
        logger.exception("deferred indexing failed for job %s", job_id)
        with session_scope() as session:
            job = session.get(IngestJob, job_id)
            if job is not None and job.result is not None:
                result = dict(job.result)
                result["index_state"] = "failed"
                result["index_error"] = f"{type(exc).__name__}: {exc}"
                job.result = result


# Failures a user can actually act on, translated from the exception text.
# Anything unmatched keeps the traceback, which is what a developer needs.
_KNOWN_FAILURES: list[tuple[str, str]] = [
    (
        "uq_vendor_per_tender",
        "A bid with this reference is already recorded against this tender. "
        "Wait for the earlier upload to finish, or use a different reference.",
    ),
    (
        "every configured model has exhausted",
        "The daily free-tier quota is spent on every configured model. Wait for "
        "the quota to reset, add more models to GEMINI_FALLBACK_MODELS, or "
        "switch LLM_PROVIDER to ollama.",
    ),
    (
        "cut off at the output token limit",
        "The document produced more content than fits in one model response. "
        "Raise LLM_MAX_OUTPUT_TOKENS, or narrow the page selection for the "
        "affected section.",
    ),
    (
        "PERMISSION_DENIED",
        "The language model rejected the API key. Check GEMINI_API_KEY, or "
        "switch LLM_PROVIDER to ollama.",
    ),
    (
        "to amend. Upload the original",
        "This corrigendum names a tender that has not been uploaded yet. Upload "
        "the original notification first, then the corrigendum.",
    ),
    (
        "Unsupported format",
        "That file type cannot be read. Upload a PDF or DOCX.",
    ),
]


def _explain(exc: Exception) -> str:
    """A message the person who uploaded the file can act on.

    A raw IntegrityError with a database traceback tells a bidder nothing about
    what to do next, and these failure modes are all recoverable by the user.
    """
    text = str(exc)
    for marker, message in _KNOWN_FAILURES:
        if marker in text:
            return message
    return f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"


def result_steps(result) -> int:
    return len(result.node_timings)


def submit(job_id: uuid.UUID, kind: JobKind, path: Path, **kwargs) -> None:
    """Queue the extraction. Falls back to running inline if the pool is gone.

    The fallback matters during interpreter shutdown (and in tests): dropping
    the work silently would leave a job stuck in QUEUED for ever.
    """
    try:
        _executor.submit(_run, job_id, kind, path, **kwargs)
    except RuntimeError:
        logger.warning("executor unavailable; running job %s inline", job_id)
        _run(job_id, kind, path, **kwargs)


def run_inline(job_id: uuid.UUID, kind: JobKind, path: Path, **kwargs) -> None:
    """Run a job on the calling thread. Used by tests to keep them deterministic."""
    _run(job_id, kind, path, **kwargs)


# A job that has not finished in this long is stuck, whatever the cause. Six
# extractors at the free tier's pace take about three minutes; twenty is well
# past any legitimate run, including retries and model failover.
STALE_AFTER_SECONDS = 20 * 60


def fail_if_stuck(job: IngestJob) -> bool:
    """Mark a job failed if it has clearly hung. Returns True if it did.

    Called when a job is read, so a stuck job surfaces to whoever is watching it
    rather than showing RUNNING for ever. The startup reaper only catches jobs
    orphaned by a restart; this catches the ones whose process is still alive
    but wedged.
    """
    if job.is_terminal or job.started_at is None:
        return False
    age = (datetime.now(timezone.utc) - job.started_at).total_seconds()
    if age < STALE_AFTER_SECONDS:
        return False

    job.status = JobStatus.FAILED
    job.stage = "timed out"
    job.error = (
        f"This job stopped making progress after {int(age // 60)} minutes and was "
        "marked failed. It reached "
        f"{job.steps_done}/{job.steps_total or '?'} sections. Re-upload the file; "
        "if it happens again the document may be too large for the current "
        "extraction budget."
    )
    job.finished_at = datetime.now(timezone.utc)
    logger.warning("job %s marked failed after %.0fs without finishing", job.id, age)
    return True


# Finished jobs older than this are removed at startup. They are an audit trail
# of uploads, not of decisions -- the extracted data itself is the record that
# matters -- so keeping them for ever grows a table nothing reads.
JOB_RETENTION_DAYS = 30


def purge_old_jobs() -> int:
    """Delete finished jobs past the retention window."""
    from datetime import timedelta

    from sqlalchemy import delete

    cutoff = datetime.now(timezone.utc) - timedelta(days=JOB_RETENTION_DAYS)
    with session_scope() as session:
        result = session.execute(
            delete(IngestJob).where(
                IngestJob.status.in_(
                    [JobStatus.SUCCEEDED, JobStatus.PARTIAL, JobStatus.FAILED]
                ),
                IngestJob.created_at < cutoff,
            )
        )
        return result.rowcount or 0


def reap_stale_jobs() -> int:
    """Mark jobs abandoned by a restart as failed.

    Without this a process kill leaves rows stuck in RUNNING for ever, and the
    UI polls them until the user gives up. Called once at startup.
    """
    from sqlalchemy import select

    with session_scope() as session:
        stale = session.scalars(
            select(IngestJob).where(
                IngestJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING])
            )
        ).all()
        for job in stale:
            job.status = JobStatus.FAILED
            job.stage = "interrupted"
            job.error = "The server restarted while this job was running. Re-upload the file."
            job.finished_at = datetime.now(timezone.utc)
        return len(stale)


def recover_interrupted_jobs() -> tuple[int, int]:
    """Replay restart-interrupted jobs from their immutable stored source.

    The `claimed:` stage prevents two API replicas starting together from
    dispatching the same row. Old rows created before source retention remain
    visible failures because their bytes genuinely cannot be recovered.
    """
    from sqlalchemy import and_, or_, select

    recovered: list[tuple[uuid.UUID, JobKind, Path, dict]] = []
    failed = 0
    claim = uuid.uuid4().hex
    with session_scope() as session:
        jobs = session.scalars(
            select(IngestJob)
            .where(
                IngestJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                or_(
                    IngestJob.stage.is_(None),
                    ~IngestJob.stage.startswith("claimed:"),
                    and_(
                        IngestJob.stage.startswith("claimed:"),
                        IngestJob.started_at < datetime.now(timezone.utc) - timedelta(seconds=STALE_AFTER_SECONDS),
                    ),
                ),
            )
            .with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            source = path_for(job.source_hash or "")
            if source is None:
                job.status = JobStatus.FAILED
                job.stage = "interrupted"
                job.error = (
                    "The server restarted and the source file was not retained. "
                    "Re-upload this document once; future restarts are recoverable."
                )
                job.finished_at = datetime.now(timezone.utc)
                failed += 1
                continue
            folder = Path(tempfile.mkdtemp(prefix="bidsense-recover-"))
            restored = folder / Path(job.file_name).name
            shutil.copyfile(source, restored)
            kwargs = {"owner_user_id": job.owner_user_id}
            if job.kind is JobKind.SUBMISSION:
                kwargs.update(vendor_id=job.vendor_id, tender_id=job.tender_id)
            elif job.kind is JobKind.CORRIGENDUM:
                kwargs = {"tender_id": job.tender_id}
            job.status = JobStatus.RUNNING
            job.stage = f"claimed:{claim}"
            job.started_at = datetime.now(timezone.utc)
            job.finished_at = None
            job.error = None
            recovered.append((job.id, job.kind, restored, kwargs))
    for job_id, kind, restored, kwargs in recovered:
        submit(job_id, kind, restored, **kwargs)
    return len(recovered), failed
