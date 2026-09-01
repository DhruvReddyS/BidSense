"""Gap report engine (Section 4.3, 4.4, 4.6).

Deterministic, rule-based comparison of two Section 6 schema instances. No LLM
anywhere in this file, by design: Section 2.1.3 argues that once a value has
been extracted, comparing it against a threshold is auditable logic, not a
judgment call -- and a vendor's disqualification is legally consequential.

Three principles run through every check:

  * A value we could not resolve is NOT_ASSESSABLE, never MISSING. "We don't
    know" must not be rendered to a vendor as "you failed".
  * Format and procedural rules are always MANUAL_CHECK (Section 4.3): they are
    usually visual, and claiming to have verified them would be a lie.
  * Every conclusion carries both provenances, so the vendor can see the tender
    clause beside the text in their own bid that was checked against it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.compliance.matching import (
    MatchResult,
    canonical_form,
    match_document,
    normalise,
)
from app.compliance.models import (
    ActionItem,
    CheckStatus,
    GapItem,
    GapReport,
    RequirementKind,
    ScorePreview,
    ScorePreviewItem,
    Severity,
    format_money,
)
from app.schemas.common import CriterionType, Provenance
from app.schemas.notification import EligibilityCriterion, TenderNotification
from app.schemas.submission import VendorSubmission

# Words in a criterion that indicate it is about turnover rather than, say,
# project value -- used to pick which extracted number to compare against.
_TURNOVER_HINTS = ("turnover", "revenue", "annual receipt", "gross receipt")
_EXPERIENCE_HINTS = ("experience", "years in business", "operating", "established")
_PROJECT_HINTS = ("project", "work", "contract", "assignment", "order")


def _mentions(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(h in lowered for h in hints)


# --------------------------------------------------------------------------- #
# Document presence (Section 4.3 "hard document checklist")
# --------------------------------------------------------------------------- #
def _check_documents(
    notification: TenderNotification,
    submission: VendorSubmission,
    *,
    use_embeddings: bool,
) -> list[GapItem]:
    present_names = [d.doc_name for d in submission.documents_submitted if d.present]
    # A document listed but explicitly marked absent is a distinct signal from
    # one never mentioned -- the vendor knows about it and hasn't attached it.
    declared_absent = {
        d.doc_name.lower() for d in submission.documents_submitted if not d.present
    }
    certificate_names = [c.name for c in submission.certifications if c.doc_present]

    # A bid can contradict itself: the checklist marks a certificate as not
    # enclosed while the certifications section still lists it. The explicit
    # "not enclosed" wins. Telling a vendor a document is present when their own
    # checklist says it is not is the dangerous direction of this error -- they
    # would submit without it.
    absent_forms = {normalise(name) for name in declared_absent}
    absent_canonicals = {
        canonical_form(name) for name in declared_absent if canonical_form(name)
    }

    def contradicted(name: str) -> bool:
        return normalise(name) in absent_forms or (
            canonical_form(name) is not None and canonical_form(name) in absent_canonicals
        )

    haystack = [n for n in present_names + certificate_names if not contradicted(n)]

    items: list[GapItem] = []
    for required in notification.mandatory_documents:
        result = match_document(
            required.doc_name,
            haystack,
            extra_aliases=required.aliases,
            use_embeddings=use_embeddings,
        )
        items.append(_document_item(required.doc_name, required.provenance, result, declared_absent))
    return items


def _document_item(
    doc_name: str,
    provenance: Provenance,
    result: MatchResult,
    declared_absent: set[str],
) -> GapItem:
    if result.matched and not result.is_uncertain:
        return GapItem(
            requirement=f"Submit {doc_name}",
            kind=RequirementKind.DOCUMENT,
            status=CheckStatus.MATCH,
            severity=Severity.INFO,
            required_value=doc_name,
            found_value=result.matched_name,
            explanation=(
                f"Found in your submission as “{result.matched_name}”."
                if result.method != "exact"
                else "Found in your submission."
            ),
            match_method=result.method,
            match_score=result.score,
            notification_provenance=provenance,
        )

    if result.matched and result.is_uncertain:
        # A borderline embedding match is reported as partial, not as settled.
        # Silently accepting it would tell a vendor they are covered when the
        # only evidence is two names that read alike.
        return GapItem(
            requirement=f"Submit {doc_name}",
            kind=RequirementKind.DOCUMENT,
            status=CheckStatus.PARTIAL,
            severity=Severity.REVIEW,
            required_value=doc_name,
            found_value=result.matched_name,
            explanation=(
                f"“{result.matched_name}” looks like it may satisfy this, but the "
                f"names differ enough (similarity {result.score:.2f}) that you "
                "should confirm it is the right document."
            ),
            match_method=result.method,
            match_score=result.score,
            notification_provenance=provenance,
        )

    explicitly_absent = doc_name.lower() in declared_absent or any(
        normalise(doc_name) == normalise(a) for a in declared_absent
    )
    return GapItem(
        requirement=f"Submit {doc_name}",
        kind=RequirementKind.DOCUMENT,
        status=CheckStatus.MISSING,
        severity=Severity.DISQUALIFYING,
        required_value=doc_name,
        found_value=None,
        explanation=(
            f"Your submission lists {doc_name} but marks it as not enclosed."
            if explicitly_absent
            else f"No document matching {doc_name} was found in your submission."
        ),
        match_score=result.score,
        notification_provenance=provenance,
    )


# --------------------------------------------------------------------------- #
# Numeric eligibility (Section 4.3 "numeric eligibility")
# --------------------------------------------------------------------------- #
def _check_numeric(
    criterion: EligibilityCriterion, submission: VendorSubmission
) -> GapItem:
    severity_if_failed = (
        Severity.DISQUALIFYING if criterion.is_mandatory else Severity.REVIEW
    )
    base = dict(
        requirement=criterion.criterion,
        kind=RequirementKind.NUMERIC,
        is_mandatory=criterion.is_mandatory,
        notification_provenance=criterion.provenance,
    )

    # --- money thresholds ---
    if criterion.threshold_amount is not None and criterion.threshold_amount.is_resolved:
        threshold = criterion.threshold_amount.amount_inr
        if _mentions(criterion.criterion, _TURNOVER_HINTS):
            return _compare_turnover(criterion, submission, threshold, severity_if_failed, base)
        if _mentions(criterion.criterion, _PROJECT_HINTS):
            return _compare_project_value(criterion, submission, threshold, severity_if_failed, base)
        return GapItem(
            status=CheckStatus.MANUAL_CHECK,
            severity=Severity.REVIEW,
            required_value=format_money(threshold),
            explanation=(
                "This is a monetary requirement, but it is not clear which figure "
                "in your bid it should be compared against. Check it manually."
            ),
            **base,
        )

    # --- plain-number thresholds (years, counts) ---
    if criterion.threshold_number is not None:
        if _mentions(criterion.criterion, _EXPERIENCE_HINTS):
            return _compare_experience(criterion, submission, severity_if_failed, base)
        if _mentions(criterion.criterion, _PROJECT_HINTS):
            return _compare_project_count(criterion, submission, severity_if_failed, base)
        return GapItem(
            status=CheckStatus.MANUAL_CHECK,
            severity=Severity.REVIEW,
            required_value=f"{criterion.threshold_number:g} {criterion.unit or ''}".strip(),
            explanation="Numeric requirement with no matching figure in your bid to compare. Check manually.",
            **base,
        )

    # --- threshold present in text but unresolvable ---
    return GapItem(
        status=CheckStatus.NOT_ASSESSABLE,
        severity=Severity.REVIEW,
        required_value=criterion.threshold_raw,
        explanation=(
            f"The requirement reads “{criterion.threshold_raw}”, which could not be "
            "read as a definite number. Check this one yourself."
            if criterion.threshold_raw
            else "No threshold could be read for this requirement. Check it manually."
        ),
        **base,
    )


def _compare_turnover(criterion, submission, threshold: Decimal, fail_severity, base) -> GapItem:
    resolved = [t for t in submission.turnover if t.amount.is_resolved]
    if not resolved:
        return GapItem(
            status=CheckStatus.NOT_ASSESSABLE,
            severity=Severity.REVIEW,
            required_value=format_money(threshold),
            found_value=(
                submission.turnover[0].amount.raw_text if submission.turnover else None
            ),
            explanation=(
                "No turnover figure in your bid could be read as a number. "
                "State it in figures (e.g. Rs. 5,00,00,000) so it can be checked."
            ),
            **base,
        )

    # Compare the best year the bidder declares: a tender asking for a minimum
    # turnover is satisfied by meeting it, and the bidder chooses which years to
    # present. Averaging here would invent a rule the tender didn't state.
    best = max(resolved, key=lambda t: t.amount.amount_inr)
    passed = best.amount.amount_inr >= threshold
    return GapItem(
        status=CheckStatus.MATCH if passed else CheckStatus.MISSING,
        severity=Severity.INFO if passed else fail_severity,
        required_value=format_money(threshold),
        found_value=f"{format_money(best.amount.amount_inr)} ({best.year})",
        explanation=(
            f"Your declared turnover of {format_money(best.amount.amount_inr)} in "
            f"{best.year} meets the requirement of {format_money(threshold)}."
            if passed
            else (
                f"Your highest declared turnover is "
                f"{format_money(best.amount.amount_inr)} ({best.year}), below the "
                f"required {format_money(threshold)}. You do not currently qualify "
                "on this criterion."
            )
        ),
        submission_provenance=best.provenance,
        **base,
    )


def _compare_project_value(criterion, submission, threshold: Decimal, fail_severity, base) -> GapItem:
    valued = [p for p in submission.past_projects if p.value and p.value.is_resolved]
    if not valued:
        return GapItem(
            status=CheckStatus.NOT_ASSESSABLE,
            severity=Severity.REVIEW,
            required_value=format_money(threshold),
            explanation="No past-project value in your bid could be read as a number. Check manually.",
            **base,
        )
    qualifying = [p for p in valued if p.value.amount_inr >= threshold]
    passed = bool(qualifying)
    best = max(valued, key=lambda p: p.value.amount_inr)
    return GapItem(
        status=CheckStatus.MATCH if passed else CheckStatus.MISSING,
        severity=Severity.INFO if passed else fail_severity,
        required_value=format_money(threshold),
        found_value=f"{len(qualifying)} project(s) at or above threshold; largest {format_money(best.value.amount_inr)}",
        explanation=(
            f"{len(qualifying)} of your listed projects meet or exceed "
            f"{format_money(threshold)}."
            if passed
            else (
                f"Your largest listed project is {format_money(best.value.amount_inr)}, "
                f"below the required {format_money(threshold)}."
            )
        ),
        submission_provenance=best.provenance,
        **base,
    )


def _compare_experience(criterion, submission, fail_severity, base) -> GapItem:
    required_years = criterion.threshold_number
    if submission.years_in_business is None:
        return GapItem(
            status=CheckStatus.NOT_ASSESSABLE,
            severity=Severity.REVIEW,
            required_value=f"{required_years:g} years",
            explanation=(
                "Your bid does not state how many years you have been in business. "
                "State it explicitly so this can be checked."
            ),
            **base,
        )
    passed = submission.years_in_business >= required_years
    return GapItem(
        status=CheckStatus.MATCH if passed else CheckStatus.MISSING,
        severity=Severity.INFO if passed else fail_severity,
        required_value=f"{required_years:g} years",
        found_value=f"{submission.years_in_business:g} years",
        explanation=(
            f"You state {submission.years_in_business:g} years of experience, "
            f"meeting the required {required_years:g}."
            if passed
            else (
                f"You state {submission.years_in_business:g} years of experience, "
                f"below the required {required_years:g}."
            )
        ),
        **base,
    )


def _compare_project_count(criterion, submission, fail_severity, base) -> GapItem:
    required_count = criterion.threshold_number
    actual = len(submission.past_projects)
    passed = actual >= required_count
    return GapItem(
        status=CheckStatus.MATCH if passed else CheckStatus.MISSING,
        severity=Severity.INFO if passed else fail_severity,
        required_value=f"{required_count:g} projects",
        found_value=f"{actual} projects",
        explanation=(
            f"You list {actual} projects, meeting the required {required_count:g}."
            if passed
            else f"You list {actual} projects, below the required {required_count:g}."
        ),
        **base,
    )


# --------------------------------------------------------------------------- #
# Boolean eligibility
# --------------------------------------------------------------------------- #
def _check_boolean(criterion: EligibilityCriterion, submission: VendorSubmission) -> GapItem:
    base = dict(
        requirement=criterion.criterion,
        kind=RequirementKind.BOOLEAN,
        is_mandatory=criterion.is_mandatory,
        notification_provenance=criterion.provenance,
    )
    lowered = criterion.criterion.lower()

    if "blacklist" in lowered or "debar" in lowered:
        if submission.is_blacklisted:
            return GapItem(
                status=CheckStatus.MISSING,
                severity=Severity.DISQUALIFYING,
                required_value="Not blacklisted or debarred",
                found_value="Flagged as blacklisted",
                explanation=(
                    "You are flagged as blacklisted or debarred, which this tender "
                    "treats as a disqualifying condition."
                ),
                **base,
            )
        # Section 5.8: the flag is manually set/seeded, so "not flagged" is not
        # proof of clean standing -- say so rather than claiming a pass.
        return GapItem(
            status=CheckStatus.MANUAL_CHECK,
            severity=Severity.REVIEW,
            required_value="Not blacklisted or debarred",
            found_value="No blacklist flag recorded",
            explanation=(
                "No blacklisting flag is recorded against you, but this system does "
                "not check official debarment lists. Enclose the required "
                "self-declaration and verify your standing independently."
            ),
            **base,
        )

    return GapItem(
        status=CheckStatus.MANUAL_CHECK,
        severity=Severity.REVIEW,
        required_value=criterion.threshold_raw or "Yes",
        explanation="This is a yes/no condition that needs a human check against your bid.",
        **base,
    )


# --------------------------------------------------------------------------- #
# Format rules -- always manual (Section 4.3)
# --------------------------------------------------------------------------- #
def _check_format_rules(notification: TenderNotification) -> list[GapItem]:
    return [
        GapItem(
            requirement=rule.rule,
            kind=RequirementKind.FORMAT_RULE,
            status=CheckStatus.MANUAL_CHECK,
            severity=Severity.REVIEW,
            explanation=(
                "Formatting and procedural rules are usually visual (signatures, "
                "seals, page numbering, envelope structure) and cannot be verified "
                "from text alone. Check this yourself before submitting."
            ),
            notification_provenance=rule.provenance,
        )
        for rule in notification.submission_format_rules
    ]


# --------------------------------------------------------------------------- #
# Section 4.4 -- score preview only when weightage is published
# --------------------------------------------------------------------------- #
def _build_score_preview(
    notification: TenderNotification, items: list[GapItem]
) -> ScorePreview:
    if not notification.evaluation_criteria:
        return ScorePreview(
            available=False,
            unavailable_reason=(
                "This tender notification does not publish evaluation criteria, so "
                "no score can be estimated. Compliance status is shown instead."
            ),
        )
    if not notification.publishes_weightage:
        return ScorePreview(
            available=False,
            unavailable_reason=(
                "This tender names its evaluation factors but does not publish "
                "their weightage, so no score can be estimated without inventing "
                "weights. Compliance status is shown instead."
            ),
        )

    by_requirement = {i.requirement.lower(): i for i in items}
    preview_items = []
    for criterion in notification.evaluation_criteria:
        if criterion.weightage_if_stated is None:
            continue
        related = by_requirement.get(criterion.factor.lower())
        preview_items.append(
            ScorePreviewItem(
                factor=criterion.factor,
                weightage=criterion.weightage_if_stated,
                status=related.status if related else CheckStatus.MANUAL_CHECK,
                provenance=criterion.provenance,
            )
        )
    return ScorePreview(
        available=True,
        items=preview_items,
        total_weightage=sum(i.weightage for i in preview_items),
    )


# --------------------------------------------------------------------------- #
# Section 4.6 -- plain-language action list
# --------------------------------------------------------------------------- #
_SEVERITY_ORDER = {
    Severity.DISQUALIFYING: 0,
    Severity.ACTION_NEEDED: 1,
    Severity.REVIEW: 2,
    Severity.INFO: 3,
}


def _build_action_list(items: list[GapItem]) -> list[ActionItem]:
    actions: list[ActionItem] = []
    for item in items:
        if item.status is CheckStatus.MATCH:
            continue

        if item.kind is RequirementKind.DOCUMENT and item.status is CheckStatus.MISSING:
            action = f"Upload {item.required_value}"
        elif item.status is CheckStatus.MISSING:
            action = item.explanation
        elif item.status is CheckStatus.NOT_ASSESSABLE:
            action = f"Clarify in your bid: {item.requirement}"
        elif item.status is CheckStatus.PARTIAL:
            action = f"Confirm that “{item.found_value}” satisfies: {item.requirement}"
        else:
            action = f"Check manually: {item.requirement}"

        actions.append(
            ActionItem(
                action=action,
                severity=item.severity,
                requirement=item.requirement,
                clause_ref=(
                    item.notification_provenance.clause_ref
                    if item.notification_provenance
                    else None
                ),
            )
        )

    actions.sort(key=lambda a: _SEVERITY_ORDER[a.severity])
    return actions


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def build_gap_report(
    notification: TenderNotification,
    submission: VendorSubmission,
    *,
    use_embeddings: bool = True,
    today: date | None = None,
) -> GapReport:
    """Cross-check a bid against a notification (Section 4.3)."""
    items: list[GapItem] = []

    items += _check_documents(notification, submission, use_embeddings=use_embeddings)

    for criterion in notification.eligibility_criteria:
        if criterion.type is CriterionType.NUMERIC:
            items.append(_check_numeric(criterion, submission))
        elif criterion.type is CriterionType.BOOLEAN:
            items.append(_check_boolean(criterion, submission))
        else:  # DOCUMENT-type eligibility criterion
            result = match_document(
                criterion.criterion,
                [d.doc_name for d in submission.documents_submitted if d.present]
                + [c.name for c in submission.certifications if c.doc_present],
                use_embeddings=use_embeddings,
            )
            items.append(
                _document_item(criterion.criterion, criterion.provenance, result, set())
            )

    items += _check_format_rules(notification)

    return GapReport(
        tender_id=notification.tender_id,
        vendor_id=submission.vendor_id,
        vendor_name=submission.vendor_name,
        items=items,
        score_preview=_build_score_preview(notification, items),
        action_list=_build_action_list(items),
    )
