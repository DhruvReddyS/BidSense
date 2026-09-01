"""Section 6 schema invariants."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas import (
    Certification,
    ChangedField,
    Corrigendum,
    CriterionType,
    EligibilityCriterion,
    EvaluationCriterion,
    MandatoryDocument,
    MoneyAmount,
    TenderNotification,
    VendorStatus,
    VendorSubmission,
    YearlyTurnover,
)


def test_money_auto_normalizes_from_raw_text() -> None:
    money = MoneyAmount(raw_text="Rs. 5 Cr")
    assert money.amount_inr == Decimal("50000000.00")
    assert money.is_resolved


def test_money_unresolved_is_not_zero() -> None:
    """An unparseable figure must stay None so it surfaces as needs-manual-check
    rather than being compared as zero by the rule engine."""
    money = MoneyAmount(raw_text="as per Annexure IV")
    assert money.amount_inr is None
    assert not money.is_resolved


def test_turnover_year_accepts_financial_year_notation() -> None:
    assert YearlyTurnover(year="2023-24", amount=MoneyAmount(raw_text="4.2 Cr")).year == 2023
    assert YearlyTurnover(year="FY2022", amount=MoneyAmount(raw_text="1 Cr")).year == 2022


def test_numeric_criterion_requires_a_threshold() -> None:
    with pytest.raises(ValidationError, match="numeric criterion requires a threshold"):
        EligibilityCriterion(criterion="Annual turnover", type=CriterionType.NUMERIC)

    ok = EligibilityCriterion(
        criterion="Annual turnover",
        type=CriterionType.NUMERIC,
        threshold_amount=MoneyAmount(raw_text="₹5 Cr"),
    )
    assert ok.threshold_amount.amount_inr == Decimal("50000000.00")


def test_document_criterion_needs_no_threshold() -> None:
    EligibilityCriterion(criterion="Valid GST registration", type=CriterionType.DOCUMENT)


def test_section_4_4_unpublished_weightage_stays_none() -> None:
    """Section 4.4 forbids inventing a score when weightage isn't published."""
    notification = TenderNotification(
        tender_id="T-1",
        title="Supply of network equipment",
        evaluation_criteria=[EvaluationCriterion(factor="Technical capability")],
    )
    assert notification.evaluation_criteria[0].weightage_if_stated is None
    assert notification.publishes_weightage is False

    scored = TenderNotification(
        tender_id="T-2",
        title="IT services",
        evaluation_criteria=[
            EvaluationCriterion(factor="Technical", weightage_if_stated=70),
            EvaluationCriterion(factor="Financial", weightage_if_stated=30),
        ],
    )
    assert scored.publishes_weightage is True


def test_eliminated_vendor_must_carry_a_reason() -> None:
    """Section 5.2: elimination has to be defensible if challenged."""
    with pytest.raises(ValidationError, match="requires an elimination_reason"):
        VendorSubmission(
            vendor_id="V-01", vendor_name="Acme Infra", status=VendorStatus.ELIMINATED
        )


def test_reason_without_elimination_is_rejected() -> None:
    with pytest.raises(ValidationError, match="non-eliminated vendor"):
        VendorSubmission(
            vendor_id="V-02",
            vendor_name="Beta Ltd",
            status=VendorStatus.PENDING,
            elimination_reason="Turnover too low",
        )


def test_vendor_defaults_to_pending_not_passed() -> None:
    """Section 5.2 -- there is deliberately no 'passed' state."""
    vendor = VendorSubmission(vendor_id="V-03", vendor_name="Gamma Works")
    assert vendor.status is VendorStatus.PENDING
    assert vendor.is_blacklisted is False
    assert {s.value for s in VendorStatus} == {"eliminated", "pending", "shortlisted"}


def test_latest_turnover_ignores_unresolved_amounts() -> None:
    vendor = VendorSubmission(
        vendor_id="V-04",
        vendor_name="Delta Systems",
        turnover=[
            YearlyTurnover(year=2022, amount=MoneyAmount(raw_text="3.1 Cr")),
            YearlyTurnover(year=2023, amount=MoneyAmount(raw_text="4.2 Cr")),
            YearlyTurnover(year=2024, amount=MoneyAmount(raw_text="see annexure")),
        ],
    )
    latest = vendor.latest_turnover()
    assert latest.year == 2023
    assert latest.amount.amount_inr == Decimal("42000000.00")


def test_certification_expiry_unknown_is_not_valid_true() -> None:
    """Section 9.2.2 lists 'document present but expired' as a borderline case;
    unknown expiry must be tri-state, not silently valid."""
    assert Certification(name="ISO 9001", doc_present=True).is_valid_on(date(2026, 1, 1)) is None
    assert (
        Certification(name="ISO 9001", doc_present=True, valid_till=date(2025, 1, 1))
        .is_valid_on(date(2026, 1, 1))
        is False
    )
    assert Certification(name="ISO 9001", doc_present=False).is_valid_on(date(2026, 1, 1)) is False


def test_provenance_defaults_and_citation_fields() -> None:
    doc = MandatoryDocument(
        doc_name="GST Registration Certificate",
        aliases=["Goods & Services Tax Certificate"],
        provenance={"clause_ref": "4.2", "source_page": 14, "source_snippet": "..."},
    )
    assert doc.provenance.clause_ref == "4.2"
    assert doc.provenance.source_page == 14
    assert MandatoryDocument(doc_name="EMD proof").provenance.clause_ref is None


def test_corrigendum_diff_shape() -> None:
    corr = Corrigendum(
        corrigendum_id="C-1",
        parent_tender_id="T-1",
        issued_date=date(2026, 3, 1),
        changed_fields=[
            ChangedField(
                field_path="submission_deadline",
                old_value="2026-03-15",
                new_value="2026-03-29",
                provenance={"clause_ref": "1"},
            )
        ],
    )
    assert corr.changed_fields[0].field_path == "submission_deadline"


def test_extra_keys_are_rejected() -> None:
    """extra='forbid' means a hallucinated field from the extractor fails loudly."""
    with pytest.raises(ValidationError):
        MandatoryDocument(doc_name="EMD proof", confidence_note="probably")
