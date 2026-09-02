"""Row -> Section 6 schema loading.

The inverse of `app.extraction.persist`. Kept together in one module so the two
directions can be read side by side; a field added to one and forgotten in the
other is the classic way a hybrid SQL/JSONB model silently loses data.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import TenderNotificationRow, VendorSubmissionRow
from app.schemas.common import (
    CriterionType,
    MoneyAmount,
    Provenance,
    VendorStatus,
    YearlyTurnover,
)
from app.schemas.notification import (
    EligibilityCriterion,
    EvaluationCriterion,
    MandatoryDocument,
    SubmissionFormatRule,
    TechnicalRequirement,
    TenderNotification,
)
from app.schemas.submission import (
    Certification,
    PastProject,
    SubmittedDocument,
    VendorSubmission,
)


def _prov(row) -> Provenance:
    return Provenance(
        clause_ref=row.clause_ref,
        source_page=row.source_page,
        source_snippet=row.source_snippet,
        extraction_confidence=row.extraction_confidence,
    )


def _prov_from_json(payload: dict) -> Provenance:
    return Provenance(
        clause_ref=payload.get("clause_ref"),
        source_page=payload.get("source_page"),
        source_snippet=payload.get("source_snippet"),
        extraction_confidence=payload.get("extraction_confidence"),
    )


def _money(raw: str | None, inr) -> MoneyAmount | None:
    if raw is None and inr is None:
        return None
    return MoneyAmount(raw_text=raw, amount_inr=inr)


def to_notification_schema(row: TenderNotificationRow) -> TenderNotification:
    return TenderNotification(
        tender_id=row.tender_id,
        title=row.title,
        issuing_authority=row.issuing_authority,
        sector=row.sector,
        submission_deadline=row.submission_deadline,
        pre_bid_query_deadline=row.pre_bid_query_deadline,
        eligibility_criteria=[
            EligibilityCriterion(
                criterion=c.criterion,
                type=CriterionType(c.type),
                threshold_raw=c.threshold_raw,
                threshold_amount=_money(c.threshold_raw, c.threshold_amount_inr)
                if c.threshold_amount_inr is not None
                else None,
                threshold_number=c.threshold_number,
                unit=c.unit,
                is_mandatory=c.is_mandatory,
                provenance=_prov(c),
            )
            for c in row.eligibility_criteria
        ],
        mandatory_documents=[
            MandatoryDocument(doc_name=d.doc_name, aliases=d.aliases or [], provenance=_prov(d))
            for d in row.mandatory_documents
        ],
        evaluation_criteria=[
            EvaluationCriterion(
                factor=c["factor"],
                weightage_if_stated=c.get("weightage_if_stated"),
                provenance=_prov_from_json(c),
            )
            for c in (row.evaluation_criteria or [])
        ],
        technical_requirements=[
            TechnicalRequirement(requirement=c["requirement"], provenance=_prov_from_json(c))
            for c in (row.technical_requirements or [])
        ],
        submission_format_rules=[
            SubmissionFormatRule(rule=c["rule"], provenance=_prov_from_json(c))
            for c in (row.submission_format_rules or [])
        ],
        emd_amount=_money(row.emd_amount_raw, row.emd_amount_inr),
        contract_value_estimate=_money(row.contract_value_raw, row.contract_value_inr),
    )


def to_submission_schema(
    row: VendorSubmissionRow, *, technical_approach_text: str | None = None
) -> VendorSubmission:
    """`technical_approach_text` lives in Qdrant, not SQL (Section 7), so it is
    passed in when a caller needs it rather than silently returning None."""
    return VendorSubmission(
        vendor_id=row.vendor_id,
        vendor_name=row.vendor_name,
        tender_id=row.notification.tender_id if row.notification else None,
        turnover=[
            YearlyTurnover(
                year=t.year,
                amount=_money(t.amount_raw, t.amount_inr) or MoneyAmount(),
                provenance=_prov(t),
            )
            for t in row.turnover
        ],
        years_in_business=row.years_in_business,
        certifications=[
            Certification(
                name=c.name,
                valid_till=c.valid_till,
                doc_present=c.doc_present,
                provenance=_prov(c),
            )
            for c in row.certifications
        ],
        past_projects=[
            PastProject(
                client=p.client,
                value=_money(p.value_raw, p.value_inr),
                year=p.year,
                description=p.description,
                provenance=_prov(p),
            )
            for p in row.past_projects
        ],
        documents_submitted=[
            SubmittedDocument(
                doc_name=d.doc_name,
                present=d.present,
                match_method=d.match_method,
                match_score=d.match_score,
                provenance=_prov(d),
            )
            for d in row.documents_submitted
        ],
        technical_approach_text=technical_approach_text,
        pricing_summary=row.pricing_summary,
        quoted_price=_money(row.quoted_price_raw, row.quoted_price_inr),
        is_blacklisted=row.is_blacklisted,
        debarment_disclosure=row.debarment_disclosure,
        status=VendorStatus(row.status),
        elimination_reason=row.elimination_reason,
    )


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #
def get_notification_row(session: Session, tender_id: str) -> TenderNotificationRow | None:
    return session.scalar(
        select(TenderNotificationRow).where(TenderNotificationRow.tender_id == tender_id)
    )


def get_submission_row(
    session: Session, tender_id: str, vendor_id: str
) -> VendorSubmissionRow | None:
    return session.scalar(
        select(VendorSubmissionRow)
        .join(TenderNotificationRow)
        .where(
            TenderNotificationRow.tender_id == tender_id,
            VendorSubmissionRow.vendor_id == vendor_id,
        )
    )


def list_notifications(
    session: Session, *, limit: int = 50, offset: int = 0
) -> list[TenderNotificationRow]:
    return list(
        session.scalars(
            select(TenderNotificationRow)
            .order_by(TenderNotificationRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def count_notifications(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(TenderNotificationRow)) or 0


def submission_counts(session: Session, notification_ids: list[uuid.UUID]) -> dict:
    """Bid counts for many tenders in one query.

    The listing previously called list_submissions() once per notification --
    an N+1 that turns a 20-tender page into 21 round trips and loads every
    submission row just to call len() on it.
    """
    if not notification_ids:
        return {}
    rows = session.execute(
        select(VendorSubmissionRow.notification_id, func.count())
        .where(VendorSubmissionRow.notification_id.in_(notification_ids))
        .group_by(VendorSubmissionRow.notification_id)
    ).all()
    return {notification_id: count for notification_id, count in rows}


def list_submissions(
    session: Session,
    notification_id: uuid.UUID,
    *,
    limit: int = 200,
    offset: int = 0,
) -> list[VendorSubmissionRow]:
    return list(
        session.scalars(
            select(VendorSubmissionRow)
            .where(VendorSubmissionRow.notification_id == notification_id)
            .order_by(VendorSubmissionRow.vendor_id)
            .limit(limit)
            .offset(offset)
        )
    )
