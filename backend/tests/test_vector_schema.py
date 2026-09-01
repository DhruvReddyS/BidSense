"""Qdrant payload / metadata-tagging contract (Section 7)."""

from app.schemas.common import ChunkSection, DocumentKind, VendorStatus
from app.vector.schema import INDEXED_KEYWORD_FIELDS, ChunkPayload, chunk_point_id


def test_payload_carries_the_section_7_scoping_tags() -> None:
    payload = ChunkPayload(
        doc_kind=DocumentKind.SUBMISSION,
        section=ChunkSection.TECHNICAL_APPROACH,
        text="Our delivery methodology uses a phased rollout...",
        tender_id="T-1",
        vendor_id="V-04",
        submission_id="11111111-1111-1111-1111-111111111111",
        status=VendorStatus.PENDING,
        source_page=7,
    )
    dumped = payload.to_qdrant()
    # Section 7 explicitly requires vendor_id + status tagging for scoped retrieval.
    assert dumped["vendor_id"] == "V-04"
    assert dumped["status"] == "pending"
    assert dumped["doc_kind"] == "submission"
    assert dumped["section"] == "technical_approach"


def test_every_scoping_tag_is_an_indexed_field() -> None:
    for field in ("vendor_id", "status", "tender_id", "submission_id", "owner_user_id"):
        assert field in INDEXED_KEYWORD_FIELDS


def test_point_ids_are_deterministic() -> None:
    """Re-indexing a document must overwrite its chunks, not duplicate them."""
    assert chunk_point_id("sub-1", 3) == chunk_point_id("sub-1", 3)
    assert chunk_point_id("sub-1", 3) != chunk_point_id("sub-1", 4)
    assert chunk_point_id("sub-1", 3) != chunk_point_id("sub-2", 3)


def test_none_fields_are_dropped_from_the_payload() -> None:
    payload = ChunkPayload(doc_kind=DocumentKind.NOTIFICATION, text="clause text")
    assert "vendor_id" not in payload.to_qdrant()
