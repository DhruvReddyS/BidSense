"""Payload schema for the Qdrant collection (Section 7 metadata tagging).

Every chunk carries enough metadata to scope retrieval three ways:
  * by tender      -- never mix clauses from a different tender into an answer
  * by vendor      -- Part 1 and Section 5.7 confidentiality between bidders
  * by status      -- Section 5.5 keeps eliminated vendors queryable, so the
                      agent must be able to include or exclude them explicitly
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import Field

from app.schemas.common import ChunkSection, DocumentKind, SchemaModel, VendorStatus

# Payload keys that get a Qdrant field index (filterable without a full scan).
INDEXED_KEYWORD_FIELDS = (
    "doc_kind",
    "tender_id",
    "notification_id",
    "vendor_id",
    "submission_id",
    "status",
    "section",
    "owner_user_id",
)
INDEXED_INTEGER_FIELDS = ("source_page",)


class ChunkPayload(SchemaModel):
    """One vector-store record. Mirrors what Section 7 calls the free-text side."""

    # --- what this chunk is ---
    doc_kind: DocumentKind
    section: ChunkSection = ChunkSection.GENERAL
    text: str

    # --- scoping ---
    tender_id: str | None = None
    notification_id: str | None = Field(
        default=None, description="UUID of the tender_notifications row."
    )
    vendor_id: str | None = None
    submission_id: str | None = Field(
        default=None, description="UUID of the vendor_submissions row."
    )
    # Mirrored from SQL and re-synced on every status change (see qdrant.retag_status).
    status: VendorStatus | None = None
    owner_user_id: str | None = None

    # --- citation anchor (must match the SQL provenance columns) ---
    source_file: str | None = None
    source_page: int | None = None
    clause_ref: str | None = None

    # --- bookkeeping ---
    chunk_index: int = Field(default=0, description="Ordinal within its source document.")
    indexed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_qdrant(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


def chunk_point_id(submission_or_doc_id: str, chunk_index: int) -> str:
    """Deterministic point id so re-indexing a document overwrites its chunks
    instead of duplicating them."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{submission_or_doc_id}:{chunk_index}"))
