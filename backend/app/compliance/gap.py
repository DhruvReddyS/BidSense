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
    prewarm,
)
from app.compliance.requirements import Applicability, Requirement, deduplicate
from app.compliance.models import (
    ActionGroup,
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
from app.schemas.notification import (
    EligibilityCriterion,
    MandatoryDocument,
    TenderNotification,
)
from app.schemas.submission import VendorSubmission

# Words in a criterion that indicate it is about turnover rather than, say,
# project value -- used to pick which extracted number to compare against.
_TURNOVER_HINTS = ("turnover", "revenue", "annual receipt", "gross receipt")

# Units under which a bare number genuinely means "how many projects".
#
# Everything else is a physical quantity the bid does not express as a count,
# and comparing it against the number of listed projects produces a confident
# false elimination. HGCL asks for "similar works of 13 MW cumulative capacity";
# read as thirteen projects, a bidder citing two 13 MW plants is eliminated for
# having "only 2". Same failure class as reading "5 years" as five rupees.
_COUNT_UNITS = {
    "", "project", "projects", "work", "works", "no", "no.", "nos", "nos.",
    "number", "numbers", "order", "orders", "contract", "contracts",
    "assignment", "assignments", "job", "jobs", "count",
}
_YEAR_UNITS = {"", "year", "years", "yr", "yrs"}


def _unit_is(unit: str | None, allowed: set[str]) -> bool:
    """Whether a criterion's unit permits this comparison at all."""
    return (unit or "").strip().lower().rstrip(".") in {
        u.rstrip(".") for u in allowed
    }
_EXPERIENCE_HINTS = ("experience", "years in business", "operating", "established")
_PROJECT_HINTS = ("project", "work", "contract", "assignment", "order")
_LIQUIDITY_HINTS = (
    "liquid asset", "credit facilit", "working capital", "solvency",
    "line of credit", "cash flow", "bid capacity",
)
_NET_WORTH_HINTS = ("net worth", "networth")


def _mentions(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(h in lowered for h in hints)


# --------------------------------------------------------------------------- #
# Document presence (Section 4.3 "hard document checklist")
# --------------------------------------------------------------------------- #
def _collect_requirements(notification: TenderNotification) -> list[Requirement]:
    """Every document the bidder must produce, stated once.

    Document-type eligibility criteria are folded in here rather than checked
    separately: a tender that lists "Copy of GST registration" both as an
    eligibility condition and in the document checklist is stating one
    requirement twice, and showing it twice makes a clean bid look untidy.
    """
    documents = list(notification.mandatory_documents)
    for criterion in notification.eligibility_criteria:
        if criterion.type is CriterionType.DOCUMENT:
            documents.append(
                MandatoryDocument(
                    doc_name=criterion.criterion,
                    provenance=criterion.provenance,
                )
            )
    return deduplicate(documents)


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

    requirements = _collect_requirements(notification)

    # Two passes, so the embedding model is called ONCE for the whole report.
    #
    # The cheap tiers (exact, alias, vocabulary) settle most requirements
    # without a model at all -- on the GHMC tender, 44 of 49. Running them first
    # for everything identifies precisely which names still need embedding, and
    # those are then embedded together.
    #
    # Trickling them in was measured at 37 separate calls for one report, 36 of
    # them a batch of one. A sentence-transformer amortises tokenisation across
    # a batch and runs it as a single forward pass, so batch-of-one is close to
    # the worst way to ask for an embedding. Pre-embedding everything up front
    # would be one call too, but would pay for the 44 names that never needed it.
    settled: dict[int, MatchResult] = {}
    pending: list[int] = []
    for index, requirement in enumerate(requirements):
        result = match_document(
            requirement.primary.doc_name,
            haystack,
            extra_aliases=requirement.aliases,
            use_embeddings=False,
        )
        if result.matched:
            settled[index] = result
        else:
            pending.append(index)

    if pending and use_embeddings:
        prewarm([requirements[i].primary.doc_name for i in pending] + haystack)

    items: list[GapItem] = []
    for index, requirement in enumerate(requirements):
        result = settled.get(index)
        if result is None:
            result = match_document(
                requirement.primary.doc_name,
                haystack,
                extra_aliases=requirement.aliases,
                use_embeddings=use_embeddings,
            )
        items.append(_document_item(requirement, result, declared_absent))
    return items


def _document_item(
    requirement: Requirement,
    result: MatchResult,
    declared_absent: set[str],
) -> GapItem:
    doc_name = requirement.label
    provenance = requirement.primary.provenance
    base = dict(
        requirement=f"Submit {doc_name}",
        kind=RequirementKind.DOCUMENT,
        required_value=doc_name,
        notification_provenance=provenance,
        # Carried on EVERY branch, not only the not-found one. A conditional
        # document that near-matches leaves through the PARTIAL branch above,
        # and setting this only on the not-found path dropped the "only if you
        # are a joint venture" qualifier from exactly those rows -- which on the
        # GHMC tender is most of them.
        conditional_on=(
            None
            if requirement.applicability is Applicability.ALWAYS
            else _CONDITION_LABELS[requirement.applicability]
        ),
    )

    if result.matched and not result.is_uncertain:
        return GapItem(
            status=CheckStatus.MATCH,
            severity=Severity.INFO,
            found_value=result.matched_name,
            explanation=(
                f"Found in your submission as \u201c{result.matched_name}\u201d."
                if result.method != "exact"
                else "Found in your submission."
            ),
            match_method=result.method,
            match_score=result.score,
            **base,
        )

    if result.matched and result.is_uncertain:
        # A borderline embedding match is reported as partial, not as settled.
        # Silently accepting it would tell a vendor they are covered when the
        # only evidence is two names that read alike.
        return GapItem(
            status=CheckStatus.PARTIAL,
            severity=Severity.REVIEW,
            found_value=result.matched_name,
            explanation=(
                f"\u201c{result.matched_name}\u201d looks like it may satisfy this, but "
                f"the names differ enough (similarity {result.score:.2f}) that you "
                "should confirm it is the right document."
            ),
            match_method=result.method,
            match_score=result.score,
            **base,
        )

    explicitly_absent = doc_name.lower() in declared_absent or any(
        normalise(doc_name) == normalise(a) for a in declared_absent
    )

    # Checked BEFORE the review band. When the bid's own checklist marks a
    # document NOT ENCLOSED, that is the bidder telling us it is absent, and it
    # outranks any resemblance to some other document they did enclose. Without
    # this ordering a vendor who declared a missing manufacturer's authorisation
    # was softened to "did you mean 'Document required from authorized
    # dealers'?" -- turning a definite failure into a maybe, and losing the
    # elimination.
    if result.needs_review and not explicitly_absent:
        # A near miss below the acceptance floor. Nothing is declared present --
        # the vendor is asked, because telling them to obtain a document that is
        # already in their bid under a different name is also a wrong answer.
        return GapItem(
            status=CheckStatus.PARTIAL,
            severity=Severity.REVIEW,
            found_value=result.review_candidate,
            explanation=(
                f"Your bid encloses “{result.review_candidate}”, which may be "
                f"this document under a different name, but the names differ too "
                f"much (similarity {result.score:.2f}) for us to treat it as "
                "confirmed. Check it, and rename it to match the tender if it is."
            ),
            match_score=result.score,
            **base,
        )

    # Not found. Whether that disqualifies depends on whether the requirement
    # binds THIS bidder. A JV agreement is not a gap for a sole proprietor, and
    # reporting it as disqualifying buries the real failures in noise.
    if requirement.applicability is not Applicability.ALWAYS:
        return GapItem(
            status=CheckStatus.MANUAL_CHECK,
            severity=Severity.REVIEW,
            found_value=None,
            explanation=_conditional_explanation(requirement.applicability, doc_name),
            match_score=result.score,
            **base,
        )

    return GapItem(
        status=CheckStatus.MISSING,
        severity=Severity.DISQUALIFYING,
        found_value=None,
        explanation=(
            f"Your submission lists {doc_name} but marks it as not enclosed."
            if explicitly_absent
            else f"No document matching {doc_name} was found in your submission."
        ),
        match_score=result.score,
        **base,
    )


_CONDITIONAL_TEXT = {
    Applicability.JOINT_VENTURE: (
        "This applies only if you are bidding as a joint venture or consortium. "
        "If you are bidding on your own, it does not apply to you — confirm and "
        "ignore."
    ),
    Applicability.CONCESSION: (
        "This applies only if you are claiming a concession or preference (MSME, "
        "startup, and similar). If you are not claiming one, it does not apply."
    ),
    Applicability.CONDITIONAL: (
        "The tender marks this as conditional. Check whether it applies to your "
        "bid; it is not automatically required."
    ),
}


# Short form of the same condition, for the action list. The explanations above
# are a paragraph each, which is right in a report row and wrong in a to-do line.
_CONDITION_LABELS = {
    Applicability.JOINT_VENTURE: "you are bidding as a joint venture or consortium",
    Applicability.CONCESSION: "you are claiming an MSME, startup or similar concession",
    Applicability.CONDITIONAL: "this clause applies to your bid",
}


def _conditional_explanation(applicability: Applicability, doc_name: str) -> str:
    return f"{doc_name} was not found. " + _CONDITIONAL_TEXT[applicability]


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
        if _mentions(criterion.criterion, _LIQUIDITY_HINTS):
            return _compare_declared_amount(
                submission.liquid_assets, threshold, severity_if_failed, base,
                label="liquid assets and credit facilities",
                advice="State your available liquid assets and credit facilities "
                       "as a figure, supported by a bankers' certificate.",
            )
        if _mentions(criterion.criterion, _NET_WORTH_HINTS):
            return _compare_declared_amount(
                submission.net_worth, threshold, severity_if_failed, base,
                label="net worth",
                advice="State your net worth as a figure, certified by your "
                       "Chartered Accountant.",
            )
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
        stated = f"{criterion.threshold_number:g} {criterion.unit or ''}".strip()

        if _mentions(criterion.criterion, _EXPERIENCE_HINTS) and _unit_is(
            criterion.unit, _YEAR_UNITS
        ):
            return _compare_experience(criterion, submission, severity_if_failed, base)

        if _mentions(criterion.criterion, _PROJECT_HINTS) and _unit_is(
            criterion.unit, _COUNT_UNITS
        ):
            return _compare_project_count(criterion, submission, severity_if_failed, base)

        # The requirement is a physical quantity -- megawatts of capacity,
        # kilometres of cable, tonnes of steel. Nothing in the extracted schema
        # holds a comparable figure, and guessing produces a confident false
        # elimination rather than an honest "check this yourself".
        if criterion.unit and not _unit_is(criterion.unit, _COUNT_UNITS | _YEAR_UNITS):
            return GapItem(
                status=CheckStatus.MANUAL_CHECK,
                severity=Severity.REVIEW,
                required_value=stated,
                explanation=(
                    f"This asks for {stated}. That is a quantity we cannot read "
                    "off your bid automatically, so check it against your own "
                    "records — it is not a failure."
                ),
                **base,
            )

        return GapItem(
            status=CheckStatus.MANUAL_CHECK,
            severity=Severity.REVIEW,
            required_value=stated,
            explanation=(
                "Numeric requirement with no matching figure in your bid to "
                "compare. Check it yourself."
            ),
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


def _compare_declared_amount(
    declared, threshold: Decimal, fail_severity, base, *, label: str, advice: str
) -> GapItem:
    """Compare a single declared figure against a money floor.

    Used for the financial-capacity criteria large tenders set alongside
    turnover. An absent figure is NOT_ASSESSABLE rather than a failure: the
    bidder may well hold the capacity and simply not have stated it in a form
    we could read, and eliminating on that would be a guess.
    """
    if declared is None or not declared.is_resolved:
        return GapItem(
            status=CheckStatus.NOT_ASSESSABLE,
            severity=Severity.REVIEW,
            required_value=format_money(threshold),
            found_value=declared.raw_text if declared else None,
            explanation=(
                f"Your bid does not state {label} in a form we could read. {advice}"
            ),
            **base,
        )

    passed = declared.amount_inr >= threshold
    return GapItem(
        status=CheckStatus.MATCH if passed else CheckStatus.MISSING,
        severity=Severity.INFO if passed else fail_severity,
        required_value=format_money(threshold),
        found_value=format_money(declared.amount_inr),
        explanation=(
            f"Your declared {label} of {format_money(declared.amount_inr)} meets "
            f"the requirement of {format_money(threshold)}."
            if passed
            else (
                f"Your declared {label} is {format_money(declared.amount_inr)}, "
                f"below the required {format_money(threshold)}. You do not "
                "currently qualify on this criterion."
            )
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

    if any(word in lowered for word in ("blacklist", "debar", "liquidation", "banned")):
        if submission.is_blacklisted:
            # Quote the bidder's own words when they disclosed it. An
            # elimination that says "you declared this yourself, here it is" is
            # far harder to dispute than one asserting an internal flag.
            disclosed = submission.debarment_disclosure
            return GapItem(
                status=CheckStatus.MISSING,
                severity=Severity.DISQUALIFYING,
                required_value="Not blacklisted or debarred",
                found_value=(
                    "Declared in your own bid" if disclosed else "Flagged as blacklisted"
                ),
                explanation=(
                    "Your bid discloses that you are debarred or under "
                    f"insolvency proceedings: \u201c{disclosed.strip()[:220]}\u201d "
                    "This tender treats that as a disqualifying condition."
                    if disclosed
                    else (
                        "You are flagged as blacklisted or debarred, which this "
                        "tender treats as a disqualifying condition."
                    )
                ),
                submission_provenance=(
                    Provenance(source_snippet=disclosed) if disclosed else None
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

# Within one severity band, order by what the vendor can do about it. Every
# unmet mandatory requirement is "disqualifying", so severity alone leaves the
# ordering to extraction order -- which on a real tender buried the one
# unfixable failure at position 39 of 39.
_GROUP_ORDER = {
    ActionGroup.HARD_FAIL: 0,
    ActionGroup.UPLOAD: 1,
    ActionGroup.CLARIFY: 2,
    ActionGroup.VERIFY: 3,
}


def _classify_action(item: GapItem) -> ActionGroup:
    if item.status is CheckStatus.NOT_ASSESSABLE:
        return ActionGroup.CLARIFY
    if item.status in (CheckStatus.MANUAL_CHECK, CheckStatus.PARTIAL):
        return ActionGroup.VERIFY
    # MISSING. A document gap is fixable by attaching the document; a failed
    # threshold or condition is not.
    if item.kind is RequirementKind.DOCUMENT:
        return ActionGroup.UPLOAD
    return ActionGroup.HARD_FAIL


def _build_action_list(items: list[GapItem]) -> list[ActionItem]:
    actions: list[ActionItem] = []
    for item in items:
        if item.status is CheckStatus.MATCH:
            continue

        group = _classify_action(item)
        if group is ActionGroup.UPLOAD:
            action = f"Upload {item.required_value or item.requirement}"
        elif group is ActionGroup.HARD_FAIL:
            # The explanation already names both figures, which is the whole
            # point -- the vendor needs to see the gap, not just be told to act.
            action = item.explanation
        elif group is ActionGroup.CLARIFY:
            action = f"State clearly in your bid: {item.requirement}"
        elif item.conditional_on and item.found_value:
            action = (
                f"Only if {item.conditional_on}: confirm "
                f"\u201c{item.found_value}\u201d satisfies {_verb(item.requirement)}. "
                "Otherwise this does not apply to you."
            )
        elif item.conditional_on:
            # Named as conditional in the to-do itself. "Check yourself: Submit
            # Joint Venture Agreement" reads as an instruction to a sole
            # proprietor who has no such agreement and needs none.
            action = (
                f"Only if {item.conditional_on}: {_verb(item.requirement)}. "
                "Otherwise this does not apply to you."
            )
        else:
            action = (
                f"Confirm \u201c{item.found_value}\u201d satisfies: {item.requirement}"
                if item.status is CheckStatus.PARTIAL and item.found_value
                else f"Check yourself: {item.requirement}"
            )

        actions.append(
            ActionItem(
                action=action,
                severity=item.severity,
                group=group,
                requirement=item.requirement,
                applies_only_if=item.conditional_on,
                clause_ref=(
                    item.notification_provenance.clause_ref
                    if item.notification_provenance
                    else None
                ),
            )
        )

    # Conditional items sink to the bottom of their band. They are the least
    # likely to need doing -- most bidders are not a joint venture -- and on a
    # real tender there are enough of them to bury the ones that are.
    actions.sort(
        key=lambda a: (
            _SEVERITY_ORDER[a.severity],
            _GROUP_ORDER[a.group],
            1 if a.applies_only_if else 0,
        )
    )
    return actions


def _verb(requirement: str) -> str:
    """Turn a requirement line into something that reads as an instruction.

    Requirements arrive as "Submit X" from the document check and as a bare
    clause from everywhere else, so a blanket prefix produces either "Only if...:
    Submit Submit X" or a sentence with no verb at all.
    """
    text = requirement.strip()
    return text[0].lower() + text[1:] if text[:1].isupper() and " " in text else text


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
        # DOCUMENT-type criteria are folded into _collect_requirements above, so
        # a tender stating one requirement in two places yields one row.

    items += _check_format_rules(notification)

    return GapReport(
        tender_id=notification.tender_id,
        vendor_id=submission.vendor_id,
        vendor_name=submission.vendor_name,
        items=items,
        score_preview=_build_score_preview(notification, items),
        action_list=_build_action_list(items),
    )
