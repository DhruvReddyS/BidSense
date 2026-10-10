"""What a corrigendum does to bids that have already been evaluated (5.6).

An amendment is the most consequential event in a live tender. A corrigendum
that raises a turnover floor from Rs 3 Cr to Rs 5 Cr does not merely edit a
document: bidders who qualified no longer do, and they have to be told, because
the alternative is a committee opening bids against rules the bidders never
saw.

`app.review.corrigendum` already replayed the easy fields -- deadlines, EMD,
contract value -- and explicitly refused `eligibility_criteria` and
`mandatory_documents`, which are precisely the paths that change a verdict. This
module implements them, and three things make that harder than re-running the
rule engine.

**Positional paths are not trustworthy.** Section 6 documents `field_path` as a
dotted path such as `eligibility_criteria[0].threshold_amount`, but neither
relationship declares an `order_by`, so the database returns those rows in
whatever order it likes and index 0 is not a stable identity. Resolving an
amendment positionally would therefore sometimes edit the wrong criterion, and
silently. We resolve by identity instead -- the clause the amendment cites, then
the value it says it is replacing -- and treat the index as a hint of last
resort. An amendment whose `old_value` matches nothing currently stored is
reported as a conflict rather than guessed at: it usually means the tender has
already been amended once and this corrigendum was written against the original.

**Relaxation and tightening are not symmetric.** Reinstating a bidder who was
wrongly excluded is always safe. Excluding one who previously qualified is not.

**Timing decides whether recomputation is even legitimate.** A corrigendum
issued BEFORE the submission deadline is part of the tender: bidders can read it
and respond, and re-deciding is simply correct. One issued AFTER the deadline
cannot be answered by anyone -- a bid was prepared against the rules as
published, and eliminating it for failing a requirement that did not exist at
submission time is a decision a procurement committee has to take deliberately,
not one a pipeline should take silently. So a retroactive tightening is
surfaced for human review and never auto-applied; a retroactive relaxation is
applied, because it can only help the bidder.

That asymmetry is the substance of this module. Everything else is bookkeeping.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from app.compliance.elimination import decide
from app.compliance.gap import build_gap_report
from app.db.repository import to_notification_schema, to_submission_schema
from app.normalize.money import try_normalize_amount
from app.schemas.common import VendorStatus

logger = logging.getLogger(__name__)

#: `eligibility_criteria[2].threshold_amount` -> ("eligibility_criteria", 2, "threshold_amount")
_PATH = re.compile(
    r"^(?P<collection>eligibility_criteria|mandatory_documents)"
    r"(?:\[(?P<index>\d+|\+)\])?"
    r"(?:\.(?P<attribute>\w+))?$"
)


class FlipDirection(StrEnum):
    """What an amendment did to one bid's standing."""

    NEWLY_ELIMINATED = "newly_eliminated"   # qualified before, does not now
    REINSTATED = "reinstated"               # excluded before, qualifies now
    REASON_CHANGED = "reason_changed"       # still excluded, different clause
    UNCHANGED = "unchanged"

    @property
    def is_adverse(self) -> bool:
        """True when the bidder is worse off than before the amendment."""
        return self is FlipDirection.NEWLY_ELIMINATED

    @property
    def needs_notice(self) -> bool:
        """Whether this bidder has to be told.

        A changed reason counts: the clause a bidder is excluded under is what
        they would contest, so replacing it silently removes their grounds.
        """
        return self is not FlipDirection.UNCHANGED


class ChangeOutcome(StrEnum):
    APPLIED = "applied"
    CONFLICT = "conflict"           # old_value matches nothing stored
    AMBIGUOUS = "ambiguous"         # matches more than one row
    UNSUPPORTED = "unsupported"     # a path shape we decline to guess at


@dataclass
class ChangeResult:
    field_path: str
    outcome: ChangeOutcome
    detail: str = ""

    @property
    def applied(self) -> bool:
        return self.outcome is ChangeOutcome.APPLIED


@dataclass
class BidImpact:
    """One bid, before and after."""

    vendor_id: str
    before_status: str
    after_status: str
    before_clause: str | None
    after_clause: str | None
    direction: FlipDirection

    @property
    def needs_notice(self) -> bool:
        return self.direction.needs_notice

    def describe(self) -> str:
        if self.direction is FlipDirection.UNCHANGED:
            return "unaffected"
        if self.direction is FlipDirection.REASON_CHANGED:
            return (f"still eliminated, clause "
                    f"{self.before_clause or '—'} -> {self.after_clause or '—'}")
        return f"{self.before_status} -> {self.after_status}"


@dataclass
class CorrigendumImpact:
    """The full consequence of one amendment, before anything is committed."""

    corrigendum_id: str
    changes: list[ChangeResult] = field(default_factory=list)
    impacts: list[BidImpact] = field(default_factory=list)
    issued_date: date | None = None
    submission_deadline: date | None = None

    @property
    def applied_changes(self) -> list[ChangeResult]:
        return [c for c in self.changes if c.applied]

    @property
    def unresolved_changes(self) -> list[ChangeResult]:
        return [c for c in self.changes if not c.applied]

    @property
    def is_retroactive(self) -> bool:
        """Issued after the deadline it amends, so no bidder could respond.

        Unknown dates are treated as NOT retroactive: a missing issued_date is
        an extraction gap, and refusing to apply every amendment whose date we
        failed to read would stall the tender rather than protect anyone. The
        gap surfaces in `warnings` instead.
        """
        if self.issued_date is None or self.submission_deadline is None:
            return False
        return self.issued_date > self.submission_deadline

    @property
    def adverse(self) -> list[BidImpact]:
        return [i for i in self.impacts if i.direction.is_adverse]

    @property
    def requires_human_review(self) -> bool:
        """A retroactive amendment that excludes someone who had qualified.

        This is the case a pipeline must not decide on its own. Relaxations are
        excluded deliberately: they can only help a bidder, so applying one
        retroactively harms nobody.
        """
        return self.is_retroactive and bool(self.adverse)

    @property
    def notify(self) -> list[BidImpact]:
        return [i for i in self.impacts if i.needs_notice]

    @property
    def warnings(self) -> list[str]:
        out = []
        if self.issued_date is None:
            out.append("corrigendum has no issued date; retroactivity "
                       "could not be determined")
        if self.submission_deadline is None:
            out.append("tender has no submission deadline; retroactivity "
                       "could not be determined")
        for change in self.unresolved_changes:
            out.append(f"{change.field_path}: {change.outcome.value}"
                       + (f" -- {change.detail}" if change.detail else ""))
        return out

    def summary(self) -> str:
        counts: dict[str, int] = {}
        for impact in self.impacts:
            counts[impact.direction.value] = counts.get(impact.direction.value, 0) + 1
        parts = [f"{len(self.applied_changes)}/{len(self.changes)} change(s) applied"]
        for direction in FlipDirection:
            if counts.get(direction.value):
                parts.append(f"{counts[direction.value]} {direction.value}")
        if self.requires_human_review:
            parts.append("REQUIRES HUMAN REVIEW (retroactive and adverse)")
        return "; ".join(parts)


# --------------------------------------------------------------------------- #
# Resolving an amendment to the row it actually refers to.
# --------------------------------------------------------------------------- #

def _normalise(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _criterion_candidates(notification_row, change) -> list:
    """Rows this change could mean, most specific signal first.

    Order matters: a clause reference is an identity the tender itself printed,
    whereas a value is only evidence. An index is neither, because the rows have
    no declared order.
    """
    criteria = list(notification_row.eligibility_criteria)

    clause = _normalise(getattr(change, "clause_ref", None))
    if clause:
        by_clause = [c for c in criteria if _normalise(c.clause_ref) == clause]
        if by_clause:
            return by_clause

    old = _normalise(change.old_value)
    if old:
        by_value = [
            c for c in criteria
            if _normalise(c.threshold_raw) == old
            or _normalise(str(c.threshold_amount_inr)) == old
            or _normalise(str(c.threshold_number)) == old
            or old in _normalise(c.criterion)
        ]
        if by_value:
            return by_value

    return []


def _document_candidates(notification_row, change) -> list:
    documents = list(notification_row.mandatory_documents)
    target = _normalise(change.old_value)
    if not target:
        return []
    exact = [d for d in documents if _normalise(d.doc_name) == target]
    if exact:
        return exact
    return [
        d for d in documents
        if target in _normalise(d.doc_name)
        or any(target == _normalise(a) for a in (d.aliases or []))
    ]


def apply_change(session, notification_row, change) -> ChangeResult:
    """Apply one amendment to the stored requirements. Never guesses."""
    path = change.field_path or ""
    match = _PATH.match(path)
    if match is None:
        return ChangeResult(path, ChangeOutcome.UNSUPPORTED,
                            "not a recognised requirement path")

    collection = match.group("collection")
    attribute = match.group("attribute")

    if collection == "eligibility_criteria":
        return _apply_criterion(session, notification_row, change, attribute)
    return _apply_document(session, notification_row, change, match.group("index"))


def _apply_criterion(session, notification_row, change, attribute) -> ChangeResult:
    path = change.field_path
    candidates = _criterion_candidates(notification_row, change)

    if not candidates:
        return ChangeResult(
            path, ChangeOutcome.CONFLICT,
            f"no stored criterion matches clause "
            f"{getattr(change, 'clause_ref', None) or '—'} or old value "
            f"{change.old_value!r}; the tender may already have been amended",
        )
    if len(candidates) > 1:
        return ChangeResult(
            path, ChangeOutcome.AMBIGUOUS,
            f"{len(candidates)} stored criteria match; refusing to pick one",
        )

    row = candidates[0]
    new_value = change.new_value

    # Withdrawal: the requirement is dropped rather than changed. Marking it
    # non-mandatory rather than deleting keeps the audit trail -- a committee
    # may need to show that the criterion existed and was withdrawn.
    if new_value is None or not new_value.strip():
        row.is_mandatory = False
        session.flush()
        return ChangeResult(path, ChangeOutcome.APPLIED,
                            f"criterion withdrawn: {row.criterion[:60]}")

    if attribute in (None, "threshold_amount", "threshold_amount_inr", "threshold_raw"):
        amount = try_normalize_amount(new_value)
        if amount is None:
            return ChangeResult(path, ChangeOutcome.UNSUPPORTED,
                                f"could not read an amount from {new_value!r}")
        row.threshold_raw = new_value
        row.threshold_amount_inr = amount
        session.flush()
        return ChangeResult(path, ChangeOutcome.APPLIED,
                            f"threshold {change.old_value!r} -> {new_value!r}")

    if attribute in ("threshold_number", "experience_years"):
        try:
            row.threshold_number = float(re.sub(r"[^\d.]", "", new_value))
        except ValueError:
            return ChangeResult(path, ChangeOutcome.UNSUPPORTED,
                                f"could not read a number from {new_value!r}")
        row.threshold_raw = new_value
        session.flush()
        return ChangeResult(path, ChangeOutcome.APPLIED,
                            f"threshold {change.old_value!r} -> {new_value!r}")

    if attribute == "is_mandatory":
        row.is_mandatory = new_value.strip().casefold() in {"true", "yes", "1"}
        session.flush()
        return ChangeResult(path, ChangeOutcome.APPLIED,
                            f"is_mandatory -> {row.is_mandatory}")

    return ChangeResult(path, ChangeOutcome.UNSUPPORTED,
                        f"no rule for attribute {attribute!r}")


def _apply_document(session, notification_row, change, index) -> ChangeResult:
    from app.db.models import MandatoryDocumentRow

    path = change.field_path
    new_value = (change.new_value or "").strip()
    old_value = (change.old_value or "").strip()

    # Addition: nothing is being replaced.
    if index == "+" or (not old_value and new_value):
        existing = {_normalise(d.doc_name) for d in notification_row.mandatory_documents}
        if _normalise(new_value) in existing:
            return ChangeResult(path, ChangeOutcome.APPLIED,
                                f"already required: {new_value}")
        session.add(MandatoryDocumentRow(
            notification_id=notification_row.id,
            doc_name=new_value,
            aliases=[],
            clause_ref=getattr(change, "clause_ref", None),
            source_page=getattr(change, "source_page", None),
            source_snippet=getattr(change, "source_snippet", None),
        ))
        session.flush()
        return ChangeResult(path, ChangeOutcome.APPLIED,
                            f"document now required: {new_value}")

    candidates = _document_candidates(notification_row, change)
    if not candidates:
        return ChangeResult(path, ChangeOutcome.CONFLICT,
                            f"no required document matches {old_value!r}")
    if len(candidates) > 1:
        return ChangeResult(path, ChangeOutcome.AMBIGUOUS,
                            f"{len(candidates)} documents match {old_value!r}")

    row = candidates[0]

    # Removal: no longer required.
    if not new_value:
        notification_row.mandatory_documents.remove(row)
        session.flush()
        return ChangeResult(path, ChangeOutcome.APPLIED,
                            f"document no longer required: {row.doc_name}")

    # Rename: keep the old name as an alias, so a bid that enclosed the
    # document under its previous name still matches.
    previous = row.doc_name
    row.aliases = list(dict.fromkeys([*(row.aliases or []), previous]))
    row.doc_name = new_value
    session.flush()
    return ChangeResult(path, ChangeOutcome.APPLIED,
                        f"document renamed: {previous!r} -> {new_value!r} "
                        f"(old name kept as an alias)")


# --------------------------------------------------------------------------- #
# Assessing the consequence.
# --------------------------------------------------------------------------- #

def _snapshot(notification_row) -> dict[str, tuple[str, str | None]]:
    return {
        str(row.vendor_id): (str(row.status), row.elimination_clause_ref)
        for row in notification_row.submissions
    }


def _redecide(session, notification_row) -> dict[str, tuple[str, str | None]]:
    """Re-run the rule engine over every bid and write the result."""
    notification = to_notification_schema(notification_row)
    out: dict[str, tuple[str, str | None]] = {}
    for row in notification_row.submissions:
        decision = decide(build_gap_report(notification, to_submission_schema(row)))
        row.status = decision.status
        row.elimination_reason = decision.reason
        row.elimination_clause_ref = decision.clause_ref
        row.elimination_source_page = decision.source_page
        row.elimination_source_snippet = decision.source_snippet
        out[str(row.vendor_id)] = (str(decision.status), decision.clause_ref)
    session.flush()
    return out


def _direction(before: tuple[str, str | None],
               after: tuple[str, str | None]) -> FlipDirection:
    was_out = before[0] == str(VendorStatus.ELIMINATED)
    is_out = after[0] == str(VendorStatus.ELIMINATED)
    if was_out and not is_out:
        return FlipDirection.REINSTATED
    if is_out and not was_out:
        return FlipDirection.NEWLY_ELIMINATED
    if is_out and was_out and before[1] != after[1]:
        return FlipDirection.REASON_CHANGED
    return FlipDirection.UNCHANGED


def assess(session, notification_row, corrigendum_row) -> CorrigendumImpact:
    """Apply the amendment and report what it did, without committing.

    The caller decides whether to keep it. Running inside a SAVEPOINT means a
    dry run cannot leave half an amendment behind if a later change conflicts,
    which matters because a corrigendum is a single document and applying three
    of its five clauses is not a state any tender should be in.
    """
    impact = CorrigendumImpact(
        corrigendum_id=corrigendum_row.corrigendum_id,
        issued_date=corrigendum_row.issued_date,
        submission_deadline=notification_row.submission_deadline,
    )

    before = _snapshot(notification_row)
    savepoint = session.begin_nested()
    try:
        for change in corrigendum_row.changed_fields:
            impact.changes.append(apply_change(session, notification_row, change))

        after = _redecide(session, notification_row) if impact.applied_changes else before

        for vendor_id, previous in before.items():
            current = after.get(vendor_id, previous)
            impact.impacts.append(BidImpact(
                vendor_id=vendor_id,
                before_status=previous[0], after_status=current[0],
                before_clause=previous[1], after_clause=current[1],
                direction=_direction(previous, current),
            ))
    finally:
        # Always roll back: `assess` reports, `apply` decides.
        savepoint.rollback()

    return impact


def apply(session, notification_row, corrigendum_row) -> CorrigendumImpact:
    """Assess, then persist unless a human has to look at it first.

    Returns the impact either way. When `requires_human_review` is set nothing
    is written and `corrigendum_row.applied` stays False, so the amendment
    remains visibly outstanding rather than quietly absorbed.
    """
    impact = assess(session, notification_row, corrigendum_row)

    if impact.requires_human_review:
        logger.warning(
            "Corrigendum %s is retroactive (issued %s, deadline %s) and would "
            "newly eliminate %d bid(s). Not applied; a committee has to decide "
            "whether a requirement published after the deadline may exclude a "
            "bid prepared before it.",
            impact.corrigendum_id, impact.issued_date,
            impact.submission_deadline, len(impact.adverse),
        )
        corrigendum_row.applied = False
        session.flush()
        return impact

    for change in corrigendum_row.changed_fields:
        apply_change(session, notification_row, change)
    if impact.applied_changes:
        _redecide(session, notification_row)
        from app.vector.qdrant import retag_status
        for row in notification_row.submissions:
            try:
                retag_status(str(row.id), row.status)
            except Exception:
                # The vector store mirrors status for scoped retrieval; a
                # failure there must not roll back a decision already made in
                # Postgres, which is the system of record.
                logger.warning("Could not retag %s in the vector store",
                               row.id, exc_info=True)

    corrigendum_row.applied = bool(impact.applied_changes) and not impact.unresolved_changes
    session.flush()
    return impact
