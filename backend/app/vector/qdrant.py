"""Qdrant client, collection bootstrap and metadata-scoped helpers (Section 7)."""

from __future__ import annotations

import logging
from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.config import settings
from app.schemas.common import DocumentKind, VendorStatus
from app.vector.schema import INDEXED_INTEGER_FIELDS, INDEXED_KEYWORD_FIELDS

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_client() -> QdrantClient:
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
        timeout=60,
    )


def ensure_collection(recreate: bool = False) -> None:
    """Create the collection and its payload indexes if absent. Idempotent.

    Vector size is pinned to settings.embedding_dim (768 for bge-base-en-v1.5).
    Changing the embedding model means recreating the collection and
    re-embedding everything -- there is no in-place migration for dimension.
    """
    client = get_client()
    name = settings.qdrant_collection

    if recreate and client.collection_exists(name):
        logger.warning("Deleting existing collection %s", name)
        client.delete_collection(name)

    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config=qm.VectorParams(
                size=settings.embedding_dim,
                distance=qm.Distance.COSINE,
            ),
        )
        logger.info("Created collection %s (dim=%d)", name, settings.embedding_dim)
    else:
        info = client.get_collection(name)
        existing_dim = info.config.params.vectors.size
        if existing_dim != settings.embedding_dim:
            raise RuntimeError(
                f"Collection {name} has dim={existing_dim} but config expects "
                f"{settings.embedding_dim}. Re-embed and recreate, don't silently mix."
            )

    for field in INDEXED_KEYWORD_FIELDS:
        _ensure_index(client, name, field, qm.PayloadSchemaType.KEYWORD)
    for field in INDEXED_INTEGER_FIELDS:
        _ensure_index(client, name, field, qm.PayloadSchemaType.INTEGER)


def _ensure_index(
    client: QdrantClient, collection: str, field: str, schema: qm.PayloadSchemaType
) -> None:
    try:
        client.create_payload_index(
            collection_name=collection, field_name=field, field_schema=schema
        )
    except Exception as exc:  # already-exists is not an error worth failing on
        if "already exists" not in str(exc).lower():
            raise
        logger.debug("Payload index %s already present", field)


def build_filter(
    *,
    doc_kind: DocumentKind | None = None,
    tender_id: str | None = None,
    vendor_id: str | None = None,
    submission_id: str | None = None,
    statuses: list[VendorStatus] | None = None,
    sections: list[str] | None = None,
    owner_user_id: str | None = None,
) -> qm.Filter | None:
    """Compose a scoped retrieval filter.

    Section 5.5 keeps eliminated vendors in the index deliberately, so `statuses`
    is opt-in: pass it to restrict, omit it to search the whole pool including
    eliminated vendors (which is what an audit query wants).
    """
    must: list[qm.Condition] = []

    def eq(key: str, value: object) -> None:
        must.append(qm.FieldCondition(key=key, match=qm.MatchValue(value=str(value))))

    if doc_kind is not None:
        eq("doc_kind", doc_kind.value)
    if tender_id is not None:
        eq("tender_id", tender_id)
    if vendor_id is not None:
        eq("vendor_id", vendor_id)
    if submission_id is not None:
        eq("submission_id", submission_id)
    if owner_user_id is not None:
        eq("owner_user_id", owner_user_id)
    if statuses:
        must.append(
            qm.FieldCondition(
                key="status", match=qm.MatchAny(any=[s.value for s in statuses])
            )
        )
    if sections:
        must.append(qm.FieldCondition(key="section", match=qm.MatchAny(any=sections)))

    return qm.Filter(must=must) if must else None


def retag_status(submission_id: str, status: VendorStatus) -> None:
    """Mirror a SQL status change onto that vendor's chunks.

    Status lives in two places (Postgres is authoritative, Qdrant is a filter
    tag). Every write that changes `vendor_submissions.status` must call this,
    or status-scoped retrieval quietly answers from stale tags.
    """
    get_client().set_payload(
        collection_name=settings.qdrant_collection,
        payload={"status": status.value},
        points=qm.Filter(
            must=[
                qm.FieldCondition(
                    key="submission_id", match=qm.MatchValue(value=submission_id)
                )
            ]
        ),
    )


def collection_stats() -> dict:
    client = get_client()
    name = settings.qdrant_collection
    if not client.collection_exists(name):
        return {"exists": False, "name": name}
    info = client.get_collection(name)
    return {
        "exists": True,
        "name": name,
        "points": info.points_count,
        "dim": info.config.params.vectors.size,
        "distance": info.config.params.vectors.distance,
    }
