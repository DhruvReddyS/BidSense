"""Gap report data model (Section 4.3, 4.4, 4.6)."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Provenance


class CheckStatus(StrEnum):
    """Section 4.3 asks for Match / Partial / Missing. Two more states exist
    because pretending to have decided is worse than saying we could not."""

    MATCH = "match"
    PARTIAL = "partial"
    MISSING = "missing"
    # Section 4.3: format/procedural rules are usually visual, not textual.
    MANUAL_CHECK = "manual_check"
    # A value the extractor could not resolve on either side. Distinct from
    # MISSING: "we don't know" must never be rendered as "you failed".
    NOT_ASSESSABLE = "not_assessable"


class RequirementKind(StrEnum):
    DOCUMENT = "document"
    NUMERIC = "numeric"
    BOOLEAN = "boolean"
    FORMAT_RULE = "format_rule"


class Severity(StrEnum):
    """Drives ordering of the Section 4.6 action list."""

    DISQUALIFYING = "disqualifying"   # mandatory criterion definitively failed
    ACTION_NEEDED = "action_needed"   # fixable before submission
    REVIEW = "review"                 # needs a human look
    INFO = "info"


class GapItem(BaseModel):
    """One requirement, checked. Both provenances are carried so the UI can show
    the tender clause beside the bid text it was checked against."""

    model_config = ConfigDict(extra="forbid")

    requirement: str
    kind: RequirementKind
    status: CheckStatus
    severity: Severity

    required_value: str | None = None
    found_value: str | None = None
    explanation: str = Field(description="Plain language, shown directly to the vendor.")

    is_mandatory: bool = True
    match_method: str | None = None
    match_score: float | None = None

    notification_provenance: Provenance | None = None
    submission_provenance: Provenance | None = None

    @property
    def blocks_submission(self) -> bool:
        return self.severity is Severity.DISQUALIFYING


class ScorePreviewItem(BaseModel):
    """Section 4.4 -- only ever populated when the notification publishes weights."""

    model_config = ConfigDict(extra="forbid")

    factor: str
    weightage: float
    status: CheckStatus
    provenance: Provenance | None = None


class ScorePreview(BaseModel):
    """Deliberately not a number when weights are unpublished.

    Section 4.4 makes this a credibility feature: if the notification does not
    state scoring weightage, the system shows compliance status only and says so.
    `available=False` is a first-class result, not an error.
    """

    model_config = ConfigDict(extra="forbid")

    available: bool
    items: list[ScorePreviewItem] = Field(default_factory=list)
    total_weightage: float | None = None
    unavailable_reason: str | None = None


class ActionItem(BaseModel):
    """Section 4.6 -- a plain-language to-do for a non-technical vendor."""

    model_config = ConfigDict(extra="forbid")

    action: str
    severity: Severity
    requirement: str
    clause_ref: str | None = None


class GapReport(BaseModel):
    """The Section 4.3 cross-check, plus 4.4's preview and 4.6's action list."""

    model_config = ConfigDict(extra="forbid")

    tender_id: str
    vendor_id: str
    vendor_name: str | None = None
    items: list[GapItem] = Field(default_factory=list)
    score_preview: ScorePreview
    action_list: list[ActionItem] = Field(default_factory=list)

    # --- summary counts, computed rather than stored, so they cannot drift ---
    @property
    def counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in CheckStatus}
        for item in self.items:
            counts[item.status.value] += 1
        return counts

    @property
    def blocking_items(self) -> list[GapItem]:
        return [i for i in self.items if i.blocks_submission]

    @property
    def is_compliant(self) -> bool:
        """No mandatory requirement definitively failed.

        Deliberately not "everything is green": items needing manual check or
        left unassessable keep this False-adjacent -- see `verdict`.
        """
        return not self.blocking_items

    @property
    def verdict(self) -> str:
        """Three-way, because a clean run and an undecidable run are different
        answers and a vendor is entitled to know which one they got."""
        if self.blocking_items:
            return "not_compliant"
        if any(
            i.status in (CheckStatus.MANUAL_CHECK, CheckStatus.NOT_ASSESSABLE)
            for i in self.items
        ):
            return "needs_review"
        return "compliant"


def format_money(value: Decimal | None) -> str:
    from app.normalize.money import format_inr

    return format_inr(value) if value is not None else "not stated"
