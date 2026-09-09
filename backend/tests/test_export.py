"""Gap report export to PDF and DOCX (Section 4.6).

The people who attach the documents are usually not the person who ran the
check. What matters is therefore not that a file is produced, but that nothing
load-bearing is lost on the way out: the clause references, the four-way
verdict, the "this is a count not a score" caveat, and the data-quality banner.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date

import pytest

from app.compliance.export import ExportContext, _pdf_text, export_docx, export_pdf
from app.compliance.gap import build_gap_report
from app.schemas.common import CriterionType, MoneyAmount, Provenance, YearlyTurnover
from app.schemas.notification import (
    EligibilityCriterion,
    MandatoryDocument,
    TenderNotification,
)
from app.schemas.submission import SubmittedDocument, VendorSubmission


def _prov(clause="4.2", page=7) -> Provenance:
    return Provenance(clause_ref=clause, source_page=page, source_snippet="x")


def _report():
    notification = TenderNotification(
        tender_id="CMU-12011/17/2026-CMU",
        title="Construction of boundary wall",
        issuing_authority="IIT (ISM) Dhanbad",
        submission_deadline=date(2026, 8, 22),
        mandatory_documents=[
            MandatoryDocument(doc_name="GST Registration Certificate", provenance=_prov("7", 12)),
            MandatoryDocument(doc_name="PAN Card", provenance=_prov("8", 12)),
        ],
        eligibility_criteria=[
            EligibilityCriterion(
                criterion="Average annual turnover",
                type=CriterionType.NUMERIC,
                threshold_raw="Rs. 5 Cr",
                threshold_amount=MoneyAmount(raw_text="Rs. 5 Cr"),
                unit="INR",
                provenance=_prov("1", 67),
            )
        ],
    )
    submission = VendorSubmission(
        vendor_id="V-1", vendor_name="Damodar Valley Builders", tender_id=notification.tender_id,
        turnover=[YearlyTurnover(year=2024, amount=MoneyAmount(raw_text="Rs. 3.2 Cr"),
                                 provenance=_prov("2", 4))],
        documents_submitted=[
            SubmittedDocument(doc_name="PAN Card", present=True, provenance=_prov("3", 5))
        ],
    )
    return build_gap_report(notification, submission)


def _flat(text: str) -> str:
    """Collapse whitespace.

    Both formats wrap: a PDF breaks a sentence across lines and DOCX splits a
    run across elements, so asserting on raw output tests the line width rather
    than the content.
    """
    return " ".join(text.split())


def _docx_text(payload: bytes) -> str:
    """The document's visible text, not its XML -- an assertion against raw XML
    fails on entity escaping rather than on missing content."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    return _flat(" ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml)))


def _pdf_strings(payload: bytes) -> str:
    """Text out of the produced PDF, read back rather than assumed."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(payload))
    return _flat("\n".join(page.extract_text() or "" for page in reader.pages))


# --------------------------------------------------------------------------- #
# Both formats carry the same load-bearing content
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def rendered():
    report = _report()
    context = ExportContext(
        tender_title="Construction of boundary wall",
        issuing_authority="IIT (ISM) Dhanbad",
        submission_deadline=date(2026, 8, 22),
        data_quality_banner="This extraction needs review: 2 fields may have been missed.",
        staleness_banner="This tender was updated on 12 August 2026 — recheck your compliance.",
    )
    return {
        "pdf": _pdf_strings(export_pdf(report, context)),
        "docx": _docx_text(export_docx(report, context)),
        "report": report,
    }


@pytest.mark.parametrize("fmt", ["pdf", "docx"])
def test_the_verdict_survives_the_export(rendered, fmt) -> None:
    """Flattening the four-way verdict to pass/fail on the way out would undo
    the whole reason it is four-way."""
    assert "Blocking issues found" in rendered[fmt]


@pytest.mark.parametrize("fmt", ["pdf", "docx"])
def test_the_completion_count_travels_with_its_caveat(rendered, fmt) -> None:
    """The number without the sentence reads as a score, which Section 4.4
    forbids inventing."""
    text = rendered[fmt]
    assert "mandatory requirements satisfied" in text
    assert "not a score" in text


@pytest.mark.parametrize("fmt", ["pdf", "docx"])
def test_clause_references_survive(rendered, fmt) -> None:
    """A to-do without its clause cannot be checked against the tender by
    whoever receives it."""
    assert "clause" in rendered[fmt].lower()


@pytest.mark.parametrize("fmt", ["pdf", "docx"])
def test_the_blocking_item_and_its_figures_survive(rendered, fmt) -> None:
    text = rendered[fmt]
    assert "3.2 Cr" in text
    assert "5 Cr" in text
    assert "do not currently qualify" in text


@pytest.mark.parametrize("fmt", ["pdf", "docx"])
def test_both_banners_survive(rendered, fmt) -> None:
    text = rendered[fmt]
    assert "recheck your compliance" in text
    assert "needs review" in text


@pytest.mark.parametrize("fmt", ["pdf", "docx"])
def test_the_missing_document_appears_as_a_to_do(rendered, fmt) -> None:
    assert "GST Registration Certificate" in rendered[fmt]


@pytest.mark.parametrize("fmt", ["pdf", "docx"])
def test_the_human_review_caveat_survives(rendered, fmt) -> None:
    """No bid is ever reported as fully clear, and the exported file has to say
    so too -- it will be read by people who never saw the app."""
    assert "no bid is ever reported as fully clear" in rendered[fmt]


def test_the_two_formats_agree_on_the_verdict(rendered) -> None:
    """A vendor choosing DOCX must not get a different answer from one choosing
    PDF. Both render from the same GapReport through the same `_sections`."""
    for phrase in ("Blocking issues found", "mandatory requirements satisfied", "not a score"):
        assert phrase in rendered["pdf"] and phrase in rendered["docx"]


# --------------------------------------------------------------------------- #
# The rupee glyph
# --------------------------------------------------------------------------- #
def test_the_pdf_preserves_the_rupee_sign() -> None:
    text = _pdf_strings(export_pdf(_report()))
    assert "₹3.2 Cr" in text
    assert "₹5 Cr" in text


@pytest.mark.parametrize("source", ["₹3.2 Cr", "a — b", "“quoted”", "22 August"])
def test_unicode_characters_are_preserved(source) -> None:
    assert _pdf_text(source) == source


def test_the_docx_keeps_the_rupee_sign() -> None:
    """DOCX must preserve the same original currency character as PDF."""
    assert "\u20b9" in _docx_text(export_docx(_report()))


# --------------------------------------------------------------------------- #
# Shape
# --------------------------------------------------------------------------- #
def test_both_formats_produce_a_valid_file() -> None:
    report = _report()
    pdf = export_pdf(report)
    docx = export_docx(report)
    assert pdf[:5] == b"%PDF-"
    assert zipfile.ZipFile(io.BytesIO(docx)).testzip() is None
    assert len(pdf) > 3000 and len(docx) > 3000


def test_a_report_that_checked_nothing_exports_without_pretending() -> None:
    """`not_checked` is a real verdict and must not be exported as a pass."""
    empty = build_gap_report(
        TenderNotification(tender_id="T-1", title="t", issuing_authority="a"),
        VendorSubmission(vendor_id="V-1", vendor_name="V", tender_id="T-1"),
    )
    text = _pdf_strings(export_pdf(empty))
    assert "Nothing could be checked" in text
    assert "0 of 0" in text
