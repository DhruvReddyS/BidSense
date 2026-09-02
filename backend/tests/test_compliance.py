"""Gap report engine tests (Section 4.3, 4.4, 4.6).

Pure logic -- no LLM, no services -- because Section 2.1.3's whole argument is
that this layer must be deterministic and auditable.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.compliance.gap import build_gap_report
from app.compliance.matching import canonical_form, match_document, normalise
from app.compliance.models import CheckStatus, RequirementKind, Severity
from app.schemas.common import CriterionType, MoneyAmount, Provenance, YearlyTurnover
from app.schemas.notification import (
    EligibilityCriterion,
    EvaluationCriterion,
    MandatoryDocument,
    SubmissionFormatRule,
    TenderNotification,
)
from app.schemas.submission import (
    Certification,
    PastProject,
    SubmittedDocument,
    VendorSubmission,
)


def notification(**overrides) -> TenderNotification:
    defaults = dict(
        tender_id="T-1",
        title="Network equipment supply",
        mandatory_documents=[
            MandatoryDocument(
                doc_name="GST Registration Certificate",
                provenance=Provenance(clause_ref="5.1", source_page=3),
            ),
            MandatoryDocument(doc_name="EMD Demand Draft", provenance=Provenance(clause_ref="5.1")),
        ],
        eligibility_criteria=[
            EligibilityCriterion(
                criterion="Average annual turnover",
                type=CriterionType.NUMERIC,
                threshold_raw="Rs. 5 Cr",
                threshold_amount=MoneyAmount(raw_text="Rs. 5 Cr"),
                unit="INR",
                provenance=Provenance(clause_ref="4.2", source_page=2),
            ),
            EligibilityCriterion(
                criterion="Years of experience",
                type=CriterionType.NUMERIC,
                threshold_raw="5 years",
                threshold_number=5,
                unit="years",
                provenance=Provenance(clause_ref="4.3"),
            ),
        ],
    )
    defaults.update(overrides)
    return TenderNotification(**defaults)


def submission(**overrides) -> VendorSubmission:
    defaults = dict(
        vendor_id="V-01",
        vendor_name="Delta Systems",
        turnover=[YearlyTurnover(year=2023, amount=MoneyAmount(raw_text="Rs. 6 Cr"))],
        years_in_business=8,
        documents_submitted=[
            SubmittedDocument(doc_name="GST Registration Certificate", present=True),
            SubmittedDocument(doc_name="EMD Demand Draft", present=True),
        ],
    )
    defaults.update(overrides)
    return VendorSubmission(**defaults)


NO_EMBED = dict(use_embeddings=False)


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #
def test_normalisation_strips_filler_and_punctuation():
    assert normalise("Self-attested copy of the GST Certificate") == "gst certificate"
    assert normalise("PAN Card") == "pan card"


def test_alias_table_resolves_real_indian_variants():
    assert canonical_form("Goods & Services Tax Certificate") == "gst registration certificate"
    assert canonical_form("GSTIN Certificate") == "gst registration certificate"
    assert canonical_form("Bid Security") == "emd demand draft"
    assert canonical_form("Certificate of Incorporation") == "incorporation certificate"


def test_alias_match_beats_exact_string_failure():
    """Section 6's warning: exact matching produces false negatives, which tell
    a compliant vendor they are missing a document they actually submitted."""
    result = match_document(
        "GST Registration Certificate",
        ["Goods & Services Tax Certificate"],
        **NO_EMBED,
    )
    assert result.matched
    assert result.method == "alias"


def test_lexically_close_but_different_documents_do_not_match():
    """PAN and TAN are one letter apart and semantically adjacent. Treating them
    as the same document would mark a real gap as satisfied."""
    result = match_document("PAN Card", ["TAN Certificate"], **NO_EMBED)
    assert not result.matched


def test_tender_specific_aliases_are_honoured():
    result = match_document(
        "Form 12-B",
        ["Annexure IV Declaration"],
        extra_aliases=["Annexure IV Declaration"],
        **NO_EMBED,
    )
    assert result.matched and result.method == "alias"


def test_no_submitted_documents_is_a_clean_no_match():
    assert not match_document("GST Registration Certificate", [], **NO_EMBED).matched


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #
def test_present_documents_match():
    report = build_gap_report(notification(), submission(), **NO_EMBED)
    doc_items = [i for i in report.items if i.kind is RequirementKind.DOCUMENT]
    assert len(doc_items) == 2
    assert all(i.status is CheckStatus.MATCH for i in doc_items)


def test_missing_document_is_disqualifying_and_cites_its_clause():
    report = build_gap_report(
        notification(),
        submission(documents_submitted=[SubmittedDocument(doc_name="EMD Demand Draft", present=True)]),
        **NO_EMBED,
    )
    gst = next(i for i in report.items if "GST" in i.requirement)
    assert gst.status is CheckStatus.MISSING
    assert gst.severity is Severity.DISQUALIFYING
    assert gst.notification_provenance.clause_ref == "5.1"
    assert report.verdict == "not_compliant"


def test_document_declared_but_not_enclosed_says_so():
    report = build_gap_report(
        notification(),
        submission(
            documents_submitted=[
                SubmittedDocument(doc_name="GST Registration Certificate", present=False),
                SubmittedDocument(doc_name="EMD Demand Draft", present=True),
            ]
        ),
        **NO_EMBED,
    )
    gst = next(i for i in report.items if "GST" in i.requirement)
    assert gst.status is CheckStatus.MISSING
    assert "marks it as not enclosed" in gst.explanation


def test_certifications_count_as_submitted_documents():
    report = build_gap_report(
        notification(
            mandatory_documents=[MandatoryDocument(doc_name="ISO 9001 Certificate")]
        ),
        submission(
            documents_submitted=[],
            certifications=[Certification(name="ISO 9001:2015 Certificate", doc_present=True)],
        ),
        **NO_EMBED,
    )
    iso = next(i for i in report.items if "ISO" in i.requirement)
    assert iso.status is CheckStatus.MATCH


# --------------------------------------------------------------------------- #
# Numeric eligibility
# --------------------------------------------------------------------------- #
def test_turnover_above_threshold_passes():
    report = build_gap_report(notification(), submission(), **NO_EMBED)
    item = next(i for i in report.items if "turnover" in i.requirement.lower())
    assert item.status is CheckStatus.MATCH
    assert "₹6 Cr" in item.found_value


def test_turnover_below_threshold_is_disqualifying_with_both_figures():
    """Section 4.6's example message: the vendor must see their number and the
    requirement side by side."""
    report = build_gap_report(
        notification(),
        submission(turnover=[YearlyTurnover(year=2023, amount=MoneyAmount(raw_text="Rs. 3.2 Cr"))]),
        **NO_EMBED,
    )
    item = next(i for i in report.items if "turnover" in i.requirement.lower())
    assert item.status is CheckStatus.MISSING
    assert item.severity is Severity.DISQUALIFYING
    assert "₹3.2 Cr" in item.explanation and "₹5 Cr" in item.explanation
    assert "do not currently qualify" in item.explanation


def test_unparseable_turnover_is_not_assessable_never_a_failure():
    """The critical distinction: "we could not read your number" must never be
    rendered to a vendor as "you failed"."""
    report = build_gap_report(
        notification(),
        submission(
            turnover=[YearlyTurnover(year=2023, amount=MoneyAmount(raw_text="as per Annexure IV"))]
        ),
        **NO_EMBED,
    )
    item = next(i for i in report.items if "turnover" in i.requirement.lower())
    assert item.status is CheckStatus.NOT_ASSESSABLE
    assert item.severity is not Severity.DISQUALIFYING
    assert report.verdict == "needs_review"


def test_best_declared_year_is_used_not_the_latest():
    report = build_gap_report(
        notification(),
        submission(
            turnover=[
                YearlyTurnover(year=2022, amount=MoneyAmount(raw_text="Rs. 7 Cr")),
                YearlyTurnover(year=2023, amount=MoneyAmount(raw_text="Rs. 2 Cr")),
            ]
        ),
        **NO_EMBED,
    )
    item = next(i for i in report.items if "turnover" in i.requirement.lower())
    assert item.status is CheckStatus.MATCH
    assert "2022" in item.found_value


def test_experience_below_threshold_fails():
    report = build_gap_report(notification(), submission(years_in_business=3), **NO_EMBED)
    item = next(i for i in report.items if "experience" in i.requirement.lower())
    assert item.status is CheckStatus.MISSING
    assert "3 years" in item.explanation and "5" in item.explanation


def test_missing_experience_figure_is_not_assessable():
    report = build_gap_report(notification(), submission(years_in_business=None), **NO_EMBED)
    item = next(i for i in report.items if "experience" in i.requirement.lower())
    assert item.status is CheckStatus.NOT_ASSESSABLE


def test_unresolvable_threshold_is_not_assessable():
    report = build_gap_report(
        notification(
            eligibility_criteria=[
                EligibilityCriterion(
                    criterion="Annual turnover",
                    type=CriterionType.NUMERIC,
                    threshold_raw="as specified in Annexure II",
                )
            ]
        ),
        submission(),
        **NO_EMBED,
    )
    item = next(i for i in report.items if "turnover" in i.requirement.lower())
    assert item.status is CheckStatus.NOT_ASSESSABLE
    assert "Annexure II" in item.explanation


def test_non_mandatory_failure_is_not_disqualifying():
    report = build_gap_report(
        notification(
            eligibility_criteria=[
                EligibilityCriterion(
                    criterion="Preferred annual turnover",
                    type=CriterionType.NUMERIC,
                    threshold_amount=MoneyAmount(raw_text="Rs. 50 Cr"),
                    threshold_raw="Rs. 50 Cr",
                    unit="INR",
                    is_mandatory=False,
                )
            ]
        ),
        submission(),
        **NO_EMBED,
    )
    item = report.items[-1] if report.items else None
    turnover = next(i for i in report.items if "turnover" in i.requirement.lower())
    assert turnover.status is CheckStatus.MISSING
    assert turnover.severity is not Severity.DISQUALIFYING
    assert report.verdict != "not_compliant"


# --------------------------------------------------------------------------- #
# Blacklist (Section 5.8)
# --------------------------------------------------------------------------- #
def test_blacklisted_vendor_is_disqualified():
    report = build_gap_report(
        notification(
            eligibility_criteria=[
                EligibilityCriterion(
                    criterion="Not blacklisted or debarred", type=CriterionType.BOOLEAN
                )
            ]
        ),
        submission(is_blacklisted=True),
        **NO_EMBED,
    )
    item = next(i for i in report.items if "blacklist" in i.requirement.lower())
    assert item.status is CheckStatus.MISSING
    assert item.severity is Severity.DISQUALIFYING


def test_absence_of_a_blacklist_flag_is_not_claimed_as_a_pass():
    """Section 5.8 -- the flag is manually seeded, so "not flagged" is not proof
    of clean standing and must not be presented as verified."""
    report = build_gap_report(
        notification(
            eligibility_criteria=[
                EligibilityCriterion(
                    criterion="Not blacklisted or debarred", type=CriterionType.BOOLEAN
                )
            ]
        ),
        submission(is_blacklisted=False),
        **NO_EMBED,
    )
    item = next(i for i in report.items if "blacklist" in i.requirement.lower())
    assert item.status is CheckStatus.MANUAL_CHECK
    assert "does not check official debarment lists" in item.explanation


# --------------------------------------------------------------------------- #
# Format rules -- always manual (Section 4.3)
# --------------------------------------------------------------------------- #
def test_format_rules_are_always_manual_check():
    report = build_gap_report(
        notification(
            submission_format_rules=[
                SubmissionFormatRule(rule="Every page signed and sealed"),
                SubmissionFormatRule(rule="Technical proposal max 40 pages"),
            ]
        ),
        submission(),
        **NO_EMBED,
    )
    rules = [i for i in report.items if i.kind is RequirementKind.FORMAT_RULE]
    assert len(rules) == 2
    assert all(i.status is CheckStatus.MANUAL_CHECK for i in rules)
    assert all(i.severity is Severity.REVIEW for i in rules)


# --------------------------------------------------------------------------- #
# Section 4.4 -- score preview
# --------------------------------------------------------------------------- #
def test_no_score_when_no_evaluation_criteria_published():
    report = build_gap_report(notification(), submission(), **NO_EMBED)
    assert report.score_preview.available is False
    assert "does not publish evaluation criteria" in report.score_preview.unavailable_reason
    assert report.score_preview.items == []


def test_no_score_when_factors_named_but_weights_unpublished():
    """The exact case Section 4.4 calls out: do NOT invent a score."""
    report = build_gap_report(
        notification(
            evaluation_criteria=[
                EvaluationCriterion(factor="Technical capability"),
                EvaluationCriterion(factor="Financial strength"),
            ]
        ),
        submission(),
        **NO_EMBED,
    )
    assert report.score_preview.available is False
    assert "does not publish their weightage" in report.score_preview.unavailable_reason
    assert report.score_preview.total_weightage is None


def test_score_preview_appears_only_with_published_weights():
    report = build_gap_report(
        notification(
            evaluation_criteria=[
                EvaluationCriterion(factor="Technical", weightage_if_stated=70),
                EvaluationCriterion(factor="Financial", weightage_if_stated=30),
            ]
        ),
        submission(),
        **NO_EMBED,
    )
    assert report.score_preview.available is True
    assert report.score_preview.total_weightage == 100
    assert {i.factor for i in report.score_preview.items} == {"Technical", "Financial"}


# --------------------------------------------------------------------------- #
# Section 4.6 -- action list
# --------------------------------------------------------------------------- #
def test_action_list_is_prioritised_and_plain_language():
    report = build_gap_report(
        notification(submission_format_rules=[SubmissionFormatRule(rule="Sign every page")]),
        submission(
            documents_submitted=[],
            turnover=[YearlyTurnover(year=2023, amount=MoneyAmount(raw_text="Rs. 3.2 Cr"))],
        ),
        **NO_EMBED,
    )
    assert report.action_list
    severities = [a.severity for a in report.action_list]
    assert severities == sorted(severities, key=lambda s: {"disqualifying":0,"action_needed":1,"review":2,"info":3}[s.value])
    assert report.action_list[0].severity is Severity.DISQUALIFYING
    assert any(a.action.startswith("Upload ") for a in report.action_list)


def test_satisfied_requirements_produce_no_action():
    report = build_gap_report(notification(), submission(), **NO_EMBED)
    assert all(
        a.requirement not in {i.requirement for i in report.items if i.status is CheckStatus.MATCH}
        for a in report.action_list
    )


# --------------------------------------------------------------------------- #
# Verdict
# --------------------------------------------------------------------------- #
def test_fully_clean_submission_is_compliant():
    report = build_gap_report(notification(), submission(), **NO_EMBED)
    assert report.verdict == "compliant"
    assert report.is_compliant
    assert report.counts["match"] == 4


def test_manual_check_alone_downgrades_to_needs_review():
    """A clean run and an undecidable run are different answers, and the vendor
    is entitled to know which one they got."""
    report = build_gap_report(
        notification(submission_format_rules=[SubmissionFormatRule(rule="Sign every page")]),
        submission(),
        **NO_EMBED,
    )
    assert report.is_compliant          # nothing failed
    assert report.verdict == "needs_review"   # but not everything was checkable


# --------------------------------------------------------------------------- #
# Self-contradictory bids (regression)
# --------------------------------------------------------------------------- #
def test_explicit_not_enclosed_overrides_a_certification_claim():
    """A bid can contradict itself: the checklist marks a certificate as not
    enclosed while the certifications section still lists it. The explicit
    "not enclosed" must win -- the opposite error tells a vendor they are
    covered and they submit without the document."""
    report = build_gap_report(
        notification(mandatory_documents=[MandatoryDocument(doc_name="ISO 9001 Certificate")]),
        submission(
            documents_submitted=[
                SubmittedDocument(doc_name="ISO 9001:2015 Certificate", present=False)
            ],
            certifications=[Certification(name="ISO 9001:2015", doc_present=True)],
        ),
        **NO_EMBED,
    )
    iso = next(i for i in report.items if "ISO" in i.requirement)
    assert iso.status is CheckStatus.MISSING
    assert iso.severity is Severity.DISQUALIFYING


def test_alias_variants_of_a_declared_absent_document_are_also_suppressed():
    """The contradiction must be caught even when the two mentions use
    different names for the same document."""
    report = build_gap_report(
        notification(
            mandatory_documents=[MandatoryDocument(doc_name="GST Registration Certificate")]
        ),
        submission(
            documents_submitted=[
                SubmittedDocument(doc_name="GST Registration Certificate", present=False)
            ],
            certifications=[
                Certification(name="Goods & Services Tax Certificate", doc_present=True)
            ],
        ),
        **NO_EMBED,
    )
    gst = next(i for i in report.items if "GST" in i.requirement)
    assert gst.status is CheckStatus.MISSING


def test_an_unrelated_certification_still_satisfies_its_own_requirement():
    """The suppression must be targeted -- one contradicted document must not
    invalidate every other certification in the bid."""
    report = build_gap_report(
        notification(
            mandatory_documents=[
                MandatoryDocument(doc_name="ISO 9001 Certificate"),
                MandatoryDocument(doc_name="GST Registration Certificate"),
            ]
        ),
        submission(
            documents_submitted=[
                SubmittedDocument(doc_name="ISO 9001 Certificate", present=False)
            ],
            certifications=[
                Certification(name="ISO 9001:2015", doc_present=True),
                Certification(name="GST Registration Certificate", doc_present=True),
            ],
        ),
        **NO_EMBED,
    )
    assert next(i for i in report.items if "ISO" in i.requirement).status is CheckStatus.MISSING
    assert next(i for i in report.items if "GST" in i.requirement).status is CheckStatus.MATCH


# --------------------------------------------------------------------------- #
# Action ranking by fixability (regression: the one real failure ranked 39/39)
# --------------------------------------------------------------------------- #
from app.compliance.models import ActionGroup  # noqa: E402


def _many_missing_documents(count: int):
    return [MandatoryDocument(doc_name=f"Annexure {i} declaration") for i in range(count)]


def test_an_unfixable_failure_outranks_a_pile_of_missing_documents():
    """On the real GHMC tender this ordering put "your turnover is below the
    floor" at position 39 of 39, under 38 document uploads. Every unmet
    mandatory requirement is "disqualifying", so severity alone cannot separate
    them -- what differs is whether the vendor can do anything about it."""
    report = build_gap_report(
        notification(mandatory_documents=_many_missing_documents(30)),
        submission(
            documents_submitted=[],
            turnover=[YearlyTurnover(year=2023, amount=MoneyAmount(raw_text="Rs. 1 Cr"))],
        ),
        **NO_EMBED,
    )

    assert len(report.action_list) > 30
    first = report.action_list[0]
    assert first.group is ActionGroup.HARD_FAIL
    assert "turnover" in first.action.lower()
    assert "₹5 Cr" in first.action, "the vendor must see both figures, not just a verdict"


def test_action_groups_are_ordered_hard_fail_upload_clarify_verify():
    report = build_gap_report(
        notification(
            mandatory_documents=_many_missing_documents(3),
            submission_format_rules=[SubmissionFormatRule(rule="Sign every page")],
        ),
        submission(
            documents_submitted=[],
            years_in_business=None,   # -> clarify
            turnover=[YearlyTurnover(year=2023, amount=MoneyAmount(raw_text="Rs. 1 Cr"))],
        ),
        **NO_EMBED,
    )
    order = [a.group for a in report.action_list]
    rank = {
        ActionGroup.HARD_FAIL: 0,
        ActionGroup.UPLOAD: 1,
        ActionGroup.CLARIFY: 2,
        ActionGroup.VERIFY: 3,
    }
    assert [rank[g] for g in order] == sorted(rank[g] for g in order)


def test_a_missing_document_is_upload_not_hard_fail():
    """Fixable before the deadline: it must not sit beside "you do not qualify"."""
    report = build_gap_report(
        notification(),
        submission(documents_submitted=[]),
        **NO_EMBED,
    )
    doc_actions = [
        a for a in report.action_list if a.action.startswith("Upload ")
    ]
    assert doc_actions
    assert all(a.group is ActionGroup.UPLOAD for a in doc_actions)


def test_unreadable_values_are_clarify_not_upload():
    report = build_gap_report(
        notification(),
        submission(
            turnover=[
                YearlyTurnover(year=2023, amount=MoneyAmount(raw_text="see annexure"))
            ]
        ),
        **NO_EMBED,
    )
    clarify = [a for a in report.action_list if a.group is ActionGroup.CLARIFY]
    assert clarify
    assert any("state clearly" in a.action.lower() for a in clarify)


def test_conditional_requirements_are_verify_not_upload():
    """A JV agreement is not something a sole bidder should be told to upload."""
    report = build_gap_report(
        notification(
            mandatory_documents=[
                MandatoryDocument(doc_name="JV / Consortium Agreement"),
                MandatoryDocument(doc_name="GST Registration Certificate"),
            ]
        ),
        submission(documents_submitted=[]),
        **NO_EMBED,
    )
    jv = next(a for a in report.action_list if "JV" in a.requirement)
    gst = next(a for a in report.action_list if "GST" in a.requirement)
    assert jv.group is ActionGroup.VERIFY
    assert gst.group is ActionGroup.UPLOAD


# --------------------------------------------------------------------------- #
# Self-declared debarment (regression: a debarred bidder passed Level 1)
# --------------------------------------------------------------------------- #
DISCLOSURE = (
    "We disclose that our firm was debarred by the Public Health Engineering "
    "Department, Government of Chhattisgarh vide order dated 11.07.2023."
)


def _blacklist_notification():
    return notification(
        eligibility_criteria=[
            EligibilityCriterion(
                criterion="Not blacklisted or debarred", type=CriterionType.BOOLEAN
            )
        ]
    )


def test_a_bid_disclosing_its_own_debarment_is_eliminated():
    """Section 5.8 stubs the debarment check as a manual flag, so a bid that
    admitted debarment in its own text passed Level 1 -- a false negative found
    by evaluating against the answer key."""
    report = build_gap_report(
        _blacklist_notification(),
        submission(is_blacklisted=True, debarment_disclosure=DISCLOSURE),
        **NO_EMBED,
    )
    item = next(i for i in report.items if "blacklist" in i.requirement.lower())
    assert item.status is CheckStatus.MISSING
    assert item.severity is Severity.DISQUALIFYING
    # The elimination quotes the bidder rather than asserting an internal flag.
    assert "Public Health Engineering" in item.explanation
    assert item.submission_provenance.source_snippet == DISCLOSURE


def test_a_manual_flag_without_a_disclosure_still_eliminates():
    """A reviewer's knowledge of an official list must not need the bidder to
    have confessed."""
    report = build_gap_report(
        _blacklist_notification(),
        submission(is_blacklisted=True),
        **NO_EMBED,
    )
    item = next(i for i in report.items if "blacklist" in i.requirement.lower())
    assert item.status is CheckStatus.MISSING
    assert "flagged as blacklisted" in item.explanation.lower()


def test_liquidation_wording_is_recognised_as_a_disqualifier():
    """HGCL words the same condition as liquidation rather than blacklisting."""
    report = build_gap_report(
        notification(
            eligibility_criteria=[
                EligibilityCriterion(
                    criterion="The Bidder should not be under liquidation",
                    type=CriterionType.BOOLEAN,
                )
            ]
        ),
        submission(is_blacklisted=True, debarment_disclosure="NCLT petition admitted."),
        **NO_EMBED,
    )
    item = next(i for i in report.items if "liquidation" in i.requirement.lower())
    assert item.severity is Severity.DISQUALIFYING


def test_a_clean_declaration_is_not_read_as_a_disclosure():
    """Nearly every bid contains a non-blacklisting declaration. Treating those
    as admissions would eliminate the entire field."""
    from app.extraction import llm_schemas as raw
    from app.extraction.convert import to_submission

    result = to_submission(
        raw.RawVendorHeader(vendor_name="Clean Co", declared_debarment=None),
        [], [], [], [],
        vendor_id="V-1", fallback_vendor_name="Clean Co",
    )
    assert result.is_blacklisted is False
    assert result.debarment_disclosure is None


def test_extraction_turns_a_disclosure_into_the_flag():
    from app.extraction import llm_schemas as raw
    from app.extraction.convert import to_submission

    result = to_submission(
        raw.RawVendorHeader(vendor_name="Sunrise", declared_debarment=DISCLOSURE),
        [], [], [], [],
        vendor_id="V-2", fallback_vendor_name="Sunrise",
    )
    assert result.is_blacklisted is True
    assert result.debarment_disclosure == DISCLOSURE
