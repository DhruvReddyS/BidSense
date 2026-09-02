"""Stress tests for the re-extraction / re-upload / upsert paths.

These are the paths where a bug is invisible. A duplicated row still answers
queries; an orphaned chunk still gets retrieved and cited; an overwrite still
returns 200. Nothing in the UI says "you now have two copies of this tender and
the gap report is reading the older one", so the only place this can be caught
is here.

Three invariants, asserted after every scenario:

  ONE ROW      one notification per tender_id, one submission per
               (notification, vendor). Re-running anything must converge, not
               accumulate.
  NO ORPHANS   every chunk in Qdrant belongs to a row that still exists in
               Postgres. A chunk whose owner was replaced is still retrievable
               and still citable -- it is a wrong answer with a real-looking
               citation attached.
  NO SILENT    a write that loses a race must fail loudly or converge
  OVERWRITE    correctly. It must never half-apply.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from sqlalchemy import select, text

from app.config import settings
from app.db.models import TenderNotificationRow, VendorSubmissionRow
from app.db.session import engine, session_scope
from app.extraction import ingest_notification, ingest_submission
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


pytestmark = [
    pytest.mark.skipif(not _services_up(), reason="postgres/qdrant not running"),
    pytest.mark.skipif(not _embeddings_available(), reason="BGE model unavailable"),
]

TENDER_ID = NOTIFICATION_TRUTH["tender_id"]


@pytest.fixture(scope="module")
def pdf(tmp_path_factory):
    return make_notification_pdf(tmp_path_factory.mktemp("stress") / "NOTIF_ITservices_01.pdf")


@pytest.fixture
def clean():
    """Wipe this tender from both stores, before and after.

    Before as well as after: a previous failing run must not leave state that
    makes the next run pass for the wrong reason.
    """

    def wipe():
        with session_scope() as session:
            session.execute(
                text("DELETE FROM tender_notifications WHERE tender_id = :t"),
                {"t": TENDER_ID},
            )
            session.execute(
                text("DELETE FROM vendor_submissions WHERE vendor_id LIKE 'V-STRESS%'")
            )
        try:
            get_client().delete(
                settings.qdrant_collection,
                points_selector=build_filter(tender_id=TENDER_ID),
                wait=True,
            )
        except Exception:
            pass

    wipe()
    yield
    wipe()


# --------------------------------------------------------------------------- #
# Invariant helpers
# --------------------------------------------------------------------------- #
def _notification_rows() -> list[TenderNotificationRow]:
    with session_scope() as session:
        return list(
            session.scalars(
                select(TenderNotificationRow).where(
                    TenderNotificationRow.tender_id == TENDER_ID
                )
            )
        )


def _submission_rows() -> list[VendorSubmissionRow]:
    with session_scope() as session:
        return list(
            session.scalars(
                select(VendorSubmissionRow).where(
                    VendorSubmissionRow.vendor_id.like("V-STRESS%")
                )
            )
        )


def _points(**filters) -> list:
    out, offset = [], None
    while True:
        page, offset = get_client().scroll(
            settings.qdrant_collection,
            scroll_filter=build_filter(**filters),
            limit=500,
            offset=offset,
            with_payload=True,
        )
        out.extend(page)
        if offset is None:
            break
    return out


def assert_no_orphan_chunks() -> None:
    """Every indexed chunk must belong to a row that still exists.

    This is the check that catches the whole family of purge bugs at once: a
    purge that missed, a purge scoped too narrowly, a row replaced rather than
    updated. All three leave chunks whose owner is gone, and all three are
    invisible until a retrieval cites one.
    """
    with session_scope() as session:
        live_notifications = {
            str(i) for i in session.scalars(select(TenderNotificationRow.id))
        }
        live_submissions = {
            str(i) for i in session.scalars(select(VendorSubmissionRow.id))
        }

    orphans = []
    for point in _points(tender_id=TENDER_ID):
        payload = point.payload or {}
        submission_id = payload.get("submission_id")
        notification_id = payload.get("notification_id")
        if submission_id is not None:
            if submission_id not in live_submissions:
                orphans.append(("submission", submission_id, payload.get("source_file")))
        elif notification_id is not None and notification_id not in live_notifications:
            orphans.append(("notification", notification_id, payload.get("source_file")))

    assert not orphans, f"orphaned chunks with no owning row: {orphans[:5]}"


# --------------------------------------------------------------------------- #
# Repeated re-extraction
# --------------------------------------------------------------------------- #
def test_repeated_reextraction_of_the_same_notification_converges(pdf, clean) -> None:
    """Ten re-extractions: one row, one row id, and a chunk count that does not
    creep. A count that grows means the purge is missing chunks; a changing row
    id means the row is being recreated, which cascades the bids away."""
    first = ingest_notification(pdf, llm=StubLLM())
    baseline_id = _notification_rows()[0].id
    baseline_chunks = len(_points(tender_id=TENDER_ID))
    assert baseline_chunks == first.chunks_indexed

    for run in range(9):
        ingest_notification(pdf, llm=StubLLM())
        rows = _notification_rows()
        assert len(rows) == 1, f"run {run + 2} produced {len(rows)} rows"
        assert rows[0].id == baseline_id, f"run {run + 2} recreated the row"
        assert len(_points(tender_id=TENDER_ID)) == baseline_chunks, (
            f"run {run + 2} left the chunk count at "
            f"{len(_points(tender_id=TENDER_ID))}, expected {baseline_chunks}"
        )

    assert_no_orphan_chunks()


def test_repeated_reextraction_does_not_accumulate_child_rows(pdf, clean) -> None:
    """Children are replaced wholesale. Ten runs must not leave ten copies of
    every eligibility criterion -- which would silently double-count a
    requirement in the gap report."""
    ingest_notification(pdf, llm=StubLLM())
    with session_scope() as session:
        row = session.scalar(
            select(TenderNotificationRow).where(TenderNotificationRow.tender_id == TENDER_ID)
        )
        criteria, documents = len(row.eligibility_criteria), len(row.mandatory_documents)
    assert criteria and documents

    for _ in range(4):
        ingest_notification(pdf, llm=StubLLM())

    with session_scope() as session:
        row = session.scalar(
            select(TenderNotificationRow).where(TenderNotificationRow.tender_id == TENDER_ID)
        )
        assert len(row.eligibility_criteria) == criteria
        assert len(row.mandatory_documents) == documents


# --------------------------------------------------------------------------- #
# Repeated bid re-upload
# --------------------------------------------------------------------------- #
def test_repeated_bid_reupload_converges(pdf, clean) -> None:
    ingest_notification(pdf, llm=StubLLM())
    ingest_submission(pdf, vendor_id="V-STRESS-1", tender_id=TENDER_ID, llm=StubLLM())

    rows = _submission_rows()
    assert len(rows) == 1
    baseline_id = rows[0].id
    baseline_chunks = len(_points(vendor_id="V-STRESS-1"))
    assert baseline_chunks > 0

    for run in range(9):
        ingest_submission(pdf, vendor_id="V-STRESS-1", tender_id=TENDER_ID, llm=StubLLM())
        rows = _submission_rows()
        assert len(rows) == 1, f"re-upload {run + 2} produced {len(rows)} rows"
        assert rows[0].id == baseline_id, "the submission row id churned"
        assert len(_points(vendor_id="V-STRESS-1")) == baseline_chunks

    assert_no_orphan_chunks()


def test_repeated_bid_reupload_does_not_accumulate_turnover_rows(pdf, clean) -> None:
    """uq_turnover_per_year would raise on a duplicate, so an accumulating
    child write shows up as a hard failure rather than a wrong number -- but
    only if the replace actually happens. Assert the count, not the absence of
    an exception."""
    ingest_notification(pdf, llm=StubLLM())
    ingest_submission(pdf, vendor_id="V-STRESS-1", tender_id=TENDER_ID, llm=StubLLM())
    with session_scope() as session:
        row = session.scalar(
            select(VendorSubmissionRow).where(VendorSubmissionRow.vendor_id == "V-STRESS-1")
        )
        years = len(row.turnover)
        projects = len(row.past_projects)
        documents = len(row.documents_submitted)

    for _ in range(4):
        ingest_submission(pdf, vendor_id="V-STRESS-1", tender_id=TENDER_ID, llm=StubLLM())

    with session_scope() as session:
        row = session.scalar(
            select(VendorSubmissionRow).where(VendorSubmissionRow.vendor_id == "V-STRESS-1")
        )
        assert len(row.turnover) == years
        assert len(row.past_projects) == projects
        assert len(row.documents_submitted) == documents


def test_reuploading_one_bid_does_not_disturb_the_others(pdf, clean) -> None:
    ingest_notification(pdf, llm=StubLLM())
    for vendor in ("V-STRESS-A", "V-STRESS-B", "V-STRESS-C"):
        ingest_submission(pdf, vendor_id=vendor, tender_id=TENDER_ID, llm=StubLLM())

    before = {v: len(_points(vendor_id=v)) for v in ("V-STRESS-A", "V-STRESS-B", "V-STRESS-C")}
    assert all(before.values())

    for _ in range(3):
        ingest_submission(pdf, vendor_id="V-STRESS-B", tender_id=TENDER_ID, llm=StubLLM())

    after = {v: len(_points(vendor_id=v)) for v in before}
    assert after == before, f"re-uploading B changed other vendors: {before} -> {after}"
    assert len(_submission_rows()) == 3
    assert_no_orphan_chunks()


# --------------------------------------------------------------------------- #
# Concurrency
# --------------------------------------------------------------------------- #
def _parallel(fn, args_list, workers: int = 4):
    """Run `fn` over `args_list` concurrently, returning (results, exceptions)."""
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fn, *args) for args in args_list]
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - the point of the test
                errors.append(exc)
    return results, errors


def test_concurrent_uploads_of_the_same_notification_converge_on_one_row(pdf, clean) -> None:
    """Four uploads of the same tender at once.

    Both branches of `save_notification` race: each SELECTs, finds nothing, and
    INSERTs. Whatever the losers do, the invariant afterwards is the same --
    exactly one row, and no orphaned chunks. A duplicate row here is the worst
    outcome in the system: the gap report would read one of them at random.
    """
    _, errors = _parallel(
        lambda: ingest_notification(pdf, llm=StubLLM()), [()] * 4
    )

    rows = _notification_rows()
    assert len(rows) == 1, (
        f"{len(rows)} notification rows after concurrent upload "
        f"(errors: {[str(e)[:120] for e in errors]})"
    )
    assert not errors, f"concurrent upload raised: {[str(e)[:200] for e in errors]}"
    assert_no_orphan_chunks()


def test_concurrent_uploads_of_different_vendors_all_land(pdf, clean) -> None:
    ingest_notification(pdf, llm=StubLLM())
    vendors = [f"V-STRESS-{i}" for i in range(6)]

    _, errors = _parallel(
        lambda v: ingest_submission(pdf, vendor_id=v, tender_id=TENDER_ID, llm=StubLLM()),
        [(v,) for v in vendors],
    )
    assert not errors, f"concurrent bid uploads raised: {[str(e)[:200] for e in errors]}"

    landed = {r.vendor_id for r in _submission_rows()}
    assert landed == set(vendors), f"missing bids: {set(vendors) - landed}"
    for vendor in vendors:
        assert _points(vendor_id=vendor), f"{vendor} has a row but no chunks"
    assert_no_orphan_chunks()


def test_concurrent_reuploads_of_the_same_vendor_do_not_duplicate(pdf, clean) -> None:
    """The uq_vendor_per_tender race. Four simultaneous uploads of one bid must
    leave exactly one row, with its chunks intact -- not one row and three
    IntegrityErrors, and certainly not two rows."""
    ingest_notification(pdf, llm=StubLLM())

    _, errors = _parallel(
        lambda: ingest_submission(
            pdf, vendor_id="V-STRESS-RACE", tender_id=TENDER_ID, llm=StubLLM()
        ),
        [()] * 4,
    )

    with session_scope() as session:
        rows = list(
            session.scalars(
                select(VendorSubmissionRow).where(
                    VendorSubmissionRow.vendor_id == "V-STRESS-RACE"
                )
            )
        )
    assert len(rows) == 1, f"{len(rows)} rows for one vendor"
    assert not errors, f"concurrent re-upload raised: {[str(e)[:200] for e in errors]}"
    assert _points(vendor_id="V-STRESS-RACE"), "the winning row has no chunks"
    assert_no_orphan_chunks()

    with session_scope() as session:
        session.execute(
            text("DELETE FROM vendor_submissions WHERE vendor_id = 'V-STRESS-RACE'")
        )
    get_client().delete(
        settings.qdrant_collection,
        points_selector=build_filter(vendor_id="V-STRESS-RACE"),
        wait=True,
    )


def test_a_notification_upload_racing_a_bid_upload_keeps_the_link(pdf, clean) -> None:
    """A re-extraction landing while a bid is being filed must not leave the bid
    unlinked. An unlinked bid is invisible to the gap report for that tender."""
    ingest_notification(pdf, llm=StubLLM())

    work = [
        (lambda: ingest_notification(pdf, llm=StubLLM()),),
        (lambda: ingest_submission(
            pdf, vendor_id="V-STRESS-LINK", tender_id=TENDER_ID, llm=StubLLM()
        ),),
        (lambda: ingest_notification(pdf, llm=StubLLM()),),
    ]
    _, errors = _parallel(lambda fn: fn(), work)
    assert not errors, f"raised: {[str(e)[:200] for e in errors]}"

    with session_scope() as session:
        row = session.scalar(
            select(VendorSubmissionRow).where(
                VendorSubmissionRow.vendor_id == "V-STRESS-LINK"
            )
        )
        assert row is not None
        assert row.notification_id is not None, "the bid lost its tender link"
        notification = session.get(TenderNotificationRow, row.notification_id)
        assert notification is not None and notification.tender_id == TENDER_ID

    assert len(_notification_rows()) == 1
    assert_no_orphan_chunks()


# --------------------------------------------------------------------------- #
# Silent overwrite
# --------------------------------------------------------------------------- #
def test_a_different_tender_is_never_overwritten(pdf, clean, tmp_path) -> None:
    """Two notifications with different ids must stay two rows, and neither
    upload may purge the other's chunks."""
    other_id = f"OTHER/{uuid.uuid4().hex[:8]}"
    other_pdf = make_notification_pdf(tmp_path / "OTHER.pdf")

    ingest_notification(pdf, llm=StubLLM())
    baseline = len(_points(tender_id=TENDER_ID))

    script = StubLLM().script
    script["RawHeader"] = script["RawHeader"].model_copy(update={"tender_id": other_id})
    try:
        ingest_notification(other_pdf, llm=StubLLM(script=script))
        assert len(_points(tender_id=TENDER_ID)) == baseline, (
            "ingesting a second tender purged the first tender's chunks"
        )
        assert len(_points(tender_id=other_id)) > 0
        assert len(_notification_rows()) == 1
    finally:
        with session_scope() as session:
            session.execute(
                text("DELETE FROM tender_notifications WHERE tender_id = :t"),
                {"t": other_id},
            )
        get_client().delete(
            settings.qdrant_collection,
            points_selector=build_filter(tender_id=other_id),
            wait=True,
        )


def test_a_heavier_mixed_concurrent_load_still_converges(pdf, clean) -> None:
    """Eight writers at once, mixing tender re-extraction with bid uploads --
    the shape of a demo where someone re-uploads the notification while three
    vendors are filing bids. Four writers is enough to expose a race; eight is
    what makes the absence of one believable."""
    ingest_notification(pdf, llm=StubLLM())
    vendors = [f"V-STRESS-M{i}" for i in range(4)]

    work = (
        [(lambda: ingest_notification(pdf, llm=StubLLM()),)] * 2
        + [
            (lambda v=v: ingest_submission(
                pdf, vendor_id=v, tender_id=TENDER_ID, llm=StubLLM()
            ),)
            for v in vendors
        ]
        # Two of the bids are filed twice, concurrently with themselves.
        + [
            (lambda v=v: ingest_submission(
                pdf, vendor_id=v, tender_id=TENDER_ID, llm=StubLLM()
            ),)
            for v in vendors[:2]
        ]
    )
    _, errors = _parallel(lambda fn: fn(), work, workers=8)
    assert not errors, f"mixed concurrent load raised: {[str(e)[:200] for e in errors]}"

    assert len(_notification_rows()) == 1
    landed = {r.vendor_id for r in _submission_rows()}
    assert landed == set(vendors), f"missing bids: {set(vendors) - landed}"

    with session_scope() as session:
        for row in session.scalars(
            select(VendorSubmissionRow).where(
                VendorSubmissionRow.vendor_id.like("V-STRESS-M%")
            )
        ):
            years = [t.year for t in row.turnover]
            assert len(years) == len(set(years)), f"{row.vendor_id} has duplicate years"

    for vendor in vendors:
        assert _points(vendor_id=vendor), f"{vendor} has a row but no chunks"
    assert_no_orphan_chunks()
