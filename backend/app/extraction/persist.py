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
from sqlalchemy.exc import IntegrityError
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

# Points per Qdrant upsert request.
UPSERT_BATCH = 128


def _claim_row(session: Session, lookup, build):
    """Return the existing row for a unique key, inserting one if there is none.

    The obvious `SELECT then INSERT` is not safe when two uploads of the same
    document overlap, which they do: the API runs ingestion on a worker pool and
    a user who double-clicks Upload, or re-uploads while the first run is still
    going, produces exactly this. Both writers SELECT, both find nothing, both
    INSERT, and the loser dies on the unique constraint -- observed as three
    `uq_vendor_per_tender` failures out of four concurrent re-uploads.

    Failing loudly there is better than duplicating, but it is still a failed
    upload for work that was already done. So the INSERT goes inside a SAVEPOINT:
    if it loses the race, only the savepoint rolls back, and the loser re-reads
    the winner's row and updates it in place. Both writers converge on one row.

    The SAVEPOINT is what makes this safe to retry -- a bare IntegrityError
    poisons the whole transaction, and everything written before this point
    would be lost with it.
    """
    row = session.scalar(lookup)
    if row is not None:
        return row
    try:
        with session.begin_nested():
            row = build()
            session.add(row)
            session.flush()
        return row
    except IntegrityError:
        session.expire_all()
        row = session.scalar(lookup)
        if row is None:
            # Not the race we guarded: some other constraint was violated, and
            # swallowing it would write a row nobody can explain.
            raise
        logger.info("lost an insert race; updating the row the other writer created")
        return row


def _lock_for_replace(session: Session, row) -> None:
    """Serialize the wholesale replacement of a row's children.

    Children are replaced, not merged (see the callers), and two writers doing
    that to the same parent at once corrupt each other even though the parent
    row itself is now race-free:

        A: DELETE children ... INSERT children ... COMMIT
        B: DELETE children   <- matches nothing, A already removed them
           INSERT children   <- collides with A's rows on uq_turnover_per_year

    B's ORM had the old children in its identity map, so it issues deletes by id
    for rows that are gone (visible as SQLAlchemy's "expected to delete 3 row(s);
    0 were matched" warning) and then inserts duplicates. Observed as
    `uq_turnover_per_year` violations under four concurrent re-uploads of one bid.

    `SELECT ... FOR UPDATE` on the parent makes B wait for A to commit; expiring
    the row afterwards forces the children to be re-read as they now are, so B's
    delete targets real rows. The two replacements then apply in sequence and the
    last writer wins cleanly, which is what "re-extraction replaces" means.
    """
    session.flush()
    session.execute(
        select(type(row).id).where(type(row).id == row.id).with_for_update()
    )
    session.expire(row)


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
    content_hash: str | None = None,
    extraction_metadata: dict | None = None,
) -> TenderNotificationRow:
    """Insert or update a notification, preserving the bids filed against it.

    Re-extraction UPDATES the existing row in place; it must never delete and
    recreate it. `vendor_submissions` cascades from this row, so delete/recreate
    silently destroys every bid filed against the tender -- on a Part 2 pool
    that is a hundred evaluations lost to re-running an extraction, or to
    uploading a corrigendum (5.6).

    Matching is by tender_id OR source file. When header extraction fails,
    tender_id falls back to the filename, so a failed run followed by a
    successful one would otherwise leave two rows for one document.
    """
    conditions = [TenderNotificationRow.tender_id == notification.tender_id]
    if source_file:
        conditions.append(TenderNotificationRow.source_file == source_file)
    matches = session.scalars(
        select(TenderNotificationRow)
        .where(or_(*conditions))
        .order_by(TenderNotificationRow.created_at)
    ).all()

    if matches:
        row = matches[0]
        logger.info(
            "Updating extraction for tender %s (%d submission(s) preserved)",
            row.tender_id,
            len(row.submissions),
        )
        # Additional matches are genuine duplicates (typically a shell row from
        # a failed run). Re-home their submissions before removing them so no
        # bid is lost to the cleanup either.
        for duplicate in matches[1:]:
            logger.info("Merging duplicate row %s", duplicate.source_file)
            for submission in list(duplicate.submissions):
                submission.notification_id = row.id
            session.flush()
            session.delete(duplicate)
    else:
        # Insert under a savepoint so a concurrent upload of the same tender
        # converges on one row instead of killing the loser's transaction.
        row = _claim_row(
            session,
            select(TenderNotificationRow).where(
                TenderNotificationRow.tender_id == notification.tender_id
            ),
            lambda: TenderNotificationRow(
                tender_id=notification.tender_id,
                title=notification.title,
                issuing_authority=notification.issuing_authority,
            ),
        )

    row.extraction_metadata = extraction_metadata or {}
    row.tender_id = notification.tender_id
    row.title = notification.title
    row.issuing_authority = notification.issuing_authority
    row.sector = notification.sector
    row.submission_deadline = notification.submission_deadline
    row.pre_bid_query_deadline = notification.pre_bid_query_deadline
    row.emd_amount_raw = notification.emd_amount.raw_text if notification.emd_amount else None
    row.emd_amount_inr = notification.emd_amount.amount_inr if notification.emd_amount else None
    row.contract_value_raw = (
        notification.contract_value_estimate.raw_text
        if notification.contract_value_estimate
        else None
    )
    row.contract_value_inr = (
        notification.contract_value_estimate.amount_inr
        if notification.contract_value_estimate
        else None
    )
    row.evaluation_criteria = [
        {
            "factor": c.factor,
            "weightage_if_stated": c.weightage_if_stated,
            **_prov(c.provenance),
        }
        for c in notification.evaluation_criteria
    ]
    row.technical_requirements = [
        {"requirement": c.requirement, **_prov(c.provenance)}
        for c in notification.technical_requirements
    ]
    row.submission_format_rules = [
        {"rule": c.rule, **_prov(c.provenance)}
        for c in notification.submission_format_rules
    ]
    if source_file:
        row.source_file = source_file
    if content_hash:
        row.content_hash = content_hash
    if owner_user_id:
        row.owner_user_id = owner_user_id

    # Children are replaced wholesale, not merged: a partial merge would leave
    # criteria from a previous, possibly wrong, extraction silently in force.
    # Locked first, so a concurrent re-extraction of the same tender replaces
    # them after us rather than on top of us.
    _lock_for_replace(session, row)
    row.eligibility_criteria.clear()
    row.mandatory_documents.clear()
    session.flush()

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

    session.flush()
    return row


def save_submission(
    session: Session,
    submission: VendorSubmission,
    *,
    notification_id: uuid.UUID | None = None,
    source_file: str | None = None,
    owner_user_id: uuid.UUID | None = None,
    content_hash: str | None = None,
    extraction_metadata: dict | None = None,
) -> VendorSubmissionRow:
    """Insert or update a vendor submission, keyed by (notification, vendor_id).

    Updated in place rather than deleted and recreated, for the same reason as
    notifications: the row id is referenced elsewhere. Vector chunks are purged
    by submission id, and a churning id means the purge cannot find the previous
    chunks -- which forced a looser filter that could delete a vendor's chunks
    across every tender they had bid on.
    """
    if notification_id is None and submission.tender_id:
        notification_id = session.scalar(
            select(TenderNotificationRow.id).where(
                TenderNotificationRow.tender_id == submission.tender_id
            )
        )

    lookup = select(VendorSubmissionRow).where(
        VendorSubmissionRow.vendor_id == submission.vendor_id,
        VendorSubmissionRow.notification_id == notification_id,
    )
    existing = session.scalar(lookup)
    if existing is not None:
        logger.info("Updating existing extraction for vendor %s", submission.vendor_id)
    # Claimed under a savepoint: uq_vendor_per_tender makes two overlapping
    # uploads of the same bid a race, and the loser should update the winner's
    # row rather than fail an upload whose extraction has already been paid for.
    row = _claim_row(
        session,
        lookup,
        lambda: VendorSubmissionRow(
            vendor_id=submission.vendor_id,
            vendor_name=submission.vendor_name,
            notification_id=notification_id,
        ),
    )

    row.extraction_metadata = extraction_metadata or {}
    row.vendor_id = submission.vendor_id
    row.vendor_name = submission.vendor_name
    row.notification_id = notification_id
    row.years_in_business = submission.years_in_business
    row.pricing_summary = submission.pricing_summary
    row.quoted_price_raw = (
        submission.quoted_price.raw_text if submission.quoted_price else None
    )
    row.quoted_price_inr = (
        submission.quoted_price.amount_inr if submission.quoted_price else None
    )
    row.liquid_assets_raw = (
        submission.liquid_assets.raw_text if submission.liquid_assets else None
    )
    row.liquid_assets_inr = (
        submission.liquid_assets.amount_inr if submission.liquid_assets else None
    )
    row.net_worth_raw = submission.net_worth.raw_text if submission.net_worth else None
    row.net_worth_inr = (
        submission.net_worth.amount_inr if submission.net_worth else None
    )
    row.is_blacklisted = submission.is_blacklisted
    row.debarment_disclosure = submission.debarment_disclosure
    row.status = submission.status
    row.elimination_reason = submission.elimination_reason
    row.has_technical_approach = bool(submission.technical_approach_text)
    if source_file:
        row.source_file = source_file
    if content_hash:
        row.content_hash = content_hash
    if owner_user_id:
        row.owner_user_id = owner_user_id

    # Children are replaced wholesale, not merged: a partial merge would leave
    # figures from a previous, possibly wrong, extraction silently in force.
    _lock_for_replace(session, row)
    row.turnover.clear()
    row.certifications.clear()
    row.past_projects.clear()
    row.documents_submitted.clear()
    session.flush()

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

    # Generated schedules, repeated declarations and boilerplate commonly
    # produce identical chunks. Encode each distinct passage once and reuse the
    # vector; cosine retrieval is mathematically identical, while large bid
    # packs avoid redundant transformer work.
    unique_texts = list(dict.fromkeys(c.text for c in chunks))
    unique_vectors = embed_passages(unique_texts)
    vector_by_text = dict(zip(unique_texts, unique_vectors))
    vectors = [vector_by_text[c.text] for c in chunks]
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
    # Batched rather than sent as one request. A 173-page bid produces a few
    # hundred chunks and a whole-document upsert is a multi-megabyte body; a
    # larger document would push it past request limits or time out, and the
    # failure would land after the embedding work was already paid for.
    client = get_client()
    for start in range(0, len(points), UPSERT_BATCH):
        client.upsert(
            settings.qdrant_collection,
            points=points[start : start + UPSERT_BATCH],
            wait=True,
        )
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
        # Scoped to this submission alone. Scoping by vendor_id instead would,
        # for a bid with no tender link, delete that vendor's chunks across
        # every tender they had bid on -- build_filter simply omits a None
        # tender_id rather than narrowing on it.
        stale_filter=build_filter(submission_id=str(row_id)),
    )


def save_corrigendum(
    session: Session,
    corrigendum,
    notification_row: TenderNotificationRow,
    *,
    source_file: str | None = None,
) -> "CorrigendumRow":
    """Insert or update an amendment against its parent notification.

    Keyed on (notification, corrigendum_id) so re-uploading the same amendment
    updates it rather than stacking a second copy -- which would show a vendor
    the same change twice in the staleness banner.

    A tender can legitimately carry SEVERAL corrigenda, so unlike the other two
    save functions this one does not replace what is already there. Corrigendum
    No. 2 does not supersede No. 1; both amended the tender, and the audit trail
    (5.5) needs both.
    """
    from app.db.models import ChangedFieldRow, CorrigendumRow

    lookup = select(CorrigendumRow).where(
        CorrigendumRow.notification_id == notification_row.id,
        CorrigendumRow.corrigendum_id == corrigendum.corrigendum_id,
    )
    row = _claim_row(
        session,
        lookup,
        lambda: CorrigendumRow(
            corrigendum_id=corrigendum.corrigendum_id,
            notification_id=notification_row.id,
            parent_tender_id=corrigendum.parent_tender_id,
        ),
    )

    row.parent_tender_id = corrigendum.parent_tender_id
    row.issued_date = corrigendum.issued_date
    if source_file:
        row.source_file = source_file

    _lock_for_replace(session, row)
    row.changed_fields.clear()
    session.flush()
    for change in corrigendum.changed_fields:
        row.changed_fields.append(
            ChangedFieldRow(
                field_path=change.field_path,
                old_value=change.old_value,
                new_value=change.new_value,
                **_prov(change.provenance),
            )
        )
    session.flush()
    return row
