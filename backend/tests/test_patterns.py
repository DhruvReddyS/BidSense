"""The deterministic header backstop (Stage: extraction hardening, item 3).

Every extraction failure measured across four local models clustered on the same
three fields -- issuing authority, submission deadline, EMD -- which are also the
three with the most regular printed form. That combination is what makes a
pattern extractor worth having: it is not trying to understand the tender, only
to locate a value whose label is one of a dozen known phrasings.

It is a CROSS-CHECK. The tests below spend as much effort on what it must NOT do
-- override the model, claim a percentage EMD, name a bank as the issuer -- as on
what it finds, because a backstop that is wrong confidently is worse than none.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.extraction.patterns import find_header_candidates
from app.ingest.models import PageText, ParsedDocument
from app.schemas.common import DocumentKind

DATA = Path(__file__).resolve().parents[2] / "data" / "notifications"
real = pytest.mark.skipif(not DATA.exists(), reason="no collected notifications")


def _doc(*pages: str) -> ParsedDocument:
    return ParsedDocument(
        file_name="n.pdf",
        doc_kind=DocumentKind.NOTIFICATION,
        pages=[PageText(page_number=i, text=t) for i, t in enumerate(pages, start=1)],
    )


# --------------------------------------------------------------------------- #
# What it finds
# --------------------------------------------------------------------------- #
def test_a_key_dates_table_yields_both_deadlines_and_the_emd() -> None:
    document = _doc(
        "INDIAN INSTITUTE OF TECHNOLOGY DHANBAD\nNotice Inviting eTender\n",
        "Estimated Cost                              Rs. 12,56,561/-\n"
        "EMD                                         Rs. 31,500/-\n"
        "Last Date and Time for receipt of Queries   19 August 2026 (11:00 Hours)\n"
        "Last Date and Time for uploading of Bids    22 August 2026 (18:30 Hours)\n",
    )
    hits = find_header_candidates(document)
    assert hits["submission_deadline"].value == "22 August 2026"
    assert hits["pre_bid_query_deadline"].value == "19 August 2026"
    assert hits["emd_amount"].value == "Rs. 31,500/-"
    assert hits["submission_deadline"].page == 2


def test_a_two_column_table_that_flattened_across_lines_still_resolves() -> None:
    """PDF extraction routinely splits a label and its value onto separate
    lines. A same-line-only rule finds nothing on a real tender."""
    document = _doc(
        "OFFICE OF THE EXECUTIVE ENGINEER, PWD\n",
        "Bid submission end date\n14.02.2026 upto 15:00 hrs\n",
    )
    assert find_header_candidates(document)["submission_deadline"].value == "14.02.2026"


@pytest.mark.parametrize(
    "line",
    [
        "HYDERABAD GROWTH CORRIDOR LIMITED",
        "Greater Hyderabad Municipal Corporation",
        "Indian Institute of Technology (Indian School of Mines) Dhanbad",
        "Office of the Superintending Engineer, Public Works Division",
        "Government of Telangana",
    ],
)
def test_a_letterhead_line_is_recognised_wherever_the_institutional_word_sits(line) -> None:
    """A positional rule anchored on capital-then-noun misses both real shapes:
    the noun starts the first name, and the second's noun is "corridor limited",
    which no sensible whitelist contains."""
    hits = find_header_candidates(_doc(f"{line}\nSome address, 500104\n"))
    assert hits["issuing_authority"].value == line


# --------------------------------------------------------------------------- #
# What it must NOT do
# --------------------------------------------------------------------------- #
def test_the_emd_submission_date_is_not_read_as_the_bid_deadline() -> None:
    """Real tenders carry both, adjacently. A looser "last date" rule takes the
    first one it meets, which is a deadline three days later than the truth."""
    document = _doc(
        "AUTHORITY LIMITED\n",
        "Last Date for submission of EMD              24 August 2026 (16:00 Hours)\n"
        "Last Date and Time for uploading of Bids     22 August 2026 (18:30 Hours)\n",
    )
    assert find_header_candidates(document)["submission_deadline"].value == "22 August 2026"


def test_a_percentage_emd_is_left_alone_rather_than_read_as_rupees() -> None:
    """"EMD @ 1% of the ECV" resolves to Rs. 1 if treated as an amount -- the
    same defect the money normaliser already guards. Silence is the right answer;
    resolving it needs the contract value, which is code's job elsewhere."""
    document = _doc("AUTHORITY LIMITED\n", "EMD  1% of the estimated contract value\n")
    assert "emd_amount" not in find_header_candidates(document)


def test_a_bank_named_in_the_emd_clause_is_not_taken_as_the_issuer() -> None:
    """A tender names dozens of organisations. The one that ISSUED it is in the
    letterhead, which is why the search is restricted to the head of page 1."""
    document = _doc(
        "GREATER HYDERABAD MUNICIPAL CORPORATION\nTank Bund Road, Hyderabad\n",
        "The EMD shall be furnished by way of a Bank Guarantee from the "
        "State Bank of India Limited or any scheduled commercial bank.\n",
    )
    found = find_header_candidates(document)["issuing_authority"].value
    assert "greater hyderabad" in found.lower()
    assert "state bank" not in found.lower()


def test_a_contents_page_line_is_not_mistaken_for_a_value() -> None:
    document = _doc(
        "AUTHORITY LIMITED\n",
        "Last Date and Time for uploading of Bids ................. 14\n",
    )
    assert "submission_deadline" not in find_header_candidates(document)


def test_the_work_title_is_not_taken_as_the_issuing_authority() -> None:
    document = _doc(
        "NAME OF THE WORK: Construction of the municipal corporation office\n"
        "HYDERABAD GROWTH CORRIDOR LIMITED\n"
    )
    assert find_header_candidates(document)["issuing_authority"].value == (
        "HYDERABAD GROWTH CORRIDOR LIMITED"
    )


def test_a_bare_year_on_the_line_is_not_read_as_an_amount() -> None:
    document = _doc("AUTHORITY LIMITED\n", "EMD applicable for the year 2026 as notified\n")
    assert "emd_amount" not in find_header_candidates(document)


def test_only_the_pages_the_model_saw_are_searched() -> None:
    """Otherwise the backstop reports "the regex found it and you didn't" for
    text that was never in front of the model."""
    document = _doc(
        "AUTHORITY LIMITED\n",
        "EMD   Rs. 31,500/-\n",
    )
    assert "emd_amount" in find_header_candidates(document, pages=[1, 2])
    assert "emd_amount" not in find_header_candidates(document, pages=[1])


# --------------------------------------------------------------------------- #
# Against the real corpus
# --------------------------------------------------------------------------- #
@real
@pytest.mark.parametrize(
    "stem, field, expected",
    [
        ("NOTIF_civilworks_01", "issuing_authority", "Indian Institute of Technology"),
        ("NOTIF_civilworks_01", "submission_deadline", "22 August 2026"),
        ("NOTIF_civilworks_01", "pre_bid_query_deadline", "19 August 2026"),
        ("NOTIF_civilworks_01", "emd_amount", "31,500"),
        ("NOTIF_supply_01", "issuing_authority", "GREATER HYDERABAD MUNICIPAL CORPORATION"),
        ("NOTIF_supply_01", "emd_amount", "2,98,720"),
        ("NOTIF_civilworks_02", "issuing_authority", "HYDERABAD GROWTH CORRIDOR LIMITED"),
    ],
)
def test_the_real_tenders_resolve(stem, field, expected) -> None:
    from app.extraction.selection import select_pages
    from app.ingest import parse_document

    path = DATA / f"{stem}.pdf"
    if not path.exists():
        pytest.skip(f"{stem} not collected")
    document = parse_document(path, DocumentKind.NOTIFICATION)
    _, pages = select_pages(document, "header")
    hit = find_header_candidates(document, pages).get(field)
    assert hit is not None, f"{field} not located in {stem}"
    assert expected.lower() in hit.value.lower(), f"got {hit.value!r}"


# --------------------------------------------------------------------------- #
# It only speaks into silence
# --------------------------------------------------------------------------- #
def test_the_backstop_never_overrides_a_value_the_model_returned() -> None:
    """A pattern that disagrees with an extracted value is not automatically
    right. Overriding on that basis would be a second unauditable extractor."""
    from datetime import date

    from app.extraction.validate import validate_notification
    from app.schemas.common import MoneyAmount
    from app.schemas.notification import TenderNotification

    document = _doc("AUTHORITY LIMITED\n", "EMD   Rs. 31,500/-\n")
    # The model said something different from what the pattern would find.
    notification = TenderNotification(
        tender_id="T-1", title="t", issuing_authority="Authority Limited",
        submission_deadline=date(2026, 8, 22),
        emd_amount=MoneyAmount(raw_text="Rs. 99,999/-"),
    )
    findings = validate_notification(notification, document, today=date(2026, 1, 1))
    assert not any(f.field == "emd_amount" for f in findings), (
        "the backstop contradicted a value the model actually returned"
    )


def test_a_located_value_is_reported_as_an_error_not_a_maybe() -> None:
    """"We could not find a deadline" and "the deadline is on page 5 and we
    missed it" are different claims, and only the second is actionable."""
    from datetime import date

    from app.extraction.validate import Severity, validate_notification
    from app.schemas.notification import TenderNotification

    document = _doc(
        "AUTHORITY LIMITED\n",
        "Last Date and Time for uploading of Bids   22 August 2026\nEMD  Rs. 31,500/-\n",
    )
    notification = TenderNotification(tender_id="T-1", title="t", issuing_authority="A Ltd")
    findings = {f.field: f for f in validate_notification(notification, document,
                                                         today=date(2026, 1, 1))}
    assert findings["submission_deadline"].severity is Severity.ERROR
    assert "page 2" in findings["submission_deadline"].message
    assert "22 August 2026" in findings["submission_deadline"].message
