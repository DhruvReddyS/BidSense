"""Phase 1 document ingestion: parse -> pages -> chunks, with page provenance intact."""

from app.ingest.chunking import Chunk, chunk_document, chunk_text
from app.ingest.loader import UnsupportedDocumentError, parse_document
from app.ingest.models import ExtractionMethod, PageText, ParsedDocument
from app.ingest.ocr import missing_dependencies, ocr_available

__all__ = [
    "Chunk",
    "ExtractionMethod",
    "PageText",
    "ParsedDocument",
    "UnsupportedDocumentError",
    "chunk_document",
    "chunk_text",
    "missing_dependencies",
    "ocr_available",
    "parse_document",
]
