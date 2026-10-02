"""Regression suite: one named test per defect this system has actually shipped.

Every entry in `DEFECTS` below was a real bug that reached a run and produced a
wrong answer -- not a hypothetical. Each is pinned here by a test named after
its id, so a reintroduction fails a test whose name says what broke.

Two properties make a silent return structurally impossible rather than merely
unlikely:

  * `test_every_known_defect_is_pinned` walks this module and asserts that every
    id in `DEFECTS` has at least one test function carrying it. Deleting or
    renaming a regression test fails the suite instead of quietly shrinking it.
  * Where the fix is a *structural* property rather than a behaviour -- a route
    declared before another, an HTTP client constructed with a timeout, a purge
    filter scoped to one id -- the test asserts the structure directly. A
    behavioural test alone can pass against a rewritten implementation that has
    lost the guard.

Several of these defects are also covered incidentally by the topic suites
(`test_money.py`, `test_compliance.py`, ...). The duplication is deliberate:
those tests exist to describe how a feature works and may legitimately be
rewritten when it changes, whereas these exist to say "this specific wrong
answer was given to a user once, and must not be given again".
"""

from __future__ import annotations

import inspect
import re
import sys
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.compliance.gap import build_gap_report
from app.compliance.models import CheckStatus, Severity
from app.config import settings
from app.db.session import engine, session_scope
from app.normalize.money import (
    MoneyParseError,
    normalize_amount,
    try_normalize_amount,
)
from app.schemas.common import (
    CriterionType,
    DocumentKind,
    Provenance,
)
from app.schemas.notification import (
    EligibilityCriterion,
    MandatoryDocument,
    TenderNotification,
)
from app.schemas.submission import VendorSubmission
from app.vector.qdrant import build_filter, collection_stats, get_client
from tests.doc_factory import NOTIFICATION_TRUTH, make_notification_pdf
from tests.stub_llm import StubLLM

# --------------------------------------------------------------------------- #
# The register. Adding a defect here without pinning it fails the meta-test.
# --------------------------------------------------------------------------- #
DEFECTS: dict[str, str] = {
    "d1_unit_vs_quantity": (
        "A capacity requirement ('13 MW cumulative') was compared against the "
        "NUMBER of past projects, eliminating a bidder who cited two 13 MW "
        "plants for having 'only 2'."
    ),
    "d2_comma_tolerant_numbers": (
        "Real tenders print 'Rs.3, 00, 00,000/-' with spaces after the commas. "
        "The number regex stopped at '3', turning a Rs. 3 crore turnover floor "
        "into Rs. 3 -- which every bidder on earth clears."
    ),
    "d3_contents_page_not_enclosures": (
        "The bid's own table of contents was read as its enclosure list, so a "
        "vendor who listed 'Section 16 - Checklist of documents' scored as "
        "having enclosed every document named in the contents."
    ),
    "d4_empty_extraction_is_not_compliant": (
        "A run that extracted no requirements produced an empty gap report, "
        "which fell through to 'compliant' and told the vendor they had no "
        "blocking issues. Silence is not a pass."
    ),
    "d5_reextraction_does_not_cascade_delete": (
        "Re-extracting a notification deleted and recreated its row. "
        "vendor_submissions cascades from it, so every bid filed against that "
        "tender was destroyed by re-running an extraction."
    ),
    "d6_percentage_is_not_an_amount": (
        "'turnover of 30% of the estimated cost' normalised to Rs. 30. Read as "
        "an absolute threshold every bidder clears it, so the criterion "
        "silently stopped eliminating anyone."
    ),
    "d7_llm_calls_are_bounded": (
        "A Gemini call with no timeout sat at 0% CPU for five hours holding a "
        "worker from a two-worker pool; two of them deadlocked the queue."
    ),
    "d8_chunk_purge_is_scoped_to_one_submission": (
        "Re-indexing a bid purged by vendor_id. For a bid with no tender link "
        "build_filter omits the None tender_id rather than narrowing on it, so "
        "the purge deleted that vendor's chunks across every tender they had "
        "bid on."
    ),
    "d10_unreadable_factor_is_not_worst_value": (
        "Level 2 min-max normalisation mapped a missing factor to 0.0, so a "
        "vendor whose quoted price the extractor could not read scored "
        "identically to the vendor who quoted the WORST price in the pool, and "
        "was dropped from the shortlist for our own extraction failure. The "
        "vendor-side report says in as many words that unreadable is not "
        "failing; the shortlist contradicted it."
    ),
    "d11_outlier_does_not_flatten_the_pool": (
        "Min-max normalisation let one extreme bid compress the rest: project "
        "values [50, 60, 70, 5000] normalised to [0.0, 0.002, 0.004, 1.0], "
        "erasing the distinction between the three ordinary vendors that the "
        "shortlist reduction exists to draw."
    ),
    "d12_shortlist_ties_are_not_broken_arbitrarily": (
        "Candidates tied at the cut-off were separated by vendor_id sort order, "
        "so of two equally-scored vendors the one whose id sorted later was "
        "excluded from a procurement shortlist for no stated reason."
    ),
    "d13_table_rows_are_chunked_individually": (
        "Tables were appended to page prose and split by size, so a seven-row "
        "date grid became ONE 1,208-character chunk whose embedding stood for "
        "seven different dates. Asked 'By when must I upload my bid?' the "
        "system ranked that chunk 11th of 212, behind prose that discussed "
        "uploading and contained no date. Measured hit@5 was 29.4% and "
        "precision@1 was 5.9%, with misses clustered on EMD, deadlines and "
        "conditions -- the fields that live in tables."
    ),
    "d9_slashed_tender_ids_route_correctly": (
        "Real tender ids contain slashes ('TENDER No.01/SE(Electrical)/GHMC/"
        "2024-25'). The greedy {tender_id:path} route, declared first, swallowed "
        "the '/submissions' suffix into the id and 404'd."
    ),
}


def _services_up() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return bool(collection_stats().get("exists"))
    except Exception:
        return False


def _embeddings_available() -> bool:
    try:
        from app.vector.embeddings import get_model

        get_model()
        return True
    except Exception:
        return False


live = pytest.mark.skipif(not _services_up(), reason="postgres/qdrant not running")
embed = pytest.mark.skipif(not _embeddings_available(), reason="BGE model unavailable")

TENDER_ID = NOTIFICATION_TRUTH["tender_id"]


def _prov(clause: str = "1") -> Provenance:
    return Provenance(clause_ref=clause, source_page=1, source_snippet="x")


# --------------------------------------------------------------------------- #
# The meta-test. This is what makes the register binding.
# --------------------------------------------------------------------------- #
def _vendor_row(vendor_id, *, years=0, project=None, price=None, technical=False):
    """A Level 2 candidate row, shaped as the ORM row the scorer reads."""
    from types import SimpleNamespace

    projects = [] if project is None else [SimpleNamespace(value_inr=Decimal(project))]
    return SimpleNamespace(
        vendor_id=vendor_id,
        vendor_name=f"Vendor {vendor_id}",
        years_in_business=years,
        past_projects=projects,
        quoted_price_inr=Decimal(price) if price is not None else None,
        has_technical_approach=technical,
    )


def test_d10_unreadable_factor_is_not_worst_value() -> None:
    """A factor the extractor could not read must not score as the worst one.

    The scenario is the one that actually matters in procurement: a strong
    bidder whose quoted price we failed to parse. Under the old min-max pass
    that vendor scored 0.0 on pricing -- indistinguishable from the most
    expensive bid in the pool -- and lost a shortlist place to a weak but
    fully-parsed competitor.
    """
    from app.review.workflow import _normalise, build_candidate, score_candidates

    # The normaliser must preserve the gap rather than fill it with a zero.
    assert _normalise([100, 10, None]) == [1.0, 0.0, None]

    strong = build_candidate(
        _vendor_row("strong", years=20, project="900000000", price=None, technical=True)
    )
    weak = build_candidate(
        _vendor_row("weak", years=1, project="1000", price="50", technical=False)
    )
    weights = {k: 1.0 for k in ("experience", "project_scale", "pricing", "technical_approach")}
    by_id = {e.candidate.vendor_id: e for e in score_candidates([strong, weak], weights)}

    # Scored on what it has, not punished for what we could not read.
    assert by_id["strong"].unscored == ("pricing",)
    assert by_id["strong"].scored_on == ("experience", "project_scale", "technical_approach")
    assert by_id["strong"].score > by_id["weak"].score
    # And the reviewer is told the basis, rather than shown a bare number.
    assert "3 of 4" in by_id["strong"].basis

    # The same error one level up: a missing age is unknown, not zero years.
    assert build_candidate(_vendor_row("no-age", years=None)).experience is None


def test_d11_outlier_does_not_flatten_the_pool() -> None:
    """One extreme bid must not compress the rest into a near-tie."""
    from app.review.workflow import _normalise

    ordinary = _normalise([50, 60, 70])
    with_outlier = _normalise([50, 60, 70, 5000])

    # Rank spacing: the three ordinary vendors stay clearly separated.
    assert ordinary == [0.0, 0.5, 1.0]
    gaps = [
        with_outlier[i + 1] - with_outlier[i] for i in range(2)
    ]
    assert all(gap > 0.3 for gap in gaps), (
        f"an outlier flattened the ordinary vendors: {with_outlier}"
    )


def test_d12_shortlist_ties_are_not_broken_arbitrarily() -> None:
    """Vendors tied at the cut-off are all included, not sorted off the list."""
    from app.review.workflow import build_candidate, shortlist_with_basis

    tied = [build_candidate(_vendor_row(v, years=5)) for v in ("A", "B", "C")]
    chosen = shortlist_with_basis(tied, 1, {"experience": 1.0})

    assert {e.candidate.vendor_id for e in chosen} == {"A", "B", "C"}, (
        "a tied vendor was excluded by id sort order"
    )
    assert all(e.tied_at_cutoff for e in chosen)


def test_d13_table_rows_are_chunked_individually() -> None:
    """A table row is its own chunk, so each labelled fact gets its own vector.

    Built from the exact grid that caused the defect: seven rows, five of them
    dates, two of which share the same date under different labels. The old
    size-based pass emitted one chunk for the lot.
    """
    from app.ingest.chunking import chunk_document
    from app.ingest.models import ExtractionMethod, PageText, ParsedDocument

    page = PageText(
        page_number=5,
        text="SECTION 1\nNOTICE INVITING eTENDER\nTenders are invited on behalf of the Director.",
        method=ExtractionMethod.NATIVE,
        tables=[[
            ["Date of Issue/Publishing", "17 August 2026 (18:30 Hours)"],
            ["Document Download/Sale Start Date", "17 August 2026 (18:30 Hours)"],
            ["Document Download/Sale End Date", "22 August 2026 (18:30 Hours)"],
            ["Last Date for submission of EMD", "24 August 2026 (16:00 Hours)"],
            ["Last Date and Time for uploading of Bids", "22 August 2026 (18:30 Hours)"],
            ["Last Date and Time for receipt of Queries", "19 August 2026 (11:00 Hours)"],
            ["Pre-bid Meeting Date and Time", "19 August 2026 (11:00 Hours)"],
        ]],
    )
    document = ParsedDocument(
        file_name="grid.pdf", doc_kind=DocumentKind.NOTIFICATION, pages=[page]
    )
    chunks = chunk_document(document)

    # Each of the seven rows is separately retrievable.
    rows = [c for c in chunks if "table on page 5" in c.text]
    assert len(rows) == 7, f"expected one chunk per row, got {len(rows)}"

    # The bid-upload row stands alone -- it must NOT be bundled with the EMD
    # deadline or the query deadline, which is precisely what diluted it.
    upload = [c for c in rows if "uploading of Bids" in c.text]
    assert len(upload) == 1
    body = upload[0].text
    assert "22 August 2026" in body
    assert "submission of EMD" not in body
    assert "receipt of Queries" not in body
    assert len(body) < 200, f"row chunk is still a blob at {len(body)} chars"

    # Every row keeps its page, so the citation anchor survives row splitting.
    assert all(c.page_number == 5 for c in chunks)
    # Chunk indexes stay contiguous across the prose/table split.
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_table_header_is_only_treated_as_a_header_when_it_is_one() -> None:
    """A first row that states a fact is kept as data, not consumed as a header.

    The date grid's first row IS a fact ("Date of Issue/Publishing | 17 August
    2026"). Treating row zero as a header unconditionally would delete a value
    from the index -- a silent loss, and the worst failure mode for a system
    whose claim is that it loses nothing.
    """
    from app.ingest.chunking import _looks_like_header

    # Carries digits -> it is data, whatever its position.
    assert not _looks_like_header(["Date of Issue/Publishing", "17 August 2026"])
    # Column labels with no digits -> a header.
    assert _looks_like_header(["Criterion", "Threshold", "Unit"])
    # A single cell cannot label columns.
    assert not _looks_like_header(["Eligibility"])


def test_every_known_defect_is_pinned() -> None:
    """Each id in DEFECTS has at least one test function carrying it.

    Without this, deleting a regression test shrinks the safety net silently --
    the suite still passes, and the defect it guarded is free to return.
    """
    module = sys.modules[__name__]
    names = [n for n, _ in inspect.getmembers(module, inspect.isfunction) if n.startswith("test_")]

    unpinned = [
        f"{defect_id}: {description}"
        for defect_id, description in DEFECTS.items()
        if not any(defect_id in name for name in names)
    ]
    assert not unpinned, "defects with no regression test:\n  " + "\n  ".join(unpinned)


def test_every_pinned_test_names_a_registered_defect() -> None:
    """The inverse: a `test_dN_...` whose id is not in DEFECTS is a test whose
    subject nobody wrote down. The register is the documentation."""
    module = sys.modules[__name__]
    orphans = [
        name
        for name, _ in inspect.getmembers(module, inspect.isfunction)
        if re.match(r"^test_d\d+_", name)
        and not any(defect_id in name for defect_id in DEFECTS)
    ]
    assert not orphans, f"tests naming an unregistered defect: {orphans}"


# --------------------------------------------------------------------------- #
# D1 -- unit vs quantity
# --------------------------------------------------------------------------- #
def _notification_with(criterion: EligibilityCriterion) -> TenderNotification:
    return TenderNotification(
        tender_id="T-1",
        title="t",
        issuing_authority="a",
        eligibility_criteria=[criterion],
    )


def _submission_with_projects(count: int) -> VendorSubmission:
    from app.schemas.submission import PastProject

    return VendorSubmission(
        vendor_id="V-1",
        vendor_name="V",
        tender_id="T-1",
        past_projects=[
            PastProject(client=f"c{i}", year=2023, description="d", provenance=_prov())
            for i in range(count)
        ],
    )


def test_d1_unit_vs_quantity_capacity_is_not_a_project_count() -> None:
    """A megawatt figure must never be compared against len(past_projects)."""
    report = build_gap_report(
        _notification_with(
            EligibilityCriterion(
                criterion="Similar works of 13 MW cumulative installed capacity",
                type=CriterionType.NUMERIC,
                threshold_raw="13 MW",
                threshold_number=Decimal(13),
                unit="MW",
                provenance=_prov("28.1"),
            )
        ),
        _submission_with_projects(2),
    )
    item = next(i for i in report.items if "13 MW" in (i.required_value or ""))
    assert item.status is not CheckStatus.MISSING
    assert item.severity is not Severity.DISQUALIFYING
    assert "2" not in (item.found_value or ""), (
        f"a capacity requirement was compared as a count: {item.found_value!r}"
    )


def test_d1_unit_vs_quantity_a_genuine_count_is_still_compared() -> None:
    """The fix must not disable the comparison it was guarding -- a criterion
    genuinely stated in projects still eliminates."""
    report = build_gap_report(
        _notification_with(
            EligibilityCriterion(
                criterion="At least 3 similar completed works",
                type=CriterionType.NUMERIC,
                threshold_raw="3 projects",
                threshold_number=Decimal(3),
                unit="projects",
                provenance=_prov("1.1"),
            )
        ),
        _submission_with_projects(2),
    )
    item = next(i for i in report.items if "3" in (i.required_value or ""))
    assert item.severity is Severity.DISQUALIFYING


def test_d1_unit_vs_quantity_the_count_unit_whitelist_still_exists() -> None:
    """Structural: the comparison is gated on an explicit whitelist of units
    that genuinely mean 'how many'. Losing the gate reopens the defect even if
    the behavioural tests above were rewritten around it."""
    from app.compliance.gap import _COUNT_UNITS, _YEAR_UNITS

    assert "mw" not in _COUNT_UNITS and "km" not in _COUNT_UNITS
    assert {"project", "projects"} <= _COUNT_UNITS
    assert {"year", "years"} <= _YEAR_UNITS


# --------------------------------------------------------------------------- #
# D2 -- comma-tolerant number parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Rs.3, 00, 00,000/-", Decimal("30000000.00")),   # the GHMC printing
        ("Rs. 3,00,00,000", Decimal("30000000.00")),
        ("₹ 2, 00, 000", Decimal("200000.00")),
        ("50,00,000", Decimal("5000000.00")),
    ],
)
def test_d2_comma_tolerant_numbers_survive_spaces_after_commas(raw, expected) -> None:
    assert normalize_amount(raw) == expected


@pytest.mark.parametrize("raw", ["at least 2, Rs. 2 Cr each", "30 60 90 days"])
def test_d2_comma_tolerant_numbers_do_not_merge_unrelated_figures(raw) -> None:
    """The tolerance is bounded: a bare space between digits must NOT join them,
    or '30 60 90 days' becomes one 8-digit number."""
    value = try_normalize_amount(raw)
    assert value != Decimal("306090.00")
    if raw.startswith("at least"):
        assert value == Decimal("20000000.00")   # the crore figure, not the count


# --------------------------------------------------------------------------- #
# D3 -- the bid's contents page is not its enclosure list
# --------------------------------------------------------------------------- #
def test_d3_contents_page_not_enclosures_is_ruled_out_in_the_prompt() -> None:
    """Structural: the enclosure extractor's prompt must explicitly exclude the
    bid's own table of contents, and must define what 'absent' looks like."""
    from app.extraction.prompts import SUBMITTED_DOCUMENTS_PROMPT

    lowered = SUBMITTED_DOCUMENTS_PROMPT.lower()
    assert "table of contents" in lowered or "contents page" in lowered
    assert "index" in lowered or "contents" in lowered


def test_d3_contents_page_not_enclosures_is_not_favoured_by_page_selection() -> None:
    """A contents page must not outscore the real checklist page when the
    extractor picks which pages to read. Measured against the real cue set, not
    against an assertion about which words are in it."""
    from app.extraction.selection import FIELD_GROUPS, _lexical_scores
    from app.ingest.models import PageText, ParsedDocument

    document = ParsedDocument(
        file_name="bid.pdf",
        doc_kind=DocumentKind.SUBMISSION,
        pages=[
            PageText(
                page_number=1,
                text=(
                    "TABLE OF CONTENTS\n\nSl. No.   Section   Page No.\n"
                    "1  Covering Letter .......... 3\n"
                    "2  Method Statement ......... 9\n"
                    "3  Price Schedule ........... 41\n"
                    "16 Checklist of Documents ... 140\n"
                ),
            ),
            PageText(
                page_number=2,
                text=(
                    "SECTION 16 - CHECKLIST OF DOCUMENTS ENCLOSED\n\n"
                    "The documents listed below are enclosed with this bid.\n"
                    "  1. [X]  GST Registration Certificate\n"
                    "  2. [X]  PAN Card\n"
                    "  3. [ ]  ISO 9001 Certificate   - NOT ENCLOSED\n"
                ),
            ),
        ],
    )

    scores = _lexical_scores(document, FIELD_GROUPS["submitted_documents"])
    assert scores.get(2, 0) > scores.get(1, 0), (
        f"the contents page outscored the enclosure checklist: {scores}"
    )


# --------------------------------------------------------------------------- #
# D4 -- an empty extraction is not a pass
# --------------------------------------------------------------------------- #
def test_d4_empty_extraction_is_not_compliant() -> None:
    report = build_gap_report(
        TenderNotification(tender_id="T-1", title="t", issuing_authority="a"),
        VendorSubmission(vendor_id="V-1", vendor_name="V", tender_id="T-1"),
    )
    assert report.items == []
    assert report.verdict == "not_checked"
    assert report.is_compliant is False
    assert report.was_checked is False


def test_d4_empty_extraction_is_not_compliant_even_with_a_real_tender() -> None:
    """The other half: a real tender against a bid that extracted nothing must
    fail, not pass. Nothing was submitted, so nothing can be satisfied."""
    report = build_gap_report(
        TenderNotification(
            tender_id="T-1",
            title="t",
            issuing_authority="a",
            mandatory_documents=[
                MandatoryDocument(doc_name="GST Registration Certificate", provenance=_prov())
            ],
        ),
        VendorSubmission(vendor_id="V-1", vendor_name="V", tender_id="T-1"),
    )
    assert report.verdict == "not_compliant"
    assert report.blocking_items


# --------------------------------------------------------------------------- #
# D5 -- re-extraction must not cascade-delete the bids
# --------------------------------------------------------------------------- #
@pytest.fixture
def clean():
    yield
    with session_scope() as session:
        session.execute(
            text("DELETE FROM tender_notifications WHERE tender_id = :t"), {"t": TENDER_ID}
        )
    try:
        get_client().delete(
            settings.qdrant_collection,
            points_selector=build_filter(tender_id=TENDER_ID),
            wait=True,
        )
    except Exception:
        pass


@pytest.fixture(scope="module")
def pdf(tmp_path_factory):
    return make_notification_pdf(tmp_path_factory.mktemp("reg") / "NOTIF_ITservices_01.pdf")


@live
@embed
def test_d5_reextraction_does_not_cascade_delete_the_bids(pdf, clean) -> None:
    from app.db.models import TenderNotificationRow, VendorSubmissionRow
    from app.extraction import ingest_notification, ingest_submission
    from sqlalchemy import select

    ingest_notification(pdf, llm=StubLLM())
    for vendor in ("V-CASCADE-1", "V-CASCADE-2", "V-CASCADE-3"):
        ingest_submission(pdf, vendor_id=vendor, tender_id=TENDER_ID, llm=StubLLM())

    with session_scope() as session:
        row = session.scalar(
            select(TenderNotificationRow).where(TenderNotificationRow.tender_id == TENDER_ID)
        )
        row_id_before = row.id
        assert len(row.submissions) == 3

    ingest_notification(pdf, llm=StubLLM())

    with session_scope() as session:
        row = session.scalar(
            select(TenderNotificationRow).where(TenderNotificationRow.tender_id == TENDER_ID)
        )
        assert row.id == row_id_before, "the notification row was recreated, not updated"
        survivors = {s.vendor_id for s in row.submissions}
        assert survivors == {"V-CASCADE-1", "V-CASCADE-2", "V-CASCADE-3"}, (
            f"re-extraction destroyed bids; survivors: {survivors}"
        )
        # And nothing orphaned: every submission row still points at a tender.
        orphans = session.scalars(
            select(VendorSubmissionRow).where(VendorSubmissionRow.notification_id.is_(None))
        ).all()
        assert not [o for o in orphans if o.vendor_id.startswith("V-CASCADE")]


def test_d5_reextraction_does_not_cascade_delete_updates_in_place() -> None:
    """Structural: save_notification must find-and-update, never delete-and-add.
    A `session.delete(row)` on the matched row reopens the defect regardless of
    what the behavioural test above happens to exercise."""
    from app.extraction import persist

    source = inspect.getsource(persist.save_notification)
    # The one delete in this function is of *duplicate* rows, after their bids
    # have been re-homed. Deleting the matched row itself is the defect.
    assert "session.delete(duplicate)" in source
    assert "session.delete(row)" not in source
    assert "for submission in list(duplicate.submissions)" in source, (
        "duplicate rows must donate their bids before being removed"
    )


# --------------------------------------------------------------------------- #
# D6 -- a percentage is not an amount
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw", ["30% of the estimated cost", "EMD @ 1% of the ECV", "2 per cent", "5 percent"]
)
def test_d6_percentage_is_not_an_amount(raw) -> None:
    with pytest.raises(MoneyParseError):
        normalize_amount(raw)
    assert try_normalize_amount(raw) is None


def test_d6_percentage_is_not_an_amount_but_an_absolute_figure_beside_one_is() -> None:
    """The guard must not swallow a real figure printed next to a rate."""
    assert normalize_amount("Rs. 5 Cr, being 30% of the estimated cost") == Decimal(
        "50000000.00"
    )


def test_d6_percentage_is_not_an_amount_so_a_relative_threshold_stays_unresolved() -> None:
    """End of the chain: an unresolvable percentage threshold must surface as
    needs-manual-check, never as a Rs. 30 floor everybody clears."""
    report = build_gap_report(
        _notification_with(
            EligibilityCriterion(
                criterion="Average annual turnover of 30% of the estimated cost",
                type=CriterionType.NUMERIC,
                threshold_raw="30% of the estimated cost",
                provenance=_prov("1"),
            )
        ),
        VendorSubmission(vendor_id="V-1", vendor_name="V", tender_id="T-1"),
    )
    item = next(i for i in report.items if "turnover" in i.requirement.lower())
    assert item.status is CheckStatus.NOT_ASSESSABLE
    assert item.severity is not Severity.DISQUALIFYING


# --------------------------------------------------------------------------- #
# D7 -- no unbounded LLM call
# --------------------------------------------------------------------------- #
def test_d7_llm_calls_are_bounded_in_every_provider() -> None:
    """Structural, and deliberately provider-agnostic: any module under app.llm
    that makes a network call must pass a timeout to it. A new provider added
    without one fails this test rather than hanging a worker in production."""
    import pkgutil

    import app.llm as llm_pkg

    checked = 0
    for module_info in pkgutil.iter_modules(llm_pkg.__path__):
        name = module_info.name
        if name in ("base", "ratelimit"):
            continue
        source = inspect.getsource(__import__(f"app.llm.{name}", fromlist=["x"]))
        if not re.search(r"requests\.|httpx|genai\.Client|urlopen", source):
            continue
        checked += 1
        assert "timeout" in source, f"app.llm.{name} makes a network call with no timeout"
    assert checked >= 2, "expected at least the gemini and ollama providers"


def test_d7_llm_calls_are_bounded_by_a_sane_configured_value() -> None:
    """A timeout of zero, or of a day, is the same defect wearing a config key."""
    assert 0 < settings.gemini_timeout_ms <= 10 * 60 * 1000


def test_d7_llm_calls_are_bounded_and_the_client_actually_receives_it(monkeypatch) -> None:
    """The timeout must reach the SDK, not merely exist in settings.

    Patched at `google.genai.Client` rather than by swapping the module in
    sys.modules: `from google import genai` reads an attribute of an
    already-imported package, so a sys.modules swap silently does nothing once
    anything else in the suite has imported google.
    """
    from unittest.mock import patch

    monkeypatch.setattr(settings, "gemini_api_key", "test-key")

    with patch("google.genai.Client") as client_cls:
        from app.llm.gemini import GeminiProvider

        GeminiProvider()

    kwargs = client_cls.call_args.kwargs
    assert kwargs["http_options"]["timeout"] == settings.gemini_timeout_ms


# --------------------------------------------------------------------------- #
# D8 -- chunk purge scoped to one submission
# --------------------------------------------------------------------------- #
@live
@embed
def test_d8_chunk_purge_is_scoped_to_one_submission_across_tenders(pdf, clean) -> None:
    """A vendor bidding on two tenders, re-uploading one bid, must keep the
    other bid's chunks."""
    from app.extraction import ingest_notification, ingest_submission

    ingest_notification(pdf, llm=StubLLM())
    # Same vendor, two submissions -- one linked to the tender, one orphaned
    # (no tender_id), which is the shape that triggered the original defect.
    ingest_submission(pdf, vendor_id="V-TWOTENDER", tender_id=TENDER_ID, llm=StubLLM())
    ingest_submission(pdf, vendor_id="V-TWOTENDER", tender_id=None, llm=StubLLM())

    def count(**kwargs) -> int:
        return len(
            get_client().scroll(
                settings.qdrant_collection,
                scroll_filter=build_filter(**kwargs),
                limit=1000,
            )[0]
        )

    linked_before = count(vendor_id="V-TWOTENDER", tender_id=TENDER_ID)
    assert linked_before > 0

    # Re-upload the orphaned bid. Its purge must not touch the linked one.
    ingest_submission(pdf, vendor_id="V-TWOTENDER", tender_id=None, llm=StubLLM())

    assert count(vendor_id="V-TWOTENDER", tender_id=TENDER_ID) == linked_before, (
        "re-indexing one bid deleted the same vendor's chunks on another tender"
    )

    with session_scope() as session:
        session.execute(
            text("DELETE FROM vendor_submissions WHERE vendor_id = 'V-TWOTENDER'")
        )
    get_client().delete(
        settings.qdrant_collection,
        points_selector=build_filter(vendor_id="V-TWOTENDER"),
        wait=True,
    )


def test_d8_chunk_purge_is_scoped_to_one_submission_by_id_not_by_vendor() -> None:
    """Structural: the purge filter for a submission must narrow on the
    submission id. Scoping by vendor_id is precisely the defect, and
    build_filter silently drops a None tender_id rather than narrowing on it."""
    from app.extraction import persist

    source = inspect.getsource(persist.index_submission)
    assert "stale_filter=build_filter(submission_id=str(row_id))" in source, (
        "the submission purge is no longer scoped to a single submission id"
    )


def test_d8_chunk_purge_is_scoped_to_one_submission_build_filter_drops_none() -> None:
    """Why the id scoping is load-bearing: build_filter omits None rather than
    matching on it, so a vendor-scoped purge of an unlinked bid is unbounded."""
    narrow = build_filter(vendor_id="V", tender_id=None)
    both = build_filter(vendor_id="V", tender_id="T")
    assert len(narrow.must) == 1 and len(both.must) == 2


# --------------------------------------------------------------------------- #
# D9 -- slashed tender ids
# --------------------------------------------------------------------------- #
def test_d9_slashed_tender_ids_route_correctly_by_declaration_order() -> None:
    """Structural, and the only kind of test that can catch this: FastAPI
    matches in declaration order, so the greedy {tender_id:path} route must be
    declared last. Reordering the file reintroduces the 404 with no other
    visible change."""
    from app.api.routes import router

    paths = [
        route.path
        for route in router.routes
        if "get" in {m.lower() for m in getattr(route, "methods", set())}
    ]
    greedy = "/api/notifications/{tender_id:path}"
    assert greedy in paths
    specific = [p for p in paths if p.startswith("/api/notifications/") and p != greedy]
    assert specific, "expected at least the /submissions sub-route"
    for path in specific:
        assert paths.index(path) < paths.index(greedy), (
            f"{path} is declared after the greedy {greedy} and can never match"
        )


@live
@embed
def test_d9_slashed_tender_ids_route_correctly_end_to_end(pdf, clean) -> None:
    from fastapi.testclient import TestClient

    from app.api.main import app
    from app.extraction import ingest_notification

    ingest_notification(pdf, llm=StubLLM())
    slashed = TENDER_ID
    assert "/" in slashed, "this test is meaningless unless the id contains a slash"

    client = TestClient(app)
    import uuid
    auth = client.post("/api/auth/register", json={"email":f"reg-{uuid.uuid4()}@example.com","password":"correct-horse-battery-staple","role":"reviewer","reviewer_code":"development-reviewer"})
    client.headers["Authorization"] = f"Bearer {auth.json()['access_token']}"
    detail = client.get(f"/api/notifications/{slashed}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["tender_id"] == slashed

    subs = client.get(f"/api/notifications/{slashed}/submissions")
    assert subs.status_code == 200, subs.text
    assert isinstance(subs.json(), list), (
        "the greedy route swallowed the /submissions suffix"
    )
