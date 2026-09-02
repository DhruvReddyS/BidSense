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
    #: Set when the requirement binds only some bidders (a JV agreement, an MSME
    #: concession). Carried through to the action list so a sole proprietor is
    #: not handed "Check yourself: submit your Joint Venture Agreement" -- on the
    #: GHMC tender that wording accounted for nine of a compliant bidder's
    #: twenty-three to-dos, none of which applied to them.
    conditional_on: str | None = None

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


class ActionGroup(StrEnum):
    """What kind of problem this is, which decides what a vendor does about it.

    The distinction that matters is fixability. A missing certificate is a
    morning's work. Turnover below the floor cannot be fixed before the deadline
    at all -- it means "do not bid, or bid as a joint venture". Sorting purely by
    severity buries the second kind underneath forty of the first, because every
    unmet mandatory requirement is equally "disqualifying".
    """

    # Cannot be fixed by uploading anything: a threshold you do not meet, or a
    # disqualifying condition.
    HARD_FAIL = "hard_fail"
    # Fixable before the deadline: attach the document.
    UPLOAD = "upload"
    # We could not read a value; the vendor must state it clearly.
    CLARIFY = "clarify"
    # Needs a human eye: formatting, signing, conditional applicability.
    VERIFY = "verify"


class ActionItem(BaseModel):
    """Section 4.6 -- a plain-language to-do for a non-technical vendor."""

    model_config = ConfigDict(extra="forbid")

    action: str
    severity: Severity
    group: ActionGroup
    requirement: str
    clause_ref: str | None = None
    #: Non-null when this only applies to some bidders. The UI groups these
    #: separately; they are still listed, because deciding on the vendor's
    #: behalf that they are not a joint venture is not ours to make.
    applies_only_if: str | None = None

    @property
    def is_blocking(self) -> bool:
        """A to-do that stops the bid going in, as opposed to one to check."""
        return self.group in (ActionGroup.HARD_FAIL, ActionGroup.UPLOAD)


class Completion(BaseModel):
    """A count of mandatory requirements satisfied. Explicitly NOT a score.

    Section 4.4 forbids inventing a score the tender did not publish, and that
    rule is a credibility feature rather than a limitation -- a number a vendor
    cannot trace to a clause is worse than no number. This does not break it:
    every unit here is one requirement, read from the tender, checked against
    the bid, and clickable through to both. Nothing is weighted, nothing is
    combined, and two tenders' counts are not comparable.

    The distinction is thin enough that it has to be stated in the UI copy, not
    only in this docstring -- a bare "7/9" beside a progress bar reads as a
    score to every person who has ever seen one. `caveat` is that copy, carried
    with the number so the two cannot be separated.
    """

    model_config = ConfigDict(extra="forbid")

    satisfied: int
    total: int
    #: Mandatory requirements that could not be decided either way. Counted
    #: separately because folding them into "not satisfied" would report a
    #: vendor as failing something we merely could not read.
    undetermined: int = 0

    @property
    def label(self) -> str:
        return f"{self.satisfied} of {self.total} mandatory requirements satisfied"

    @property
    def caveat(self) -> str:
        return (
            "This is a count of requirements met, not a score. The tender does "
            "not publish weightings, so nothing here is weighted and this number "
            "cannot be compared against another tender's."
        )


class GapReport(BaseModel):
    """The Section 4.3 cross-check, plus 4.4's preview and 4.6's action list."""

    model_config = ConfigDict(extra="forbid")

    tender_id: str
    vendor_id: str
    vendor_name: str | None = None
    items: list[GapItem] = Field(default_factory=list)
    score_preview: ScorePreview
    action_list: list[ActionItem] = Field(default_factory=list)

    @property
    def completion(self) -> Completion:
        """Mandatory requirements satisfied, counted rather than scored.

        Only MATCH counts as satisfied. A partial, a manual check and an
        unreadable value are all "we have not established this", and rolling
        them in either direction would be inventing information -- upward it
        flatters a bid, downward it reports a vendor as failing something nobody
        checked.
        """
        mandatory = [i for i in self.items if i.is_mandatory]
        satisfied = sum(1 for i in mandatory if i.status is CheckStatus.MATCH)
        undetermined = sum(
            1
            for i in mandatory
            if i.status
            in (CheckStatus.PARTIAL, CheckStatus.MANUAL_CHECK, CheckStatus.NOT_ASSESSABLE)
        )
        return Completion(
            satisfied=satisfied, total=len(mandatory), undetermined=undetermined
        )

    @property
    def action_counts(self) -> dict[str, int]:
        """How the to-do list splits, so the UI can lead with what blocks a bid.

        A compliant bidder on a 49-document tender still collects twenty-odd
        "check this yourself" items, and rendering them in one flat list makes a
        clean bid look like a disaster. These counts are what lets the two be
        shown differently.
        """
        return {
            "blocking": sum(1 for a in self.action_list if a.is_blocking),
            "to_check": sum(
                1 for a in self.action_list if not a.is_blocking and not a.applies_only_if
            ),
            "conditional": sum(1 for a in self.action_list if a.applies_only_if),
        }

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
        left unassessable keep this False-adjacent -- see `verdict`. A report
        that checked nothing is not compliant either, since nothing was tested.
        """
        return bool(self.items) and not self.blocking_items

    @property
    def verdict(self) -> str:
        """Four-way. A clean run, an undecidable run and a run that checked
        nothing at all are three different answers, and a vendor is entitled to
        know which one they got.

        `not_checked` exists because the alternative is worse than useless: when
        extraction yields no requirements -- a failed run, a scanned notification
        with no OCR, a document in a format the parser could not read -- an
        empty report would otherwise fall through to "compliant" and tell every
        vendor they have no blocking issues. Silence is not a pass.
        """
        if not self.items:
            return "not_checked"
        if self.blocking_items:
            return "not_compliant"
        if any(
            i.status in (CheckStatus.MANUAL_CHECK, CheckStatus.NOT_ASSESSABLE)
            for i in self.items
        ):
            return "needs_review"
        return "compliant"

    @property
    def was_checked(self) -> bool:
        """False when nothing could be checked. Distinct from `is_compliant`,
        which is about whether anything failed."""
        return bool(self.items)


def format_money(value: Decimal | None) -> str:
    from app.normalize.money import format_inr

    return format_inr(value) if value is not None else "not stated"
