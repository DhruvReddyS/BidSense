"""Content-addressed store for the documents we extracted from.

Until now the uploaded file was deleted as soon as its text had been extracted.
That was reasonable while a citation was only a label -- "page 5, clause 1.1" --
but a citation the vendor can click through to the page it came from needs the
page to still exist.

Keyed by SHA-256 of the bytes, the same key the extraction cache uses, so the
same tender uploaded as `NIT_final.pdf` and `NIT_final(1).pdf` is stored once
and both rows point at it.

Deliberately a directory of files rather than bytes in Postgres: these are
50MB PDFs, they are read whole and served whole, and a filesystem does that
better than a large-object column. The row keeps the hash, not the blob.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

__all__ = ["store_document", "path_for", "content_hash", "is_stored"]

_CHUNK = 1 << 20


def content_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(_CHUNK):
            digest.update(block)
    return digest.hexdigest()


def _root() -> Path:
    root = Path(settings.document_store_path)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(digest: str, suffix: str) -> Path:
    # Sharded two levels deep. A flat directory of tens of thousands of files is
    # slow to list on every filesystem worth naming.
    return _root() / digest[:2] / digest[2:4] / f"{digest}{suffix}"


def store_document(path: str | Path, *, digest: str | None = None) -> str:
    """Copy a document into the store and return its hash.

    Copies rather than moves: the caller's file may be a temp upload it still
    intends to read, or a file in `data/` that belongs to the repository.
    Storing the same bytes twice is a no-op.
    """
    path = Path(path)
    digest = digest or content_hash(path)
    target = _path(digest, path.suffix.lower())
    if target.exists():
        return digest

    target.parent.mkdir(parents=True, exist_ok=True)
    # Written beside the target and renamed, so a crash mid-copy cannot leave a
    # truncated file that looks complete to every later reader.
    staging = target.with_suffix(target.suffix + ".part")
    shutil.copyfile(path, staging)
    staging.replace(target)
    logger.info("stored %s as %s", path.name, digest[:12])
    return digest


def path_for(digest: str) -> Path | None:
    """The stored file for a hash, whatever its extension."""
    if not digest or len(digest) != 64 or not digest.isalnum():
        return None
    folder = _root() / digest[:2] / digest[2:4]
    if not folder.is_dir():
        return None
    for candidate in folder.glob(f"{digest}.*"):
        if candidate.suffix != ".part":
            return candidate
    return None


def is_stored(digest: str) -> bool:
    return path_for(digest) is not None
