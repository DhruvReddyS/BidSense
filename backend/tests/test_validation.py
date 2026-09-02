"""Post-extraction plausibility checks (Stage 4.10).

The failure this guards against is the one that does not raise. Every extractor
returned, no error was recorded, the job said SUCCEEDED -- and the notification
had no deadline, no EMD and no issuing authority.

That is not hypothetical. The same 101-page tender through two models:

    field               gemini-3.5-flash                qwen3:4b
    issuing_authority   IIT (ISM) Dhanbad               (empty)
    submission_deadline 2026-08-22                      None
    emd_amount          Rs. 31,500/-                    None
    errors reported     0                               0

`test_the_measured_ollama_degradation_is_caught` replays exactly that output.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.extraction.validate import (
    Finding,
    Severity,
    affects_confidence,
    summarise,
    validate_notification,
    validate_submission,
)
from app.ingest.models import PageText, ParsedDocument
from app.schemas.common import (
    CriterionType,
    DocumentKind,
    MoneyAmount,
    Provenance,
    YearlyTurnover,
)
from app.schemas.notification import (
    EligibilityCriterion,
    MandatoryDocument,
    TenderNotification,
)
from app.schemas.submission import SubmittedDocument, VendorSubmission

TODAY = date(2026, 6, 1)


def _prov(page: int | None = 2) -> Provenance:
    return Provenance(clause_ref="4.2", source_page=page, source_snippet="x")


def _healthy() -> TenderNotification:
    return TenderNotification(
        tender_id="T-1",
        title="Boundary wall",
        issuing_authority="IIT (ISM) Dhanbad",
        submission_deadline=date(2026, 8, 22),
        pre_bid_query_deadline=date(2026, 8, 19),
        emd_amount=MoneyAmount(raw_text="Rs. 31,500/-"),
        contract_value_estimate=MoneyAmount(raw_text="Rs. 12,56,561/-"),
        eligibility_criteria=[
            EligibilityCriterion(
                criterion="Turnover",
                type=CriterionType.NUMERIC,
                threshold_raw="Rs. 5 Cr",
                threshold_amount=MoneyAmount(raw_text="Rs. 5 Cr"),
                provenance=_prov(),
            )
        ],
        mandatory_documents=[
            MandatoryDocument(doc_name="PAN Card", provenance=_prov())
        ],
    )


def _document(pages: int = 10) -> ParsedDocument:
    return ParsedDocument(
        file_name="n.pdf",
        doc_kind=DocumentKind.NOTIFICATION,
        pages=[PageText(page_number=i, text="x" * 50) for i in range(1, pages + 1)],
    )


# --------------------------------------------------------------------------- #
# A good extraction is quiet
# --------------------------------------------------------------------------- #
def test_a_clean_extraction_produces_no_findings() -> None:
    """The property that makes the flag worth anything. A validator that fires
    on healthy output trains everyone to ignore it."""
    findings = validate_notification(_healthy(), _document(), today=TODAY)
    assert findings == [], [str(f) for f in findings]
    assert summarise(findings) is None


# --------------------------------------------------------------------------- #
# The measured regression
# --------------------------------------------------------------------------- #
def test_the_measured_ollama_degradation_is_caught() -> None:
    """Replays the real qwen3:4b output for NOTIF_civilworks_01, which reported
    zero errors and would otherwise have been presented as a clean run."""
    degraded = TenderNotification(
        tender_id="CMU-12011/17/2026-CMU",
        title="Notice Inviting eTender",
        issuing_authority=None,
        submission_deadline=None,
        emd_amount=None,
        contract_value_estimate=MoneyAmount(raw_text="Rs. 12,56,561/-"),
    )
    findings = validate_notification(degraded, today=TODAY)
    flagged = {f.field for f in findings}

    assert {"submission_deadline", "issuing_authority", "emd_amount"} <= flagged
    assert affects_confidence(findings)
    assert "may have been missed" in summarise(findings)


# --------------------------------------------------------------------------- #
# Implausible values
# --------------------------------------------------------------------------- #
def test_a_zero_amount_is_an_error_not_a_number() -> None:
    notification = _healthy()
    notification.emd_amount = MoneyAmount(raw_text="0")
    findings = validate_notification(notification, today=TODAY)
    finding = next(f for f in findings if f.field == "emd_amount")
    assert finding.severity is Severity.ERROR


def test_a_zero_threshold_is_flagged_because_it_passes_everybody() -> None:
    notification = _healthy()
    notification.eligibility_criteria[0].threshold_amount = MoneyAmount(raw_text="0")
    findings = validate_notification(notification, today=TODAY)
    assert any(
        f.field.startswith("eligibility_criteria[0]") and f.severity is Severity.ERROR
        for f in findings
    )


def test_an_emd_larger_than_the_whole_contract_is_an_error() -> None:
    notification = _healthy()
    notification.emd_amount = MoneyAmount(raw_text="Rs. 50 Cr")
    findings = validate_notification(notification, today=TODAY)
    finding = next(f for f in findings if f.field == "emd_amount")
    assert finding.severity is Severity.ERROR
    assert "magnitude" in finding.message


def test_pre_bid_queries_closing_after_bids_are_due_is_impossible() -> None:
    notification = _healthy()
    notification.pre_bid_query_deadline = date(2026, 9, 30)
    findings = validate_notification(notification, today=TODAY)
    finding = next(f for f in findings if f.field == "pre_bid_query_deadline")
    assert finding.severity is Severity.ERROR


# --------------------------------------------------------------------------- #
# Citations that cannot be checked
# --------------------------------------------------------------------------- #
def test_a_citation_beyond_the_last_page_is_an_error() -> None:
    """The citation is the entire basis for believing an extracted value. One
    pointing at page 400 of a 10-page document cannot be checked, and reliably
    means the anchor was invented rather than read."""
    notification = _healthy()
    notification.mandatory_documents[0].provenance = _prov(page=400)
    findings = validate_notification(notification, _document(pages=10), today=TODAY)
    finding = next(f for f in findings if "mandatory_documents" in f.field)
    assert finding.severity is Severity.ERROR
    assert "400" in finding.message and "10 pages" in finding.message


def test_page_checks_are_skipped_when_the_document_is_not_available() -> None:
    """Validation runs at gap-report time too, where the parsed document is long
    gone. It must not invent a failure from an absence of evidence."""
    notification = _healthy()
    notification.mandatory_documents[0].provenance = _prov(page=400)
    assert validate_notification(notification, None, today=TODAY) == []


# --------------------------------------------------------------------------- #
# Facts about the tender vs doubts about the extraction
# --------------------------------------------------------------------------- #
def test_a_past_deadline_is_reported_but_does_not_impugn_the_extraction() -> None:
    """An expired tender is a real thing, correctly read. Downgrading that run
    to "partial" would train everyone to ignore the flag."""
    notification = _healthy()
    findings = validate_notification(notification, today=date(2027, 1, 1))
    finding = next(f for f in findings if f.field == "submission_deadline")
    assert finding.affects_confidence is False
    assert not affects_confidence(findings)
    assert summarise(findings) is None, "a closed tender is not an extraction problem"


def test_a_missing_deadline_does_impugn_the_extraction() -> None:
    """The other side of the same distinction."""
    notification = _healthy()
    notification.submission_deadline = None
    findings = validate_notification(notification, today=TODAY)
    finding = next(f for f in findings if f.field == "submission_deadline")
    assert finding.affects_confidence is True
    assert affects_confidence(findings)


# --------------------------------------------------------------------------- #
# Bids
# --------------------------------------------------------------------------- #
def _bid(**kwargs) -> VendorSubmission:
    kwargs.setdefault("vendor_id", "V-1")
    kwargs.setdefault("vendor_name", "V Ltd")
    kwargs.setdefault("tender_id", "T-1")
    kwargs.setdefault(
        "turnover",
        [
            YearlyTurnover(
                year=2024, amount=MoneyAmount(raw_text="Rs. 5 Cr"), provenance=_prov()
            )
        ],
    )
    kwargs.setdefault(
        "documents_submitted",
        [SubmittedDocument(doc_name="PAN Card", present=True, provenance=_prov())],
    )
    return VendorSubmission(**kwargs)


def test_a_clean_bid_produces_no_findings() -> None:
    assert validate_submission(_bid(), _document()) == []


def test_a_zero_turnover_is_flagged_because_it_eliminates_the_bidder() -> None:
    bid = _bid(
        turnover=[
            YearlyTurnover(
                year=2024, amount=MoneyAmount(raw_text="0"), provenance=_prov()
            )
        ]
    )
    finding = next(f for f in validate_submission(bid) if f.field.startswith("turnover["))
    assert finding.severity is Severity.ERROR
    assert "eliminates a bidder" in finding.message


def test_an_absent_enclosure_list_is_flagged_before_it_fails_every_document() -> None:
    bid = _bid(documents_submitted=[])
    finding = next(f for f in validate_submission(bid) if f.field == "documents_submitted")
    assert "report as missing" in finding.message


def test_an_implausible_age_is_a_misread_year() -> None:
    bid = _bid(years_in_business=400)
    assert any(f.field == "years_in_business" for f in validate_submission(bid))


def test_a_negative_age_cannot_reach_the_validator_at_all() -> None:
    """The stronger guarantee, worth pinning separately.

    `years_in_business` carries `ge=0` on the schema, so a negative value is
    rejected at construction and never reaches validation at all. That is
    better than flagging it, and this test is what notices if the constraint is
    ever relaxed -- at which point the validator's own bound takes over.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _bid(years_in_business=-3)


def test_a_negative_net_worth_is_allowed_but_a_negative_price_is_not() -> None:
    """Net worth can genuinely be negative -- that is what an insolvent bidder
    looks like, and flagging it as an extraction fault would hide a real signal."""
    bid = _bid(net_worth=MoneyAmount(raw_text="-5000000"))
    assert not any(f.field == "net_worth" for f in validate_submission(bid))

    bid = _bid(quoted_price=MoneyAmount(raw_text="0"))
    assert any(f.field == "quoted_price" for f in validate_submission(bid))


# --------------------------------------------------------------------------- #
# Nothing is silently corrected
# --------------------------------------------------------------------------- #
def test_validation_never_changes_a_value() -> None:
    """A validator that quietly fixed what it disliked would be a second,
    unauditable extractor."""
    notification = _healthy()
    notification.emd_amount = MoneyAmount(raw_text="0")
    before = notification.model_dump_json()
    validate_notification(notification, _document(), today=TODAY)
    assert notification.model_dump_json() == before


def test_a_partial_run_is_still_stored_and_readable() -> None:
    """`ok` stays True for a run with findings. The rows landed and are worth
    reading; what changes is that they are no longer presented as unqualified."""
    from app.extraction.pipeline import IngestReport

    report = IngestReport(file_name="n.pdf", doc_kind=DocumentKind.NOTIFICATION)
    report.row_id = "not-none"
    report.validation = [
        Finding(field="emd_amount", severity=Severity.WARNING, message="missing")
    ]
    assert report.ok is True
    assert report.needs_review is True
    assert report.validation_summary is not None
