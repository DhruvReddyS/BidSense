"""The Section 4.6 missing-item action list.

The list is generated from the gap report, not from anything new -- no second
extraction, no LLM. What it adds is ORDER and VOICE: a vendor reading this
before a deadline needs the thing that stops them bidding at the top, in words
that say what to do about it.

Two failures this file exists to prevent, both measured on the real corpus:

  * the unfixable failure buried. Every unmet mandatory requirement is
    "disqualifying", so sorting by severity alone left a turnover shortfall at
    position 39 of 39, under thirty-eight documents that could be attached in a
    morning.
  * the conditional wall. A compliant sole proprietor on the GHMC tender
    collected twenty-three to-dos, six of which were joint-venture paperwork
    they neither have nor need. A to-do list that is mostly inapplicable is one
    a vendor stops reading.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.compliance.gap import build_gap_report
from app.compliance.models import ActionGroup, Severity
from app.schemas.common import CriterionType, MoneyAmount, Provenance, YearlyTurnover
from app.schemas.notification import (
    EligibilityCriterion,
    MandatoryDocument,
    TenderNotification,
)
from app.schemas.submission import SubmittedDocument, VendorSubmission


def _prov(clause: str = "4.2") -> Provenance:
    return Provenance(clause_ref=clause, source_page=2, source_snippet="x")


def _notification(**kwargs) -> TenderNotification:
    kwargs.setdefault("tender_id", "T-1")
    kwargs.setdefault("title", "t")
    kwargs.setdefault("issuing_authority", "a")
    return TenderNotification(**kwargs)


def _submission(**kwargs) -> VendorSubmission:
    kwargs.setdefault("vendor_id", "V-1")
    kwargs.setdefault("vendor_name", "V Ltd")
    kwargs.setdefault("tender_id", "T-1")
    return VendorSubmission(**kwargs)


# --------------------------------------------------------------------------- #
# Voice
# --------------------------------------------------------------------------- #
def test_a_missing_document_becomes_an_upload_instruction() -> None:
    report = build_gap_report(
        _notification(
            mandatory_documents=[
                MandatoryDocument(doc_name="GST Registration Certificate", provenance=_prov("7"))
            ]
        ),
        _submission(),
    )
    action = report.action_list[0]
    assert action.action == "Upload GST Registration Certificate"
    assert action.group is ActionGroup.UPLOAD
    assert action.clause_ref == "7"
    assert action.is_blocking


def test_a_threshold_failure_states_both_figures_and_the_consequence() -> None:
    """Section 4.6's own example. "Upload turnover certificate" would be wrong
    advice -- no document fixes a turnover that is genuinely too low."""
    report = build_gap_report(
        _notification(
            eligibility_criteria=[
                EligibilityCriterion(
                    criterion="Average annual turnover",
                    type=CriterionType.NUMERIC,
                    threshold_raw="Rs. 5 Cr",
                    threshold_amount=MoneyAmount(raw_text="Rs. 5 Cr"),
                    unit="INR",
                    provenance=_prov("4.2"),
                )
            ]
        ),
        _submission(
            turnover=[
                YearlyTurnover(
                    year=2024,
                    amount=MoneyAmount(raw_text="Rs. 3.2 Cr"),
                    provenance=_prov(),
                )
            ]
        ),
    )
    action = report.action_list[0]
    assert action.group is ActionGroup.HARD_FAIL
    assert action.is_blocking
    assert "3.2 Cr" in action.action and "5 Cr" in action.action
    assert "do not currently qualify" in action.action
    assert not action.action.lower().startswith("upload")


def test_an_unreadable_value_asks_the_vendor_to_state_it_not_to_upload() -> None:
    report = build_gap_report(
        _notification(
            eligibility_criteria=[
                EligibilityCriterion(
                    criterion="Average annual turnover",
                    type=CriterionType.NUMERIC,
                    threshold_raw="Rs. 5 Cr",
                    threshold_amount=MoneyAmount(raw_text="Rs. 5 Cr"),
                    unit="INR",
                    provenance=_prov(),
                )
            ]
        ),
        _submission(),
    )
    action = report.action_list[0]
    assert action.group is ActionGroup.CLARIFY
    assert action.action.startswith("State clearly in your bid")


def test_a_satisfied_requirement_produces_no_action() -> None:
    report = build_gap_report(
        _notification(
            mandatory_documents=[
                MandatoryDocument(doc_name="PAN Card", provenance=_prov())
            ]
        ),
        _submission(
            documents_submitted=[
                SubmittedDocument(doc_name="PAN Card", present=True, provenance=_prov())
            ]
        ),
    )
    assert report.action_list == []


# --------------------------------------------------------------------------- #
# Order
# --------------------------------------------------------------------------- #
def test_the_unfixable_failure_outranks_a_pile_of_missing_documents() -> None:
    report = build_gap_report(
        _notification(
            mandatory_documents=[
                MandatoryDocument(doc_name=f"Certificate {i}", provenance=_prov())
                for i in range(20)
            ],
            eligibility_criteria=[
                EligibilityCriterion(
                    criterion="Average annual turnover",
                    type=CriterionType.NUMERIC,
                    threshold_raw="Rs. 5 Cr",
                    threshold_amount=MoneyAmount(raw_text="Rs. 5 Cr"),
                    unit="INR",
                    provenance=_prov(),
                )
            ],
        ),
        _submission(
            turnover=[
                YearlyTurnover(
                    year=2024, amount=MoneyAmount(raw_text="Rs. 1 Cr"), provenance=_prov()
                )
            ]
        ),
    )
    assert report.action_list[0].group is ActionGroup.HARD_FAIL, (
        "the one thing that cannot be fixed by uploading anything must lead"
    )


def test_conditional_items_sink_below_everything_that_applies_to_everyone() -> None:
    report = build_gap_report(
        _notification(
            mandatory_documents=[
                MandatoryDocument(doc_name="Joint Venture Agreement", provenance=_prov()),
                MandatoryDocument(doc_name="GST Registration Certificate", provenance=_prov()),
            ]
        ),
        _submission(),
    )
    conditional = [a for a in report.action_list if a.applies_only_if]
    unconditional = [a for a in report.action_list if not a.applies_only_if]
    assert conditional and unconditional
    last_unconditional = max(report.action_list.index(a) for a in unconditional)
    first_conditional = min(report.action_list.index(a) for a in conditional)
    assert first_conditional > last_unconditional


# --------------------------------------------------------------------------- #
# The conditional wall
# --------------------------------------------------------------------------- #
def test_a_conditional_document_says_it_is_conditional_in_the_todo_itself() -> None:
    """"Check yourself: Submit Joint Venture Agreement" reads as an instruction
    to a sole proprietor who has no such agreement and needs none."""
    report = build_gap_report(
        _notification(
            mandatory_documents=[
                MandatoryDocument(doc_name="Joint Venture Agreement", provenance=_prov())
            ]
        ),
        _submission(),
    )
    action = report.action_list[0]
    assert action.applies_only_if == "you are bidding as a joint venture or consortium"
    assert action.action.startswith("Only if you are bidding as a joint venture")
    assert "does not apply to you" in action.action
    assert not action.is_blocking, "a JV document is not a gap for a sole bidder"


def test_a_conditional_document_that_near_matches_keeps_its_qualifier() -> None:
    """The branch this was missed on.

    A conditional requirement that turns up a near-match leaves through the
    PARTIAL branch, which sits ABOVE the conditional branch. Setting the
    qualifier only on the not-found path dropped it from exactly these rows --
    and on the GHMC tender that is most of the joint-venture paperwork, so a
    sole proprietor was told to "confirm" four documents they do not need.
    """
    report = build_gap_report(
        _notification(
            mandatory_documents=[
                MandatoryDocument(
                    doc_name="JV / Consortium Agreement", provenance=_prov()
                )
            ]
        ),
        _submission(
            documents_submitted=[
                SubmittedDocument(
                    doc_name="undertaking by the Bidder/JV/Consortium",
                    present=True,
                    provenance=_prov(),
                )
            ]
        ),
    )
    action = report.action_list[0]
    assert action.applies_only_if, f"the qualifier was dropped: {action.action!r}"
    assert action.action.startswith("Only if you are bidding as a joint venture")


def test_the_instruction_reads_as_a_sentence_not_a_stitched_fragment() -> None:
    """Requirements arrive as "Submit X" already, so a blanket prefix yields
    "Only if ...: Submit Submit X"."""
    report = build_gap_report(
        _notification(
            mandatory_documents=[
                MandatoryDocument(doc_name="Joint Venture Agreement", provenance=_prov())
            ]
        ),
        _submission(),
    )
    assert "submit submit" not in report.action_list[0].action.lower()
    assert ": submit Joint Venture Agreement." in report.action_list[0].action


# --------------------------------------------------------------------------- #
# The counts the UI leads with
# --------------------------------------------------------------------------- #
def test_action_counts_separate_what_blocks_a_bid_from_what_to_check() -> None:
    report = build_gap_report(
        _notification(
            mandatory_documents=[
                MandatoryDocument(doc_name="GST Registration Certificate", provenance=_prov()),
                MandatoryDocument(doc_name="Joint Venture Agreement", provenance=_prov()),
            ],
            submission_format_rules=[],
        ),
        _submission(),
    )
    counts = report.action_counts
    assert counts["blocking"] == 1
    assert counts["conditional"] == 1
    assert sum(counts.values()) == len(report.action_list)


def test_a_clean_bid_reports_no_blocking_actions() -> None:
    report = build_gap_report(
        _notification(
            mandatory_documents=[
                MandatoryDocument(doc_name="PAN Card", provenance=_prov())
            ]
        ),
        _submission(
            documents_submitted=[
                SubmittedDocument(doc_name="PAN Card", present=True, provenance=_prov())
            ]
        ),
    )
    assert report.action_counts["blocking"] == 0


# --------------------------------------------------------------------------- #
# It must stay derived, not re-extracted
# --------------------------------------------------------------------------- #
def test_the_action_list_is_derived_from_the_gap_report_alone() -> None:
    """Structural. Section 4.6 reuses 4.3's output; an action list that went
    back to the document would be a second, divergent opinion about the same
    bid -- and would cost LLM calls a free tier cannot spare."""
    import inspect

    from app.compliance import gap

    source = inspect.getsource(gap._build_action_list)
    for forbidden in ("llm", "generate_", "retrieve", "embed"):
        assert forbidden not in source.lower(), (
            f"the action list reaches for {forbidden!r}; it must derive from GapItems"
        )
    assert inspect.signature(gap._build_action_list).parameters.keys() == {"items"}


# --------------------------------------------------------------------------- #
# The completion meter (Stage 4.12) -- a count, explicitly not a score
# --------------------------------------------------------------------------- #
def test_the_meter_counts_satisfied_mandatory_requirements() -> None:
    report = build_gap_report(
        _notification(
            mandatory_documents=[
                MandatoryDocument(doc_name="PAN Card", provenance=_prov()),
                MandatoryDocument(doc_name="GST Registration Certificate", provenance=_prov()),
                MandatoryDocument(doc_name="Solvency Certificate", provenance=_prov()),
            ]
        ),
        _submission(
            documents_submitted=[
                SubmittedDocument(doc_name="PAN Card", present=True, provenance=_prov()),
                SubmittedDocument(
                    doc_name="GST Registration Certificate", present=True, provenance=_prov()
                ),
            ]
        ),
    )
    completion = report.completion
    assert (completion.satisfied, completion.total) == (2, 3)
    assert completion.label == "2 of 3 mandatory requirements satisfied"


def test_an_undecided_requirement_counts_neither_way() -> None:
    """Rolling "we could not establish this" into either column invents
    information: upward it flatters the bid, downward it reports a vendor as
    failing something nobody checked."""
    report = build_gap_report(
        _notification(
            mandatory_documents=[
                MandatoryDocument(doc_name="PAN Card", provenance=_prov()),
                MandatoryDocument(doc_name="Joint Venture Agreement", provenance=_prov()),
            ]
        ),
        _submission(
            documents_submitted=[
                SubmittedDocument(doc_name="PAN Card", present=True, provenance=_prov())
            ]
        ),
    )
    completion = report.completion
    assert completion.satisfied == 1
    assert completion.undetermined == 1
    assert completion.satisfied + completion.undetermined <= completion.total


def test_the_meter_carries_the_copy_that_stops_it_reading_as_a_score() -> None:
    """Section 4.4 forbids inventing a score. A bare "7/9" beside a progress bar
    reads as one to everybody, so the disclaimer travels WITH the number rather
    than living in a docstring or being left to whoever writes the UI."""
    report = build_gap_report(
        _notification(
            mandatory_documents=[MandatoryDocument(doc_name="PAN Card", provenance=_prov())]
        ),
        _submission(),
    )
    caveat = report.completion.caveat
    assert "not a score" in caveat
    assert "weight" in caveat
    assert "cannot be compared" in caveat


def test_the_meter_is_not_a_percentage_or_a_grade() -> None:
    """Structural. The moment this exposes a ratio, someone renders it as 78%
    and Section 4.4's rule is gone -- a number the vendor cannot trace to a
    clause is exactly what that rule exists to prevent."""
    from app.compliance.models import Completion

    fields = set(Completion.model_fields)
    assert fields == {"satisfied", "total", "undetermined"}
    for forbidden in ("score", "percent", "percentage", "grade", "rating", "ratio"):
        assert not any(forbidden in f for f in fields)


def test_the_score_preview_stays_unavailable_when_no_weights_are_published() -> None:
    """The meter must not have quietly become the score Section 4.4 refuses to
    invent. Both can be true at once: a factual count, and no score."""
    report = build_gap_report(
        _notification(
            mandatory_documents=[MandatoryDocument(doc_name="PAN Card", provenance=_prov())]
        ),
        _submission(),
    )
    assert report.score_preview.available is False
    assert report.completion.total == 1
