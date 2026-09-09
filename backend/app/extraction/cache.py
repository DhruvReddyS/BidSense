"""Look up and store extractions by document content hash.

The saving is the whole daily budget, not a few seconds: six requests per
document against a free tier of twenty per model per day means one accidental
re-upload costs almost a third of a model's quota. During a demo the same three
notifications get uploaded again and again.

Two things make this safe rather than merely fast:

  CONTENT KEY     the hash is of the file bytes. The same tender arrives as
                  `NIT_final.pdf`, `NIT_final(1).pdf` and `tender.pdf`; a
                  filename key misses all three.
  VERSION KEY     a digest of the extraction code -- prompts, LLM output
                  schemas, converters, graph. Changing a prompt is how this
                  system changes what it extracts, so an entry written by an
                  older prompt is not a hit. It would be a silently stale
                  answer, which is worse than paying for the call.

What is deliberately NOT cached: persistence. A cache hit still writes rows and
chunks, because the same bid can be filed against a different tender and the
same tender re-extracted under a different owner. Only the model calls are
skipped.
"""

from __future__ import annotations

import hashlib
import logging
import time
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from app.db.models.cache import ExtractionCacheRow
from app.db.session import session_scope
from app.schemas.common import DocumentKind

logger = logging.getLogger(__name__)

__all__ = [
    "content_hash",
    "pipeline_version",
    "lookup",
    "store",
    "CacheHit",
]

# Files whose source defines what an extraction produces. Any edit to these
# changes the answer, so any edit must invalidate the cache.
_VERSIONED_MODULES = (
    "app/extraction/prompts.py",
    "app/extraction/llm_schemas.py",
    "app/extraction/convert.py",
    "app/extraction/graph.py",
    "app/extraction/selection.py",
    "app/normalize/money.py",
    "app/schemas/common.py",
    "app/schemas/notification.py",
    "app/schemas/submission.py",
    "app/ingest/loader.py",
    "app/ingest/models.py",
    "app/ingest/pdf.py",
    "app/ingest/docx.py",
    "app/ingest/ocr.py",
)

_CHUNK = 1 << 20


@contextmanager
def extraction_lock(digest: str, doc_kind: DocumentKind, *, timeout: float = 600):
    """Coalesce identical extraction work across workers on this host.

    Keep the lock file: unlinking it allows old and new callers to lock
    different inodes for the same document. No database connection is held
    while waiting on a model. Cache lookup must happen INSIDE this context.
    An unavailable lock only loses the optimization; extraction still runs.
    """
    import fcntl
    from app.config import settings

    handle = None
    locked = False
    try:
        key = hashlib.sha256(f"{digest}:{doc_kind.value}:{pipeline_version()}".encode()).hexdigest()
        folder = Path(settings.document_store_path) / ".extraction-locks"
        folder.mkdir(parents=True, exist_ok=True)
        handle = (folder / f"{key}.lock").open("a")
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    logger.warning("extraction lock wait timed out; extracting independently")
                    break
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    except OSError as exc:
        logger.warning("extraction lock unavailable; extracting independently: %s", exc)
    try:
        yield
    finally:
        if handle is not None:
            try:
                if locked:
                    fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                handle.close()


def content_hash(path: str | Path) -> str:
    """SHA-256 of the file's bytes, streamed so a 50MB PDF is not held in RAM."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(_CHUNK):
            digest.update(block)
    return digest.hexdigest()


def digest_of(paths: list[Path]) -> str:
    """Short digest of a set of files' bytes. Split out so it is testable
    without editing the repository's own source."""
    digest = hashlib.sha256()
    for path in paths:
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:32]


@lru_cache(maxsize=1)
def pipeline_version() -> str:
    """A short digest of the code that decides what an extraction contains.

    Computed from source rather than from a hand-maintained constant, because a
    constant someone forgets to bump is exactly how a stale cache entry gets
    served -- and the failure would be invisible: a perfectly well-formed
    extraction produced by a prompt that no longer exists.
    """
    root = Path(__file__).resolve().parents[2]
    return digest_of([root / relative for relative in _VERSIONED_MODULES])


class CacheHit:
    """A stored extraction, with what is needed to report it honestly."""

    __slots__ = ("payload", "model", "stored_at", "hits")

    def __init__(self, payload: dict, model: str | None, stored_at, hits: int):
        self.payload = payload
        self.model = model
        self.stored_at = stored_at
        self.hits = hits


def lookup(digest: str, doc_kind: DocumentKind) -> CacheHit | None:
    """Return a previous extraction of these exact bytes, if one is current."""
    try:
        with session_scope() as session:
            row = session.scalar(
                update(ExtractionCacheRow).where(
                    ExtractionCacheRow.content_hash == digest,
                    ExtractionCacheRow.doc_kind == doc_kind.value,
                    ExtractionCacheRow.pipeline_version == pipeline_version(),
                ).values(hits=ExtractionCacheRow.hits + 1).returning(ExtractionCacheRow)
            )
            if row is None:
                return None
            return CacheHit(row.payload, row.model, row.created_at, row.hits)
    except Exception as exc:
        # A cache that cannot be read must never stop an extraction. The cost of
        # a miss is an API call; the cost of raising here is a failed upload.
        logger.warning("extraction cache unavailable, extracting normally: %s", exc)
        return None


def store(
    digest: str,
    doc_kind: DocumentKind,
    payload: dict,
    *,
    model: str | None = None,
    source_file: str | None = None,
) -> None:
    """Record an extraction. Failures here are logged, never raised."""
    try:
        with session_scope() as session:
            # The unique key arbitrates races in the database, including
            # separate worker processes. Never overwrite the winning payload
            # or its provenance with a later writer's model label.
            session.execute(
                insert(ExtractionCacheRow).values(
                    content_hash=digest,
                    doc_kind=doc_kind.value,
                    pipeline_version=pipeline_version(),
                    payload=payload,
                    model=model,
                    source_file=source_file,
                ).on_conflict_do_nothing(constraint="uq_extraction_cache_key")
            )
    except Exception as exc:
        logger.warning("could not cache extraction: %s", exc)
