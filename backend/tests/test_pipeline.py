"""End-to-end: real PDF -> parse -> extract (stub LLM) -> real Postgres + Qdrant."""

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
    report = ingest_notification(pdf, llm=StubLLM())

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
    first = ingest_notification(pdf, llm=StubLLM())
    second = ingest_notification(pdf, llm=StubLLM())

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
    assert first.row_id != second.row_id  # replaced, not merged


@live
@embed
def test_vendor_submission_linked_and_status_tagged(pdf, clean):
    ingest_notification(pdf, llm=StubLLM())
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
    report = ingest_notification(pdf, llm=StubLLM(fail_on={"TechnicalList"}))

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
    full = ingest_notification(pdf, llm=StubLLM())
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
    from sqlalchemy import func

    broken = ingest_notification(pdf, llm=StubLLM(fail_on={"RawHeader"}))
    assert broken.identifier == "NOTIF_ITservices_01.pdf"  # the fallback

    good = ingest_notification(pdf, llm=StubLLM())
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
