"""Tender Notification schema (Section 6).

Populated once per notification document. This is the single source of truth
every downstream check in Part 1 (4.3) and Part 2 (5.2) is measured against.
"""

from __future__ import annotations

from datetime import date

from pydantic import Field, model_validator

from app.schemas.common import (
    CriterionType,
    MoneyAmount,
    Provenanced,
    SchemaModel,
)


class EligibilityCriterion(Provenanced):
    """Section 6: { criterion, type, threshold, clause_ref }.

    `threshold_amount` is populated for money criteria so the rule engine (5.2)
    compares canonical rupees; `threshold_number` holds unit-less numerics such
    as "minimum 5 years experience". Exactly one is expected for NUMERIC.
    """

    criterion: str = Field(description="The requirement as stated, e.g. 'Annual turnover'.")
    type: CriterionType
    threshold_raw: str | None = Field(
        default=None, description="Threshold exactly as printed, e.g. '₹5 Cr'."
    )
    threshold_amount: MoneyAmount | None = Field(
        default=None, description="Canonical rupee threshold, for money criteria."
    )
    threshold_number: float | None = Field(
        default=None, description="Unit-less numeric threshold, e.g. 5 (years)."
    )
    unit: str | None = Field(default=None, description="e.g. 'years', 'projects', 'INR'.")
    is_mandatory: bool = Field(
        default=True,
        description="Only mandatory criteria are hard filters at Level 1 (5.2).",
    )

    @model_validator(mode="after")
    def _numeric_needs_a_threshold(self) -> "EligibilityCriterion":
        if self.type is CriterionType.NUMERIC:
            resolved = (
                self.threshold_amount is not None and self.threshold_amount.is_resolved
            ) or self.threshold_number is not None
            if not resolved and not self.threshold_raw:
                raise ValueError(
                    "numeric criterion requires a threshold "
                    "(threshold_amount, threshold_number, or at minimum threshold_raw)"
                )
        return self


class MandatoryDocument(Provenanced):
    """Section 6: { doc_name, clause_ref }."""

    doc_name: str = Field(description="Document name as printed in the notification.")
    aliases: list[str] = Field(
        default_factory=list,
        description=(
            "Known alternate names ('Goods & Services Tax Certificate' for "
            "'GST Registration Certificate'). Section 6 warns exact string "
            "matching produces false negatives at check time (4.3 / 5.2)."
        ),
    )


class EvaluationCriterion(Provenanced):
    """Section 6: { factor, weightage_if_stated, clause_ref }.

    `weightage_if_stated` stays None when the notification publishes no scoring.
    Section 4.4 forbids inventing a score in that case -- consumers must check
    this for None rather than defaulting it.
    """

    factor: str
    weightage_if_stated: float | None = Field(
        default=None, ge=0, le=100, description="Percent weight; None if unpublished."
    )


class TechnicalRequirement(Provenanced):
    requirement: str


class SubmissionFormatRule(Provenanced):
    """Section 4.3 treats these as needs-manual-check -- often visual, not textual."""

    rule: str


class TenderNotification(SchemaModel):
    """The full Section 6 Tender Notification Schema."""

    tender_id: str = Field(description="Tender reference number as issued.")
    title: str
    issuing_authority: str | None = None
    sector: str | None = Field(default=None, description="e.g. 'IT services', 'civil works'.")

    submission_deadline: date | None = None
    pre_bid_query_deadline: date | None = None

    eligibility_criteria: list[EligibilityCriterion] = Field(default_factory=list)
    mandatory_documents: list[MandatoryDocument] = Field(default_factory=list)
    evaluation_criteria: list[EvaluationCriterion] = Field(default_factory=list)
    technical_requirements: list[TechnicalRequirement] = Field(default_factory=list)
    submission_format_rules: list[SubmissionFormatRule] = Field(default_factory=list)

    emd_amount: MoneyAmount | None = None
    contract_value_estimate: MoneyAmount | None = None

    @property
    def publishes_weightage(self) -> bool:
        """Section 4.4: only show a self-score when weightage is actually stated."""
        return any(c.weightage_if_stated is not None for c in self.evaluation_criteria)
