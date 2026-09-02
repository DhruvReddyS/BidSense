"""Extraction graph, conversion and honesty-constraint tests.

Run against a scripted stub LLM so orchestration and conversion are verified
deterministically. Accuracy against a real model is Section 10's job.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.extraction.convert import parse_date, to_eligibility
from app.extraction.graph import extract_notification, extract_submission
from app.extraction import llm_schemas as raw
from app.ingest import parse_document
from app.schemas.common import CriterionType, DocumentKind, VendorStatus
from tests.doc_factory import NOTIFICATION_TRUTH, make_notification_pdf
from tests.stub_llm import StubLLM


@pytest.fixture(scope="module")
def parsed(tmp_path_factory):
    path = make_notification_pdf(tmp_path_factory.mktemp("x") / "NOTIF_ITservices_01.pdf")
    return parse_document(path, DocumentKind.NOTIFICATION)


@pytest.fixture
def stub():
    return StubLLM()


# --------------------------------------------------------------------------- #
# Graph orchestration
# --------------------------------------------------------------------------- #
def test_all_six_notification_extractors_run(parsed, stub):
    notification, result = extract_notification(parsed, llm=stub)
    assert set(stub.calls) == {
        "RawHeader",
        "EligibilityList",
        "DocumentList",
        "EvaluationList",
        "TechnicalList",
        "FormatRuleList",
    }
    assert result["errors"] == []
    assert len(result["timings"]) == 6
    assert notification.tender_id == NOTIFICATION_TRUTH["tender_id"]


def test_extraction_produces_the_full_section_6_shape(parsed, stub):
    notification, _ = extract_notification(parsed, llm=stub)
    assert notification.issuing_authority == NOTIFICATION_TRUTH["issuing_authority"]
    assert notification.submission_deadline == date(2026, 3, 15)
    assert notification.pre_bid_query_deadline == date(2026, 2, 20)
    assert len(notification.eligibility_criteria) == 3
    assert len(notification.mandatory_documents) == 5
    assert len(notification.technical_requirements) == 2
    assert len(notification.submission_format_rules) == 2


def test_one_failing_extractor_does_not_lose_the_others(parsed):
    """Partial extraction that names its gaps beats all-or-nothing failure."""
    stub = StubLLM(fail_on={"EvaluationList", "TechnicalList"})
    notification, result = extract_notification(parsed, llm=stub)

    assert len(result["errors"]) == 2
    assert any("evaluation" in e for e in result["errors"])
    assert notification.evaluation_criteria == []
    assert notification.technical_requirements == []
    # The healthy branches still landed.
    assert len(notification.eligibility_criteria) == 3
    assert notification.tender_id == NOTIFICATION_TRUTH["tender_id"]


def test_total_header_failure_falls_back_to_filename(parsed):
    """tender_id and title are required; a document that fails to yield them
    must still be storable and reviewable rather than dropped."""
    stub = StubLLM(fail_on={"RawHeader"})
    notification, result = extract_notification(parsed, llm=stub)
    assert notification.tender_id == "NOTIF_ITservices_01.pdf"
    assert notification.submission_deadline is None
    assert any("header" in e for e in result["errors"])


# --------------------------------------------------------------------------- #
# Normalization boundary -- the LLM never computes
# --------------------------------------------------------------------------- #
def test_money_thresholds_are_normalized_in_code_not_by_the_model(parsed, stub):
    notification, _ = extract_notification(parsed, llm=stub)
    turnover = next(
        c for c in notification.eligibility_criteria if "turnover" in c.criterion.lower()
    )
    assert turnover.threshold_raw == "Rs. 5 Cr"           # what the model returned
    assert turnover.threshold_amount.amount_inr == Decimal("50000000.00")  # what code derived
    assert turnover.threshold_number is None


def test_non_monetary_numeric_threshold_routes_to_the_number_slot(parsed, stub):
    notification, _ = extract_notification(parsed, llm=stub)
    experience = next(
        c for c in notification.eligibility_criteria if "experience" in c.criterion.lower()
    )
    assert experience.threshold_number == 5.0
    assert experience.threshold_amount is None


def test_a_years_threshold_is_never_read_as_rupees():
    """'5 (five) years' must not become Rs. 5 -- that would compare a duration
    against a turnover threshold."""
    criterion = to_eligibility(
        raw.RawEligibilityCriterion(
            criterion="Experience", type=CriterionType.NUMERIC,
            threshold_raw="5 (five) years", unit="years",
        )
    )
    assert criterion.threshold_amount is None
    assert criterion.threshold_number == 5.0


def test_unresolvable_numeric_threshold_still_produces_a_criterion():
    """It must surface as needs-manual-check, not vanish from the eligibility list."""
    criterion = to_eligibility(
        raw.RawEligibilityCriterion(
            criterion="Turnover", type=CriterionType.NUMERIC,
            threshold_raw="as specified in Annexure II",
        )
    )
    assert criterion.threshold_raw == "as specified in Annexure II"
    assert criterion.threshold_amount is None
    assert criterion.threshold_number is None


def test_emd_normalized_from_printed_form(parsed, stub):
    notification, _ = extract_notification(parsed, llm=stub)
    assert notification.emd_amount.raw_text == "Rs. 2,00,000"
    assert notification.emd_amount.amount_inr == Decimal("200000.00")
    assert notification.contract_value_estimate.amount_inr == Decimal("125000000.00")


# --------------------------------------------------------------------------- #
# Section 4.4 honesty constraint
# --------------------------------------------------------------------------- #
def test_unpublished_weightage_yields_no_score(parsed, stub):
    """The fixture notification publishes no scoring weights, so the system must
    not be able to show a self-score."""
    notification, _ = extract_notification(parsed, llm=stub)
    assert notification.evaluation_criteria == []
    assert notification.publishes_weightage is False


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #
def test_every_extracted_item_keeps_its_citation(parsed, stub):
    notification, _ = extract_notification(parsed, llm=stub)
    turnover = next(
        c for c in notification.eligibility_criteria if "turnover" in c.criterion.lower()
    )
    assert turnover.provenance.clause_ref == NOTIFICATION_TRUTH["turnover_clause"]
    assert turnover.provenance.source_page == 2
    assert "Rs. 5 Cr" in turnover.provenance.source_snippet


def test_cited_page_matches_where_the_text_actually_is(parsed, stub):
    """A citation pointing at the wrong page is worse than none -- it looks
    verifiable and isn't."""
    notification, _ = extract_notification(parsed, llm=stub)
    for criterion in notification.eligibility_criteria:
        page = parsed.page(criterion.provenance.source_page)
        assert page is not None
        snippet_head = criterion.provenance.source_snippet.split("(")[0].strip()[:30]
        assert snippet_head in page.combined_text().replace("\n", " ")


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-03-15", date(2026, 3, 15)),
        ("15.03.2026", date(2026, 3, 15)),
        ("15/03/2026", date(2026, 3, 15)),
        ("15 March 2026", date(2026, 3, 15)),
        ("March 15, 2026", date(2026, 3, 15)),
    ],
)
def test_indian_date_formats_parse_day_first(text, expected):
    assert parse_date(text) == expected


def test_unparseable_date_returns_none_rather_than_guessing():
    assert parse_date("within 21 days of award") is None
    assert parse_date(None) is None


# --------------------------------------------------------------------------- #
# Vendor submission side
# --------------------------------------------------------------------------- #
def test_vendor_extraction_full_shape(parsed, stub):
    submission, result = extract_submission(parsed, vendor_id="V-04", llm=stub)
    assert result["errors"] == []
    assert submission.vendor_name == "Delta Systems Pvt Ltd"
    assert submission.years_in_business == 8.5
    assert submission.status is VendorStatus.PENDING
    assert submission.is_blacklisted is False
    assert len(submission.certifications) == 2
    assert len(submission.past_projects) == 1


def test_vendor_turnover_normalized_and_unparseable_kept_null(parsed, stub):
    submission, _ = extract_submission(parsed, vendor_id="V-04", llm=stub)
    by_year = {t.year: t for t in submission.turnover}
    assert by_year[2023].amount.amount_inr == Decimal("42000000.00")
    assert by_year[2022].amount.amount_inr == Decimal("38000000.00")
    # "as per annexure IV" is unresolvable and must stay None, never 0.
    assert by_year[2024].amount.amount_inr is None
    assert by_year[2024].amount.raw_text == "as per annexure IV"


def test_latest_resolved_turnover_skips_the_unparseable_year(parsed, stub):
    submission, _ = extract_submission(parsed, vendor_id="V-04", llm=stub)
    assert submission.latest_turnover().year == 2023


def test_technical_approach_preserved_verbatim_for_the_vector_store(parsed, stub):
    submission, _ = extract_submission(parsed, vendor_id="V-04", llm=stub)
    assert submission.technical_approach_text.startswith("Our delivery methodology")


def test_document_marked_absent_stays_absent(parsed, stub):
    """A checklist entry marked not-enclosed is a compliance fact, not noise."""
    submission, _ = extract_submission(parsed, vendor_id="V-04", llm=stub)
    iso = next(d for d in submission.documents_submitted if "ISO" in d.doc_name)
    assert iso.present is False


def test_certification_without_expiry_is_tri_state(parsed, stub):
    submission, _ = extract_submission(parsed, vendor_id="V-04", llm=stub)
    gst = next(c for c in submission.certifications if "GST" in c.name)
    assert gst.valid_till is None
    assert gst.is_valid_on(date(2026, 1, 1)) is None  # unknown, not valid


# --------------------------------------------------------------------------- #
# Monetary vs non-monetary discrimination (regression: "years" contains "rs")
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("threshold", "unit", "expect_money"),
    [
        ("Rs. 5 Cr", "INR", True),
        ("₹5 Cr", None, True),
        ("5,00,00,000", "INR", True),
        ("50 lakh", None, True),
        # The trap cases: each contains a monetary token as a substring only.
        ("5 (five) years", "years", False),
        ("3 years", "years", False),
        ("2 projects", "projects", False),
        ("10 crores worth", None, True),
    ],
)
def test_monetary_detection_uses_word_boundaries(threshold, unit, expect_money):
    criterion = to_eligibility(
        raw.RawEligibilityCriterion(
            criterion="x", type=CriterionType.NUMERIC, threshold_raw=threshold, unit=unit
        )
    )
    if expect_money:
        assert criterion.threshold_amount is not None, f"{threshold!r} should be money"
        assert criterion.threshold_number is None
    else:
        assert criterion.threshold_amount is None, f"{threshold!r} must not be money"
        assert criterion.threshold_number is not None


def test_word_numerals_surface_as_needs_manual_check():
    """"Rupees Five Crore only" with no digits is a known limitation: it is
    recognised as monetary but cannot be canonicalised, so both threshold slots
    stay None and the criterion falls to manual review. Guessing 5 Cr from the
    words would be the model doing arithmetic we cannot audit."""
    criterion = to_eligibility(
        raw.RawEligibilityCriterion(
            criterion="Turnover",
            type=CriterionType.NUMERIC,
            threshold_raw="Rupees Five Crore only",
            unit="INR",
        )
    )
    assert criterion.threshold_raw == "Rupees Five Crore only"
    assert criterion.threshold_amount is None
    assert criterion.threshold_number is None


def test_digits_alongside_words_still_resolve():
    """The common real form pairs both -- the digits must win."""
    criterion = to_eligibility(
        raw.RawEligibilityCriterion(
            criterion="Turnover",
            type=CriterionType.NUMERIC,
            threshold_raw="Rs. 5,00,00,000 (Rupees Five Crore only)",
            unit="INR",
        )
    )
    assert criterion.threshold_amount.amount_inr == Decimal("50000000.00")


# --------------------------------------------------------------------------- #
# Relative thresholds (Indian works tenders express eligibility as a share of
# the estimated cost, not an absolute figure)
# --------------------------------------------------------------------------- #
from decimal import Decimal as _D  # noqa: E402

from app.extraction.convert import relative_share  # noqa: E402


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("30% of the estimated cost", 30.0),
        ("80% of Estimated Cost", 80.0),
        ("not less than 40 percent of the estimated value", 40.0),
        ("50% of ECPT", 50.0),
        ("100% of the contract value", 100.0),
        # A percentage that is not a share of the estimate.
        ("80% marks in the technical evaluation", None),
        ("minimum 60% attendance", None),
        # Not a percentage at all.
        ("Rs. 5 Cr", None),
        ("5 (five) years", None),
        (None, None),
    ],
)
def test_relative_threshold_detection(text, expected):
    assert relative_share(text) == expected


def test_percentage_threshold_resolves_against_the_estimated_cost():
    """IIT (ISM) Dhanbad states "Average Annual Financial Turnover ... 30% of
    the estimated cost". Read naively that is a threshold of 30 rupees, which
    every bidder clears -- the same failure class as a project count being read
    as an amount."""
    criterion = to_eligibility(
        raw.RawEligibilityCriterion(
            criterion="Average Annual Financial Turnover",
            type=CriterionType.NUMERIC,
            threshold_raw="30% of the estimated cost",
        ),
        contract_value_inr=_D("1256561.00"),
    )
    assert criterion.threshold_amount.amount_inr == _D("376968.30")
    assert criterion.threshold_number is None, "the bare percentage must never be a threshold"


def test_percentage_threshold_without_an_estimate_is_left_unresolved():
    """Honest outcome: needs-manual-check. Inventing an absolute figure from an
    unknown base would be worse than admitting we cannot compute it."""
    criterion = to_eligibility(
        raw.RawEligibilityCriterion(
            criterion="Average Annual Financial Turnover",
            type=CriterionType.NUMERIC,
            threshold_raw="30% of the estimated cost",
        )
    )
    assert criterion.threshold_amount is None
    assert criterion.threshold_number is None
    assert criterion.threshold_raw == "30% of the estimated cost"


def test_notification_assembly_wires_the_estimate_into_relative_thresholds():
    from app.extraction.convert import to_notification

    notification = to_notification(
        raw.RawHeader(tender_id="T-1", title="Boundary wall", contract_value_raw="Rs. 12,56,561/-"),
        [
            raw.RawEligibilityCriterion(
                criterion="Average Annual Financial Turnover",
                type=CriterionType.NUMERIC,
                threshold_raw="30% of the estimated cost",
            )
        ],
        [], [], [], [],
        fallback_tender_id="f", fallback_title="f",
    )
    criterion = notification.eligibility_criteria[0]
    assert notification.contract_value_estimate.amount_inr == _D("1256561.00")
    assert criterion.threshold_amount.amount_inr == _D("376968.30")


# --------------------------------------------------------------------------- #
# Table of contents vs enclosure checklist (regression)
# --------------------------------------------------------------------------- #
def test_the_enclosure_prompt_rules_out_the_bids_own_contents_page():
    """A 60-page bid opens with an index of its own sections. Extracted as
    enclosures, those chapters replaced the real checklist and every required
    certificate looked missing -- a defect no nine-page bid could surface."""
    from app.extraction.prompts import SUBMITTED_DOCUMENTS_PROMPT

    prompt = SUBMITTED_DOCUMENTS_PROMPT.lower()
    assert "table of contents" in prompt
    assert "not documents enclosed with it" in prompt
    # It must also say how to tell them apart, not merely forbid the mistake.
    assert "page numbers" in prompt
    assert "checklist" in prompt


def test_selection_cues_do_not_favour_a_contents_page():
    """"index" and "page no" match a table of contents far more strongly than an
    enclosure checklist."""
    from app.extraction.selection import FIELD_GROUPS

    cues = FIELD_GROUPS["submitted_documents"].cues
    assert "index" not in cues
    assert "page no" not in cues
    assert "not enclosed" in cues
    assert any("enclos" in c for c in cues)


def test_the_enclosure_prompt_defines_the_absent_case():
    """A checklist entry marked NOT ENCLOSED is a compliance fact, and the
    prompt has to say so or the model reports it as present."""
    from app.extraction.prompts import SUBMITTED_DOCUMENTS_PROMPT

    assert "not enclosed" in SUBMITTED_DOCUMENTS_PROMPT.lower()
    assert "present=false" in SUBMITTED_DOCUMENTS_PROMPT.lower()
