"""Vendor Submission schema (Section 6).

Same schema whether the document arrives through Part 1 (a vendor self-checking
their own draft, 4.2) or Part 2 (bulk ingestion by a reviewer, 5.1). Part 1
simply never advances `status` past PENDING.
"""

from __future__ import annotations

from datetime import date

from pydantic import Field, model_validator

from app.schemas.common import (
    MoneyAmount,
    Provenance,
    Provenanced,
    SchemaModel,
    VendorStatus,
    YearlyTurnover,
)


class Certification(Provenanced):
    """Section 6: { name, valid_till, doc_present: bool }."""

    name: str
    valid_till: date | None = None
    doc_present: bool = False

    def is_valid_on(self, when: date) -> bool | None:
        """None means unknown expiry -- a borderline case (9.2.2) that should be
        flagged for manual check, not silently treated as valid."""
        if not self.doc_present:
            return False
        if self.valid_till is None:
            return None
        return self.valid_till >= when


class PastProject(Provenanced):
    """Section 6: { client, value, year, description }."""

    client: str | None = None
    value: MoneyAmount | None = None
    year: int | None = Field(default=None, ge=1900, le=2200)
    description: str | None = Field(
        default=None,
        description="Narrative text; also chunked into the vector store (Section 7).",
    )


class SubmittedDocument(Provenanced):
    """Section 6: { doc_name, present: bool }.

    `matched_requirement` records which notification `mandatory_documents` entry
    this satisfied, and `match_method` how it was matched -- Section 6 requires
    alias/embedding matching rather than exact strings, so the check must record
    how it concluded a match for the audit trail (5.5).
    """

    doc_name: str
    present: bool = False
    matched_requirement: str | None = None
    match_method: str | None = Field(
        default=None, description="'exact' | 'alias' | 'embedding' | None."
    )
    match_score: float | None = Field(default=None, ge=0.0, le=1.0)


class VendorSubmission(SchemaModel):
    """The full Section 6 Vendor Submission Schema."""

    vendor_id: str = Field(description="Stable id, matches the tracking sheet (9.4).")
    vendor_name: str
    tender_id: str | None = Field(
        default=None, description="Notification this bid was submitted against."
    )

    turnover: list[YearlyTurnover] = Field(default_factory=list)
    years_in_business: float | None = Field(default=None, ge=0)
    certifications: list[Certification] = Field(default_factory=list)
    past_projects: list[PastProject] = Field(default_factory=list)
    documents_submitted: list[SubmittedDocument] = Field(default_factory=list)

    technical_approach_text: str | None = Field(
        default=None,
        description="Free text -> vector store (Section 7). Not stored for SQL filtering.",
    )
    pricing_summary: str | None = None
    quoted_price: MoneyAmount | None = Field(
        default=None,
        description=(
            "Canonical form of the bid price when one is extractable. Section 6 "
            "names only free-text `pricing_summary`; this is kept alongside so "
            "5.3's pricing-competitiveness factor has a comparable number."
        ),
    )

    is_blacklisted: bool = Field(
        default=False,
        description=(
            "Section 5.8 -- hard-fail at Level 1. Set by a reviewer from an "
            "official debarment list, or derived from the bidder's own "
            "disclosure in `debarment_disclosure`."
        ),
    )
    debarment_disclosure: str | None = Field(
        default=None,
        description=(
            "Verbatim text where the bid admits to being debarred, blacklisted "
            "or under insolvency. Kept so the elimination can quote the bidder's "
            "own words rather than asserting a flag."
        ),
    )
    status: VendorStatus = VendorStatus.PENDING
    elimination_reason: str | None = Field(
        default=None,
        description="Human-readable reason, e.g. 'Turnover ₹2.1Cr < required ₹5Cr'.",
    )
    elimination_provenance: Provenance | None = Field(
        default=None, description="The failed clause, cited (Section 5.2)."
    )

    @model_validator(mode="after")
    def _eliminated_requires_reason(self) -> "VendorSubmission":
        """Section 5.2 makes elimination defensible-if-challenged. An eliminated
        vendor with no stated reason is a bug, not a valid state."""
        if self.status is VendorStatus.ELIMINATED and not self.elimination_reason:
            raise ValueError("status 'eliminated' requires an elimination_reason")
        if self.status is not VendorStatus.ELIMINATED and self.elimination_reason:
            raise ValueError(
                f"elimination_reason set on non-eliminated vendor (status={self.status})"
            )
        return self

    def latest_turnover(self) -> YearlyTurnover | None:
        resolved = [t for t in self.turnover if t.amount.is_resolved]
        return max(resolved, key=lambda t: t.year) if resolved else None
