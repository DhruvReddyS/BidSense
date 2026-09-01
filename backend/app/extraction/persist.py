"""Persist extracted Section 6 objects into Postgres + Qdrant (Phase 1).

Both stores are written in one call because they must not diverge: a submission
row without its chunks is invisible to qualitative retrieval, and chunks without
a row cannot be joined to a status. Postgres is committed first and is
authoritative; if the Qdrant write then fails, the caller is told loudly rather
than left with a half-indexed vendor that looks complete.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    EligibilityCriterionRow,
    MandatoryDocumentRow,
    TenderNotificationRow,
    VendorCertificationRow,
    VendorDocumentRow,
    VendorPastProjectRow,
    VendorSubmissionRow,
    VendorTurnoverRow,
)
from app.ingest.chunking import Chunk, chunk_document, chunk_text
from app.ingest.models import ParsedDocument
from app.schemas.common import ChunkSection, DocumentKind, Provenance
from app.schemas.notification import TenderNotification
from app.schemas.submission import VendorSubmission
from app.vector.embeddings import embed_passages
from app.vector.qdrant import build_filter, get_client
from app.vector.schema import ChunkPayload, chunk_point_id

logger = logging.getLogger(__name__)


def _prov(p: Provenance) -> dict:
    return {
        "clause_ref": p.clause_ref,
        "source_page": p.source_page,
        "source_snippet": p.source_snippet,
        "extraction_confidence": p.extraction_confidence,
    }


# --------------------------------------------------------------------------- #
# Postgres
# --------------------------------------------------------------------------- #
def save_notification(
    session: Session,
    notification: TenderNotification,
    *,
    source_file: str | None = None,
    owner_user_id: uuid.UUID | None = None,
) -> TenderNotificationRow:
    """Insert or replace a notification by its tender_id.

    Re-extracting the same tender replaces its children wholesale rather than
    merging: a partial merge would leave criteria from a previous, possibly
    wrong, extraction silently in force.
    """
    # Replace by tender_id AND by source file. The second clause matters: when
    # header extraction fails, tender_id falls back to the filename, so a failed
    # run followed by a successful one would otherwise leave two rows for the
    # same document -- one real, one an empty shell that still looks like a
    # tender in the listing.
    conditions = [TenderNotificationRow.tender_id == notification.tender_id]
    if source_file:
        conditions.append(TenderNotificationRow.source_file == source_file)
    stale = session.scalars(
        select(TenderNotificationRow).where(or_(*conditions))
    ).all()
    for existing in stale:
        logger.info(
            "Replacing existing extraction for tender %s (%s)",
            existing.tender_id,
            existing.source_file,
        )
        session.delete(existing)
    if stale:
        session.flush()

    row = TenderNotificationRow(
        tender_id=notification.tender_id,
        title=notification.title,
        issuing_authority=notification.issuing_authority,
        sector=notification.sector,
        submission_deadline=notification.submission_deadline,
        pre_bid_query_deadline=notification.pre_bid_query_deadline,
        emd_amount_raw=notification.emd_amount.raw_text if notification.emd_amount else None,
        emd_amount_inr=notification.emd_amount.amount_inr if notification.emd_amount else None,
        contract_value_raw=(
            notification.contract_value_estimate.raw_text
            if notification.contract_value_estimate
            else None
        ),
        contract_value_inr=(
            notification.contract_value_estimate.amount_inr
            if notification.contract_value_estimate
            else None
        ),
        evaluation_criteria=[
            {
                "factor": c.factor,
                "weightage_if_stated": c.weightage_if_stated,
                **_prov(c.provenance),
            }
            for c in notification.evaluation_criteria
        ],
        technical_requirements=[
            {"requirement": c.requirement, **_prov(c.provenance)}
            for c in notification.technical_requirements
        ],
        submission_format_rules=[
            {"rule": c.rule, **_prov(c.provenance)}
            for c in notification.submission_format_rules
        ],
        source_file=source_file,
        owner_user_id=owner_user_id,
    )

    for criterion in notification.eligibility_criteria:
        row.eligibility_criteria.append(
            EligibilityCriterionRow(
                criterion=criterion.criterion,
                type=criterion.type,
                threshold_raw=criterion.threshold_raw,
                threshold_amount_inr=(
                    criterion.threshold_amount.amount_inr
                    if criterion.threshold_amount
                    else None
                ),
                threshold_number=criterion.threshold_number,
                unit=criterion.unit,
                is_mandatory=criterion.is_mandatory,
                **_prov(criterion.provenance),
            )
        )

    for document in notification.mandatory_documents:
        row.mandatory_documents.append(
            MandatoryDocumentRow(
                doc_name=document.doc_name,
                aliases=document.aliases,
                **_prov(document.provenance),
            )
        )

    session.add(row)
    session.flush()
    return row


def save_submission(
    session: Session,
    submission: VendorSubmission,
    *,
    notification_id: uuid.UUID | None = None,
    source_file: str | None = None,
    owner_user_id: uuid.UUID | None = None,
) -> VendorSubmissionRow:
    """Insert or replace a vendor submission, keyed by (notification, vendor_id)."""
    if notification_id is None and submission.tender_id:
        notification_id = session.scalar(
            select(TenderNotificationRow.id).where(
                TenderNotificationRow.tender_id == submission.tender_id
            )
        )

    existing = session.scalar(
        select(VendorSubmissionRow).where(
            VendorSubmissionRow.vendor_id == submission.vendor_id,
            VendorSubmissionRow.notification_id == notification_id,
        )
    )
    if existing is not None:
        logger.info("Replacing existing extraction for vendor %s", submission.vendor_id)
        session.delete(existing)
        session.flush()

    row = VendorSubmissionRow(
        vendor_id=submission.vendor_id,
        vendor_name=submission.vendor_name,
        notification_id=notification_id,
        years_in_business=submission.years_in_business,
        pricing_summary=submission.pricing_summary,
        quoted_price_raw=submission.quoted_price.raw_text if submission.quoted_price else None,
        quoted_price_inr=(
            submission.quoted_price.amount_inr if submission.quoted_price else None
        ),
        is_blacklisted=submission.is_blacklisted,
        status=submission.status,
        elimination_reason=submission.elimination_reason,
        has_technical_approach=bool(submission.technical_approach_text),
        source_file=source_file,
        owner_user_id=owner_user_id,
    )

    for entry in submission.turnover:
        row.turnover.append(
            VendorTurnoverRow(
                year=entry.year,
                amount_raw=entry.amount.raw_text,
                amount_inr=entry.amount.amount_inr,
                **_prov(entry.provenance),
            )
        )
    for cert in submission.certifications:
        row.certifications.append(
            VendorCertificationRow(
                name=cert.name,
                valid_till=cert.valid_till,
                doc_present=cert.doc_present,
                **_prov(cert.provenance),
            )
        )
    for project in submission.past_projects:
        row.past_projects.append(
            VendorPastProjectRow(
                client=project.client,
                value_raw=project.value.raw_text if project.value else None,
                value_inr=project.value.amount_inr if project.value else None,
                year=project.year,
                description=project.description,
                **_prov(project.provenance),
            )
        )
    for document in submission.documents_submitted:
        row.documents_submitted.append(
            VendorDocumentRow(
                doc_name=document.doc_name,
                present=document.present,
                match_method=document.match_method,
                match_score=document.match_score,
                **_prov(document.provenance),
            )
        )

    session.add(row)
    session.flush()
    return row


# --------------------------------------------------------------------------- #
# Qdrant
# --------------------------------------------------------------------------- #
def _purge(stale_filter) -> None:
    """Drop a document's existing chunks before re-indexing it.

    Deterministic point ids alone are not enough: replacing the SQL row mints a
    new row_id, so the new chunks get new ids and the old ones survive as
    orphans. A shrinking re-extraction would also strand the tail. Both cases
    are fixed by deleting on the stable business identifier first.
    """
    if stale_filter is None:
        return
    get_client().delete(
        settings.qdrant_collection, points_selector=stale_filter, wait=True
    )


def _index(
    chunks: list[Chunk], payload_base: dict, owner_key: str, stale_filter=None
) -> int:
    """Purge any previous indexing of this document, then embed and upsert."""
    _purge(stale_filter)
    if not chunks:
        return 0

    vectors = embed_passages([c.text for c in chunks])
    points = [
        {
            "id": chunk_point_id(owner_key, chunk.chunk_index),
            "vector": vector,
            "payload": ChunkPayload(
                text=chunk.text,
                section=chunk.section,
                source_page=chunk.page_number,
                clause_ref=chunk.clause_ref,
                chunk_index=chunk.chunk_index,
                **payload_base,
            ).to_qdrant(),
        }
        for chunk, vector in zip(chunks, vectors)
    ]
    get_client().upsert(settings.qdrant_collection, points=points, wait=True)
    return len(points)


def index_notification(
    document: ParsedDocument, notification: TenderNotification, row_id: uuid.UUID
) -> int:
    """Index the notification's full text so Part 1's RAG (4.5) can cite clauses."""
    return _index(
        chunk_document(document, section=ChunkSection.ELIGIBILITY),
        {
            "doc_kind": DocumentKind.NOTIFICATION,
            "tender_id": notification.tender_id,
            "notification_id": str(row_id),
            "source_file": document.file_name,
        },
        owner_key=f"notification:{row_id}",
        # tender_id is stable across re-extraction; the row id is not.
        stale_filter=build_filter(
            doc_kind=DocumentKind.NOTIFICATION, tender_id=notification.tender_id
        ),
    )


def index_submission(
    document: ParsedDocument,
    submission: VendorSubmission,
    row_id: uuid.UUID,
    *,
    notification_id: uuid.UUID | None = None,
    owner_user_id: uuid.UUID | None = None,
) -> int:
    """Index the bid's narrative text (Section 7: free text -> vector store).

    The whole document is chunked, not only `technical_approach_text`: Section
    5.4's qualitative path also searches past-performance narratives, and the
    audit trail (5.5) needs the eliminated vendor's own words retrievable.
    """
    chunks = chunk_document(document, section=ChunkSection.TECHNICAL_APPROACH)

    # The extracted narrative is indexed separately too -- it is the passage the
    # qualitative queries in 5.4 are actually about, and chunking it on its own
    # keeps it from being diluted by boilerplate on the same page.
    if submission.technical_approach_text:
        chunks += chunk_text(
            submission.technical_approach_text,
            section=ChunkSection.TECHNICAL_APPROACH,
            start_index=len(chunks),
        )
    for project in submission.past_projects:
        if project.description:
            chunks += chunk_text(
                project.description,
                page_number=project.provenance.source_page or 1,
                section=ChunkSection.PAST_PERFORMANCE,
                start_index=len(chunks),
            )

    return _index(
        chunks,
        {
            "doc_kind": DocumentKind.SUBMISSION,
            "tender_id": submission.tender_id,
            "notification_id": str(notification_id) if notification_id else None,
            "vendor_id": submission.vendor_id,
            "submission_id": str(row_id),
            "status": submission.status,
            "owner_user_id": str(owner_user_id) if owner_user_id else None,
            "source_file": document.file_name,
        },
        owner_key=f"submission:{row_id}",
        stale_filter=build_filter(
            doc_kind=DocumentKind.SUBMISSION,
            vendor_id=submission.vendor_id,
            tender_id=submission.tender_id,
        ),
    )
