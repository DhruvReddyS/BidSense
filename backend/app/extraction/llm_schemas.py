"""What the LLM is asked to return -- deliberately NOT the Section 6 schema.

Two reasons for a separate, flatter set of models:

1. **The model never computes.** It returns amounts exactly as printed
   ("Rs. 5 Cr") and a later node canonicalises them with the tested normalizer
   in `app.normalize.money`. Section 2.1.3's argument -- extraction is the NLP
   task, arithmetic is deterministic code -- applies to normalization too. An
   LLM that "helpfully" converts to 50000000 is doing arithmetic we cannot audit.
2. **Flat models decode more reliably.** Deeply nested schemas raise the failure
   rate of constrained decoding, which Section 8.1 explicitly asks us to lean on.

Every extracted item carries its own citation anchor, because the page a value
came from is only knowable while the model is looking at the text.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import CriterionType


class Cited(BaseModel):
    """Citation anchor. `source_snippet` must be verbatim -- it is what an
    auditor checks the extracted value against (Section 10, citation faithfulness)."""

    model_config = ConfigDict(extra="ignore")

    clause_ref: str | None = Field(
        default=None, description="Clause number exactly as printed, e.g. '4.2'. Null if none."
    )
    source_page: int | None = Field(
        default=None, description="The [PAGE N] marker this was found under."
    )
    source_snippet: str | None = Field(
        default=None, description="Verbatim sentence containing the value. Do not paraphrase."
    )


class RawHeader(BaseModel):
    """Top-level notification identifiers and dates."""

    model_config = ConfigDict(extra="ignore")

    tender_id: str | None = Field(default=None, description="Tender reference number as printed.")
    title: str | None = None
    issuing_authority: str | None = None
    sector: str | None = Field(
        default=None, description="e.g. 'IT services', 'civil works', 'supply'."
    )
    submission_deadline: str | None = Field(
        default=None, description="ISO date YYYY-MM-DD. Null if not stated."
    )
    pre_bid_query_deadline: str | None = Field(default=None, description="ISO date YYYY-MM-DD.")
    emd_amount_raw: str | None = Field(
        default=None, description="EMD exactly as printed, e.g. 'Rs. 2,00,000'. Do NOT convert."
    )
    contract_value_raw: str | None = Field(
        default=None, description="Estimated contract value as printed. Do NOT convert."
    )


class RawEligibilityCriterion(Cited):
    criterion: str = Field(description="The requirement as stated.")
    type: CriterionType = Field(
        description="numeric = a threshold to compare; document = a paper that must exist; "
        "boolean = a yes/no condition such as not being blacklisted."
    )
    threshold_raw: str | None = Field(
        default=None,
        description="Threshold exactly as printed, e.g. 'Rs. 5 Cr' or '5 years'. Do NOT convert.",
    )
    unit: str | None = Field(default=None, description="e.g. 'INR', 'years', 'projects'.")
    is_mandatory: bool = Field(
        default=True, description="False only if the text marks it desirable/preferred."
    )


class RawMandatoryDocument(Cited):
    doc_name: str = Field(description="Document name as printed in the notification.")


class RawEvaluationCriterion(Cited):
    factor: str
    weightage_if_stated: float | None = Field(
        default=None,
        description=(
            "Percentage weight ONLY if the notification prints one. If no scoring "
            "weightage is published, return null -- never estimate or infer a weight."
        ),
    )


class RawTechnicalRequirement(Cited):
    requirement: str


class RawSubmissionFormatRule(Cited):
    rule: str


# --- container models: structured output needs an object root, not a bare list ---
class EligibilityList(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[RawEligibilityCriterion] = Field(default_factory=list)


class DocumentList(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[RawMandatoryDocument] = Field(default_factory=list)


class EvaluationList(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[RawEvaluationCriterion] = Field(default_factory=list)


class TechnicalList(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[RawTechnicalRequirement] = Field(default_factory=list)


class FormatRuleList(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[RawSubmissionFormatRule] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Vendor submission side
# --------------------------------------------------------------------------- #
class RawTurnover(Cited):
    year: str = Field(description="Financial year as printed, e.g. '2023-24'.")
    amount_raw: str = Field(description="Amount exactly as printed. Do NOT convert.")


class RawCertification(Cited):
    name: str
    valid_till: str | None = Field(default=None, description="ISO date YYYY-MM-DD if stated.")
    doc_present: bool = Field(
        default=True, description="True if the certificate itself appears in the bid."
    )


class RawPastProject(Cited):
    client: str | None = None
    value_raw: str | None = Field(default=None, description="As printed. Do NOT convert.")
    year: int | None = None
    description: str | None = None


class RawSubmittedDocument(Cited):
    doc_name: str
    present: bool = True


class RawVendorHeader(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vendor_name: str | None = None
    years_in_business: float | None = Field(
        default=None, description="Only if explicitly stated. Do not infer from dates."
    )
    pricing_summary: str | None = None
    quoted_price_raw: str | None = Field(default=None, description="As printed. Do NOT convert.")
    liquid_assets_raw: str | None = Field(
        default=None,
        description=(
            "Liquid assets, working capital, or unutilised bank credit "
            "facilities the bidder declares, exactly as printed. This is the "
            "figure a solvency or credit-availability certificate states. Do "
            "NOT convert, and do not use the turnover figure here."
        ),
    )
    net_worth_raw: str | None = Field(
        default=None, description="Declared net worth exactly as printed. Do NOT convert."
    )
    technical_approach_text: str | None = Field(
        default=None,
        description=(
            "The bidder's methodology / technical approach narrative, copied "
            "verbatim and in full. This is free text for the vector store."
        ),
    )
    declared_debarment: str | None = Field(
        default=None,
        description=(
            "Verbatim text of any statement that the bidder IS currently "
            "debarred, blacklisted, banned, or under liquidation or insolvency "
            "proceedings. Return null when the bid declares the opposite -- "
            "'we have not been blacklisted' is a clean declaration, not a "
            "disclosure. Only a positive admission goes here."
        ),
    )


class TurnoverList(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[RawTurnover] = Field(default_factory=list)


class CertificationList(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[RawCertification] = Field(default_factory=list)


class PastProjectList(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[RawPastProject] = Field(default_factory=list)


class SubmittedDocumentList(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[RawSubmittedDocument] = Field(default_factory=list)
