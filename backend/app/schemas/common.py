"""Shared primitives for the Section 6 extraction schema."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.normalize.money import try_normalize_amount


class SchemaModel(BaseModel):
    """Base for every extraction model: strict-ish, trims strings, no stray keys."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=False,
        validate_assignment=True,
    )


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class UserRole(StrEnum):
    """Section 5.7 -- role separation between the two sides of the system."""

    VENDOR = "vendor"
    REVIEWER = "reviewer"


class CriterionType(StrEnum):
    """Section 6, eligibility_criteria.type."""

    NUMERIC = "numeric"
    BOOLEAN = "boolean"
    DOCUMENT = "document"


class VendorStatus(StrEnum):
    """Section 6, vendor status enum. Note there is deliberately no `passed`
    state: vendors clearing elimination sit at `pending` until Level 2 (5.3)
    promotes them to `shortlisted` (see Section 5.2)."""

    ELIMINATED = "eliminated"
    PENDING = "pending"
    SHORTLISTED = "shortlisted"


class DocumentKind(StrEnum):
    """What a stored document / vector chunk originated from."""

    NOTIFICATION = "notification"
    SUBMISSION = "submission"
    CORRIGENDUM = "corrigendum"


class ChunkSection(StrEnum):
    """Which narrative section a vector chunk came from (Section 7: free-text
    fields go to the vector store; structured fields stay in SQL)."""

    TECHNICAL_APPROACH = "technical_approach"
    PAST_PERFORMANCE = "past_performance"
    PRICING = "pricing"
    ELIGIBILITY = "eligibility"
    TECHNICAL_REQUIREMENTS = "technical_requirements"
    SUBMISSION_FORMAT = "submission_format"
    EVALUATION_CRITERIA = "evaluation_criteria"
    GENERAL = "general"


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #
class Provenance(SchemaModel):
    """Where an extracted value came from.

    Section 6 specifies `clause_ref`; we carry the page anchor and the verbatim
    snippet alongside it so citations in 4.3 / 4.5 / 5.2 resolve to real text,
    and so citation faithfulness (Section 10) is measurable rather than assumed.
    """

    clause_ref: str | None = Field(
        default=None, description="Clause/section label as printed, e.g. '4.2'."
    )
    source_page: int | None = Field(
        default=None, ge=1, description="1-indexed page in the source document."
    )
    source_snippet: str | None = Field(
        default=None,
        max_length=2000,
        description="Verbatim text the value was read from. Never paraphrase.",
    )
    extraction_confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Optional model-reported confidence."
    )


class Provenanced(SchemaModel):
    """Mixin for any extracted row that must be citable."""

    provenance: Provenance = Field(default_factory=Provenance)


# --------------------------------------------------------------------------- #
# Money
# --------------------------------------------------------------------------- #
class MoneyAmount(SchemaModel):
    """An amount kept in both the form it was written and canonical rupees.

    `amount_inr` is what rules compare against; `raw_text` is what gets shown to
    a human and what an auditor checks the normalization against. A None
    `amount_inr` with a present `raw_text` means "seen but not parseable" --
    that must surface as needs-manual-check, never as zero.
    """

    raw_text: str | None = Field(
        default=None, description="As printed, e.g. 'Rs. 5 Cr' or '5,00,00,000'."
    )
    amount_inr: Decimal | None = Field(
        default=None, ge=0, description="Canonical absolute rupees (Section 6)."
    )

    @model_validator(mode="after")
    def _derive_canonical(self) -> "MoneyAmount":
        if self.amount_inr is None and self.raw_text:
            object.__setattr__(self, "amount_inr", try_normalize_amount(self.raw_text))
        return self

    @property
    def is_resolved(self) -> bool:
        return self.amount_inr is not None

    @classmethod
    def parse(cls, raw: str | int | float | Decimal | None) -> "MoneyAmount | None":
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None
        return cls(raw_text=str(raw))


class YearlyTurnover(Provenanced):
    """Section 6: turnover: [ { year, amount } ]."""

    year: int = Field(ge=1900, le=2200, description="Financial year, e.g. 2023.")
    amount: MoneyAmount

    @field_validator("year", mode="before")
    @classmethod
    def _coerce_year(cls, v: object) -> object:
        """Accept '2023-24' / 'FY2023' forms and keep the opening year."""
        if isinstance(v, str):
            import re

            match = re.search(r"(19|20)\d{2}", v)
            if match:
                return int(match.group(0))
        return v
