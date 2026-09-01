"""Format dispatch for document ingestion."""

from __future__ import annotations

from pathlib import Path

from app.ingest.models import ParsedDocument
from app.schemas.common import DocumentKind

SUPPORTED_SUFFIXES = {".pdf", ".docx"}


class UnsupportedDocumentError(ValueError):
    pass


def parse_document(
    path: str | Path,
    doc_kind: DocumentKind = DocumentKind.NOTIFICATION,
    **kwargs,
) -> ParsedDocument:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No such document: {path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from app.ingest.pdf import parse_pdf

        return parse_pdf(str(path), doc_kind, **kwargs)
    if suffix == ".docx":
        from app.ingest.docx import parse_docx

        return parse_docx(str(path), doc_kind)
    if suffix == ".doc":
        raise UnsupportedDocumentError(
            ".doc (legacy Word) is not supported; convert to .docx or PDF first"
        )
    raise UnsupportedDocumentError(
        f"Unsupported format {suffix!r}; expected one of {sorted(SUPPORTED_SUFFIXES)}"
    )
