"""Raw LLM output -> Section 6 schema.

This is where the model's verbatim strings become canonical, comparable values.
Everything here is deterministic and tested: no LLM involvement, so a wrong
number is a bug we can find rather than a sampling artefact.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from app.extraction import llm_schemas as raw
from app.normalize.money import try_normalize_amount
from app.schemas.common import CriterionType, MoneyAmount, Provenance
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
from app.schemas.common import YearlyTurnover

logger = logging.getLogger(__name__)

# Indian tender documents use all of these. Ambiguous D/M vs M/D is resolved
# day-first, which is the Indian convention -- getting this backwards silently
# shifts deadlines by months.
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
)

_NUMBER_IN_TEXT = re.compile(r"(\d+(?:\.\d+)?)")

# Word-boundary matched, NOT substring: "years" contains "rs", so a plain
# `"rs" in text` check reads "5 (five) years" as five rupees and compares a
# duration against a turnover threshold.
_MONETARY_TOKEN = re.compile(
    r"(?:₹|\b(?:inr|rs|rupees?|cr|crores?|lakhs?|lacs?|crore)\b)", re.IGNORECASE
)


def parse_date(value: str | None) -> date | None:
    """Lenient date parsing. Returns None rather than guessing -- a wrong
    deadline is worse than a missing one."""
    if not value:
        return None
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    logger.warning("Unparseable date %r -- left as None", value)
    return None


def to_provenance(item: raw.Cited, confidence: float | None = None) -> Provenance:
    return Provenance(
        clause_ref=item.clause_ref,
        source_page=item.source_page,
        source_snippet=item.source_snippet,
        extraction_confidence=confidence,
    )


def _looks_monetary(threshold_raw: str | None, unit: str | None) -> bool:
    """Distinguish 'Rs. 5 Cr' from '5 years' so the right threshold slot fills."""
    blob = f"{threshold_raw or ''} {unit or ''}"
    return bool(_MONETARY_TOKEN.search(blob))


def _bare_number(text: str | None) -> float | None:
    if not text:
        return None
    match = _NUMBER_IN_TEXT.search(text)
    return float(match.group(1)) if match else None


def to_eligibility(item: raw.RawEligibilityCriterion) -> EligibilityCriterion:
    """Route the printed threshold into the money slot or the plain-number slot.

    A numeric criterion whose threshold cannot be resolved either way still gets
    built, carrying threshold_raw only -- it must surface as needs-manual-check
    rather than vanish from the eligibility list.
    """
    threshold_amount = None
    threshold_number = None

    if item.type is CriterionType.NUMERIC and item.threshold_raw:
        if _looks_monetary(item.threshold_raw, item.unit):
            amount = try_normalize_amount(item.threshold_raw)
            if amount is not None:
                threshold_amount = MoneyAmount(
                    raw_text=item.threshold_raw, amount_inr=amount
                )
        else:
            threshold_number = _bare_number(item.threshold_raw)

    return EligibilityCriterion(
        criterion=item.criterion,
        type=item.type,
        threshold_raw=item.threshold_raw,
        threshold_amount=threshold_amount,
        threshold_number=threshold_number,
        unit=item.unit,
        is_mandatory=item.is_mandatory,
        provenance=to_provenance(item),
    )


def to_notification(
    header: raw.RawHeader,
    eligibility: list[raw.RawEligibilityCriterion],
    documents: list[raw.RawMandatoryDocument],
    evaluation: list[raw.RawEvaluationCriterion],
    technical: list[raw.RawTechnicalRequirement],
    format_rules: list[raw.RawSubmissionFormatRule],
    *,
    fallback_tender_id: str,
    fallback_title: str,
) -> TenderNotification:
    return TenderNotification(
        # tender_id and title are required by the schema; a document that fails
        # to yield them still has to be storable and reviewable, so fall back to
        # the filename rather than dropping the whole extraction.
        tender_id=(header.tender_id or fallback_tender_id).strip(),
        title=(header.title or fallback_title).strip(),
        issuing_authority=header.issuing_authority,
        sector=header.sector,
        submission_deadline=parse_date(header.submission_deadline),
        pre_bid_query_deadline=parse_date(header.pre_bid_query_deadline),
        eligibility_criteria=[to_eligibility(i) for i in eligibility],
        mandatory_documents=[
            MandatoryDocument(doc_name=i.doc_name, provenance=to_provenance(i))
            for i in documents
        ],
        evaluation_criteria=[
            EvaluationCriterion(
                factor=i.factor,
                weightage_if_stated=i.weightage_if_stated,
                provenance=to_provenance(i),
            )
            for i in evaluation
        ],
        technical_requirements=[
            TechnicalRequirement(requirement=i.requirement, provenance=to_provenance(i))
            for i in technical
        ],
        submission_format_rules=[
            SubmissionFormatRule(rule=i.rule, provenance=to_provenance(i))
            for i in format_rules
        ],
        emd_amount=MoneyAmount.parse(header.emd_amount_raw),
        contract_value_estimate=MoneyAmount.parse(header.contract_value_raw),
    )


def to_submission(
    header: raw.RawVendorHeader,
    turnover: list[raw.RawTurnover],
    certifications: list[raw.RawCertification],
    past_projects: list[raw.RawPastProject],
    documents: list[raw.RawSubmittedDocument],
    *,
    vendor_id: str,
    fallback_vendor_name: str,
    tender_id: str | None = None,
) -> VendorSubmission:
    turnover_rows: list[YearlyTurnover] = []
    for item in turnover:
        year = _bare_number(item.year)
        if year is None:
            logger.warning("Turnover entry with unparseable year %r -- skipped", item.year)
            continue
        turnover_rows.append(
            YearlyTurnover(
                year=int(year),
                amount=MoneyAmount(raw_text=item.amount_raw),
                provenance=to_provenance(item),
            )
        )

    return VendorSubmission(
        vendor_id=vendor_id,
        vendor_name=(header.vendor_name or fallback_vendor_name).strip(),
        tender_id=tender_id,
        turnover=turnover_rows,
        years_in_business=header.years_in_business,
        certifications=[
            Certification(
                name=i.name,
                valid_till=parse_date(i.valid_till),
                doc_present=i.doc_present,
                provenance=to_provenance(i),
            )
            for i in certifications
        ],
        past_projects=[
            PastProject(
                client=i.client,
                value=MoneyAmount.parse(i.value_raw),
                year=i.year,
                description=i.description,
                provenance=to_provenance(i),
            )
            for i in past_projects
        ],
        documents_submitted=[
            SubmittedDocument(
                doc_name=i.doc_name, present=i.present, provenance=to_provenance(i)
            )
            for i in documents
        ],
        technical_approach_text=header.technical_approach_text,
        pricing_summary=header.pricing_summary,
        quoted_price=MoneyAmount.parse(header.quoted_price_raw),
    )
