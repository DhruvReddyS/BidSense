"""End-to-end: real PDF -> parse -> extract (stub LLM) -> real Postgres + Qdrant.

Every ingest here passes `use_cache=False`. This file is about the PERSISTENCE
layer, and it works by extracting the same bytes repeatedly with different
scripted output -- which the content-keyed extraction cache would correctly
collapse to one result, leaving the tests measuring nothing. Only a test can
vary the extraction of identical bytes; a real re-upload should reuse it, and
`tests/test_efficiency.py` covers that.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.config import settings
from app.db.models import TenderNotificationRow, VendorSubmissionRow, VendorTurnoverRow
from app.db.session import engine, session_scope
from app.extraction import ingest_notification, ingest_submission
from app.schemas.common import ChunkSection, DocumentKind, VendorStatus
from app.vector.qdrant import build_filter, collection_stats, get_client
from tests.doc_factory import NOTIFICATION_TRUTH, make_notification_pdf
from tests.stub_llm import StubLLM


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


@pytest.fixture
def clean():
    """Remove anything this test wrote, in both stores."""
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
    return make_notification_pdf(tmp_path_factory.mktemp("p") / "NOTIF_ITservices_01.pdf")


@live
@embed
def test_notification_ingested_into_both_stores(pdf, clean):
    report = ingest_notification(pdf, llm=StubLLM(), use_cache=False)

    assert report.ok, report.extraction_errors
    assert report.identifier == TENDER_ID
    assert report.pages == 3
    assert report.chunks_indexed > 0
    assert report.total_seconds > 0

    with session_scope() as session:
        row = session.scalar(
            select(TenderNotificationRow).where(TenderNotificationRow.tender_id == TENDER_ID)
        )
        assert row is not None
        assert row.issuing_authority == NOTIFICATION_TRUTH["issuing_authority"]
        assert row.emd_amount_inr == Decimal("200000.00")
        assert len(row.eligibility_criteria) == 3
        assert len(row.mandatory_documents) == 5
        # JSONB half survives.
        assert len(row.technical_requirements) == 2
        assert row.evaluation_criteria == []

        turnover = next(
            c for c in row.eligibility_criteria if "turnover" in c.criterion.lower()
        )
        assert turnover.threshold_amount_inr == Decimal("50000000.00")
        assert turnover.clause_ref == "4.2"
        assert turnover.source_page == 2

    found, _ = get_client().scroll(
        settings.qdrant_collection,
        scroll_filter=build_filter(
            doc_kind=DocumentKind.NOTIFICATION, tender_id=TENDER_ID
        ),
        limit=100,
    )
    assert len(found) == report.chunks_indexed
    assert all(p.payload["tender_id"] == TENDER_ID for p in found)
    assert all(p.payload["source_page"] in (1, 2, 3) for p in found)


@live
@embed
def test_reingesting_replaces_rather_than_duplicates(pdf, clean):
    """Re-extraction must not leave criteria from a previous, possibly wrong,
    extraction silently in force -- nor duplicate chunks in the index."""
    first = ingest_notification(pdf, llm=StubLLM(), use_cache=False)
    second = ingest_notification(pdf, llm=StubLLM(), use_cache=False)

    with session_scope() as session:
        rows = session.scalars(
            select(TenderNotificationRow).where(TenderNotificationRow.tender_id == TENDER_ID)
        ).all()
        assert len(rows) == 1
        assert len(rows[0].eligibility_criteria) == 3

    found, _ = get_client().scroll(
        settings.qdrant_collection,
        scroll_filter=build_filter(tender_id=TENDER_ID),
        limit=200,
    )
    assert len(found) == second.chunks_indexed
    # The row id must be STABLE across re-extraction: vendor_submissions
    # references it, so minting a new id (or delete/recreate) would cascade away
    # every bid filed against the tender.
    assert first.row_id == second.row_id


@live
@embed
def test_vendor_submission_linked_and_status_tagged(pdf, clean):
    ingest_notification(pdf, llm=StubLLM(), use_cache=False)
    report = ingest_submission(pdf, vendor_id="V-04", tender_id=TENDER_ID, llm=StubLLM())

    assert report.ok, report.extraction_errors
    with session_scope() as session:
        row = session.scalar(
            select(VendorSubmissionRow).where(VendorSubmissionRow.vendor_id == "V-04")
        )
        assert row is not None
        assert row.notification_id is not None, "submission must link to its tender"
        assert row.status is VendorStatus.PENDING
        assert row.has_technical_approach is True
        assert row.quoted_price_inr == Decimal("118000000.00")

        by_year = {t.year: t for t in row.turnover}
        assert by_year[2023].amount_inr == Decimal("42000000.00")
        assert by_year[2024].amount_inr is None  # unparseable stays NULL, not 0

    found, _ = get_client().scroll(
        settings.qdrant_collection,
        scroll_filter=build_filter(vendor_id="V-04", statuses=[VendorStatus.PENDING]),
        limit=200,
    )
    assert found, "vendor chunks must be tagged with vendor_id and status"
    sections = {p.payload["section"] for p in found}
    assert ChunkSection.TECHNICAL_APPROACH.value in sections
    assert ChunkSection.PAST_PERFORMANCE.value in sections


@live
@embed
def test_partial_extraction_is_persisted_and_flagged(pdf, clean):
    """A run with a failed node must still store what succeeded, and say so."""
    # use_cache=False throughout: these tests deliberately extract the SAME
    # bytes twice with DIFFERENT scripted output, to exercise the persistence
    # layer's replace semantics. The extraction cache is keyed on content, so
    # with it on the second run would correctly return the first result and the
    # test would be measuring nothing. Only a test can vary this; a real second
    # upload of identical bytes SHOULD reuse the first extraction.
    report = ingest_notification(pdf, llm=StubLLM(fail_on={"TechnicalList"}), use_cache=False)

    assert report.ok is False
    assert len(report.extraction_errors) == 1
    with session_scope() as session:
        row = session.scalar(
            select(TenderNotificationRow).where(TenderNotificationRow.tender_id == TENDER_ID)
        )
        assert row is not None
        assert row.technical_requirements == []
        assert len(row.eligibility_criteria) == 3  # healthy branches landed


@live
def test_indexing_can_be_skipped_for_a_sql_only_run(pdf, clean):
    """Lets the extraction-accuracy metric (Section 10) be re-run without paying
    the embedding cost each time."""
    report = ingest_notification(pdf, llm=StubLLM(), index=False)
    assert report.chunks_indexed == 0
    with session_scope() as session:
        assert session.scalar(
            select(TenderNotificationRow).where(TenderNotificationRow.tender_id == TENDER_ID)
        )


@live
@embed
def test_shrinking_reextraction_strands_no_orphan_chunks(pdf, clean):
    """A re-extraction yielding fewer chunks must not leave the tail behind --
    orphans would be retrievable and citable long after the text they quote is
    gone from the record."""
    full = ingest_notification(pdf, llm=StubLLM(), use_cache=False)
    assert full.chunks_indexed >= 3

    from app.ingest import parse_document
    from app.extraction.persist import index_notification
    from app.extraction.graph import extract_notification

    document = parse_document(pdf, DocumentKind.NOTIFICATION)
    document.pages = document.pages[:1]  # simulate a shorter re-parse
    notification, _ = extract_notification(document, llm=StubLLM())
    shrunk = index_notification(document, notification, full.row_id)

    found, _ = get_client().scroll(
        settings.qdrant_collection,
        scroll_filter=build_filter(tender_id=TENDER_ID),
        limit=200,
    )
    assert len(found) == shrunk < full.chunks_indexed


@live
@embed
def test_failed_then_successful_run_leaves_one_row(pdf, clean):
    """When header extraction fails, tender_id falls back to the filename. A
    later successful run must replace that shell, not sit beside it -- otherwise
    the listing shows a phantom tender with no criteria."""
    # use_cache=False throughout: these tests deliberately extract the SAME
    # bytes twice with DIFFERENT scripted output, to exercise the persistence
    # layer's replace semantics. The extraction cache is keyed on content, so
    # with it on the second run would correctly return the first result and the
    # test would be measuring nothing. Only a test can vary this; a real second
    # upload of identical bytes SHOULD reuse the first extraction.
    from sqlalchemy import func

    broken = ingest_notification(pdf, llm=StubLLM(fail_on={"RawHeader"}), use_cache=False)
    assert broken.identifier == "NOTIF_ITservices_01.pdf"  # the fallback

    good = ingest_notification(pdf, llm=StubLLM(), use_cache=False)
    assert good.identifier == TENDER_ID

    with session_scope() as session:
        rows = session.scalars(
            select(TenderNotificationRow).where(
                TenderNotificationRow.source_file.like("%NOTIF_ITservices_01.pdf")
            )
        ).all()
        assert len(rows) == 1, "the shell row from the failed run must be replaced"
        assert rows[0].tender_id == TENDER_ID
        assert len(rows[0].eligibility_criteria) == 3


@live
@embed
def test_reextracting_a_notification_preserves_its_vendor_bids(pdf, clean):
    """The data-loss case. vendor_submissions cascades from the notification, so
    delete-and-recreate on re-extraction silently destroys every bid filed
    against the tender -- a hundred evaluations lost to re-running extraction,
    or to uploading a corrigendum (5.6)."""
    first = ingest_notification(pdf, llm=StubLLM(), use_cache=False)
    ingest_submission(pdf, vendor_id="V-04", tender_id=TENDER_ID, llm=StubLLM())
    ingest_submission(pdf, vendor_id="V-09", tender_id=TENDER_ID, llm=StubLLM())

    with session_scope() as session:
        before = session.scalars(
            select(VendorSubmissionRow).where(
                VendorSubmissionRow.notification_id == first.row_id
            )
        ).all()
        assert len(before) == 2

    second = ingest_notification(pdf, llm=StubLLM(), use_cache=False)
    assert second.row_id == first.row_id

    with session_scope() as session:
        after = session.scalars(
            select(VendorSubmissionRow).where(
                VendorSubmissionRow.notification_id == second.row_id
            )
        ).all()
        assert {s.vendor_id for s in after} == {"V-04", "V-09"}, (
            "vendor bids must survive re-extraction of the notification"
        )


@live
@embed
def test_reextraction_refreshes_criteria_without_merging_stale_ones(pdf, clean):
    """Children are replaced wholesale. A partial merge would leave criteria
    from a previous, possibly wrong, extraction silently in force."""
    # use_cache=False throughout: these tests deliberately extract the SAME
    # bytes twice with DIFFERENT scripted output, to exercise the persistence
    # layer's replace semantics. The extraction cache is keyed on content, so
    # with it on the second run would correctly return the first result and the
    # test would be measuring nothing. Only a test can vary this; a real second
    # upload of identical bytes SHOULD reuse the first extraction.
    ingest_notification(pdf, llm=StubLLM(), use_cache=False)

    trimmed = StubLLM()
    trimmed.script["EligibilityList"].items = trimmed.script["EligibilityList"].items[:1]
    ingest_notification(pdf, llm=trimmed, use_cache=False)

    with session_scope() as session:
        row = session.scalar(
            select(TenderNotificationRow).where(TenderNotificationRow.tender_id == TENDER_ID)
        )
        assert len(row.eligibility_criteria) == 1, "stale criteria must not survive"


@live
@embed
def test_a_shell_row_from_a_failed_run_donates_its_bids(pdf, clean):
    """When header extraction fails the tender_id falls back to the filename, so
    a bid filed against that shell must be re-homed onto the real row rather
    than deleted with it."""
    broken = ingest_notification(pdf, llm=StubLLM(fail_on={"RawHeader"}), use_cache=False)
    ingest_submission(
        pdf, vendor_id="V-77", tender_id=broken.identifier, llm=StubLLM()
    )

    good = ingest_notification(pdf, llm=StubLLM(), use_cache=False)

    with session_scope() as session:
        rows = session.scalars(
            select(TenderNotificationRow).where(
                TenderNotificationRow.source_file.like("%NOTIF_ITservices_01.pdf")
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].tender_id == TENDER_ID
        assert {s.vendor_id for s in rows[0].submissions} == {"V-77"}


@live
@embed
def test_reingesting_a_bid_keeps_a_stable_row_id(pdf, clean):
    """Vector chunks are purged by submission id. A churning id means the purge
    cannot find the previous chunks, which forced a looser filter that could
    delete a vendor's chunks across every tender they had bid on."""
    ingest_notification(pdf, llm=StubLLM(), use_cache=False)
    first = ingest_submission(pdf, vendor_id="V-04", tender_id=TENDER_ID, llm=StubLLM())
    second = ingest_submission(pdf, vendor_id="V-04", tender_id=TENDER_ID, llm=StubLLM())

    assert first.row_id == second.row_id

    with session_scope() as session:
        rows = session.scalars(
            select(VendorSubmissionRow).where(VendorSubmissionRow.vendor_id == "V-04")
        ).all()
        assert len(rows) == 1
        assert len(rows[0].turnover) == 3      # replaced wholesale, not doubled


@live
@embed
def test_reingesting_one_bid_leaves_another_vendors_chunks_alone(pdf, clean):
    """The purge must be scoped to this submission. Scoping by vendor_id, with a
    None tender_id dropped by build_filter, deleted far more than intended."""
    ingest_notification(pdf, llm=StubLLM(), use_cache=False)
    ingest_submission(pdf, vendor_id="V-AAA", tender_id=TENDER_ID, llm=StubLLM())
    ingest_submission(pdf, vendor_id="V-BBB", tender_id=TENDER_ID, llm=StubLLM())

    before, _ = get_client().scroll(
        settings.qdrant_collection,
        scroll_filter=build_filter(vendor_id="V-BBB"),
        limit=200,
    )
    assert before

    ingest_submission(pdf, vendor_id="V-AAA", tender_id=TENDER_ID, llm=StubLLM())

    after, _ = get_client().scroll(
        settings.qdrant_collection,
        scroll_filter=build_filter(vendor_id="V-BBB"),
        limit=200,
    )
    assert len(after) == len(before), "re-ingesting V-AAA disturbed V-BBB's chunks"


@live
@embed
def test_a_bid_with_no_tender_link_purges_only_itself(pdf, clean):
    """The specific case the loose filter got wrong: with tender_id None,
    build_filter omitted it entirely and the purge matched on vendor_id alone."""
    ingest_notification(pdf, llm=StubLLM(), use_cache=False)
    linked = ingest_submission(pdf, vendor_id="V-DUP", tender_id=TENDER_ID, llm=StubLLM())
    orphan = ingest_submission(pdf, vendor_id="V-DUP", tender_id=None, llm=StubLLM())
    assert linked.row_id != orphan.row_id

    linked_chunks, _ = get_client().scroll(
        settings.qdrant_collection,
        scroll_filter=build_filter(submission_id=str(linked.row_id)),
        limit=200,
    )
    assert linked_chunks, "the linked bid should have chunks"

    # Re-ingest the unlinked one; the linked one must be untouched.
    ingest_submission(pdf, vendor_id="V-DUP", tender_id=None, llm=StubLLM())

    still, _ = get_client().scroll(
        settings.qdrant_collection,
        scroll_filter=build_filter(submission_id=str(linked.row_id)),
        limit=200,
    )
    assert len(still) == len(linked_chunks)

    with session_scope() as session:
        session.execute(
            text("DELETE FROM vendor_submissions WHERE vendor_id = 'V-DUP'")
        )
