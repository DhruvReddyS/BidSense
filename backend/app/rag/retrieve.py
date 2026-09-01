"""Scoped retrieval over the Qdrant index (Section 4.5, 5.4).

Every retrieval is scoped by metadata before the vector search runs, not
filtered afterwards. Two reasons:

  * Correctness. Answering a question about tender A with a clause from tender B
    is a wrong answer that looks perfectly well-cited.
  * Confidentiality. Section 5.7 forbids a vendor seeing another vendor's bid.
    A post-filter leaks through score ordering and result counts; a pre-filter
    means the other bids were never candidates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import settings
from app.schemas.common import ChunkSection, DocumentKind, VendorStatus
from app.vector.embeddings import embed_query
from app.vector.qdrant import build_filter, get_client

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 6
# Below this cosine score a chunk is more likely to mislead than to help. BGE
# puts genuinely relevant tender text well above this; unrelated boilerplate
# sits below it.
MIN_SCORE = 0.30


@dataclass
class RetrievedChunk:
    """A retrieved passage with everything needed to cite it."""

    text: str
    score: float
    doc_kind: str
    source_file: str | None
    source_page: int | None
    clause_ref: str | None
    vendor_id: str | None
    tender_id: str | None
    section: str | None

    @property
    def citation(self) -> str:
        """Human-readable source label, e.g. 'NOTIF_01.pdf, page 2, clause 4.2'."""
        parts = [self.source_file or self.doc_kind]
        if self.source_page is not None:
            parts.append(f"page {self.source_page}")
        if self.clause_ref:
            parts.append(f"clause {self.clause_ref}")
        return ", ".join(parts)

    @classmethod
    def from_point(cls, point) -> "RetrievedChunk":
        payload = point.payload or {}
        return cls(
            text=payload.get("text", ""),
            score=point.score,
            doc_kind=payload.get("doc_kind", "unknown"),
            source_file=payload.get("source_file"),
            source_page=payload.get("source_page"),
            clause_ref=payload.get("clause_ref"),
            vendor_id=payload.get("vendor_id"),
            tender_id=payload.get("tender_id"),
            section=payload.get("section"),
        )


def retrieve(
    query: str,
    *,
    tender_id: str | None = None,
    vendor_id: str | None = None,
    submission_id: str | None = None,
    doc_kind: DocumentKind | None = None,
    statuses: list[VendorStatus] | None = None,
    sections: list[ChunkSection] | None = None,
    owner_user_id: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = MIN_SCORE,
) -> list[RetrievedChunk]:
    """Dense retrieval, scoped by metadata before the search."""
    query_vector = embed_query(query)
    results = get_client().query_points(
        collection_name=settings.qdrant_collection,
        query=query_vector,
        query_filter=build_filter(
            doc_kind=doc_kind,
            tender_id=tender_id,
            vendor_id=vendor_id,
            submission_id=submission_id,
            statuses=statuses,
            sections=[s.value for s in sections] if sections else None,
            owner_user_id=owner_user_id,
        ),
        limit=top_k,
        with_payload=True,
    ).points

    chunks = [RetrievedChunk.from_point(p) for p in results if p.score >= min_score]
    logger.info(
        "retrieve(%r) -> %d/%d chunks above %.2f", query[:60], len(chunks), len(results), min_score
    )
    return chunks


def retrieve_for_pair(
    query: str,
    *,
    tender_id: str,
    vendor_id: str,
    top_k: int = DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """Part 1's two-document scope (4.5): this tender's notification plus this
    one vendor's bid, and nothing else.

    Run as two scoped searches rather than one OR-filtered search so the
    notification is guaranteed representation. A single search lets a verbose
    bid crowd out the clause the question is actually about.
    """
    half = max(2, top_k // 2)
    notification_chunks = retrieve(
        query, tender_id=tender_id, doc_kind=DocumentKind.NOTIFICATION, top_k=half
    )
    bid_chunks = retrieve(
        query, tender_id=tender_id, vendor_id=vendor_id,
        doc_kind=DocumentKind.SUBMISSION, top_k=half,
    )
    merged = notification_chunks + bid_chunks
    merged.sort(key=lambda c: c.score, reverse=True)
    return merged[:top_k]
