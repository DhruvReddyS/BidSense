"""Corrigendum extraction, diff, and staleness (Section 5.6, Part 1 slice).

Three things are tested and one is tested for its ABSENCE:

  diff        the amendment is compared against the parent's stored values, in
              code. `old_value` never comes from the model.
  staleness   a vendor who has already seen a gap report is told the tender moved.
  re-check    an explicit re-check clears the banner; merely viewing does not.
  NOT DONE    no verdict is recomputed, no vendor is re-eliminated, nothing is
              propagated. `test_a_corrigendum_does_not_silently_change_a_verdict`
              is a test that Part 2's behaviour has NOT leaked into Part 1.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.corrigendum.diff import UNMAPPED, diff_corrigendum
from app.corrigendum.staleness import mark_report_generated, staleness_for
from app.db.session import engine, session_scope
from app.extraction import llm_schemas as raw
from app.schemas.common import MoneyAmount, Provenance
from app.schemas.notification import TenderNotification

DATA = Path(__file__).resolve().parents[2] / "data"
KEY_PATH = DATA / "tracking_corrigenda.json"

def _reviewer_client():
    from fastapi.testclient import TestClient
    from app.api.main import app
    client=TestClient(app)
    response=client.post("/api/auth/register",json={"email":f"corr-{uuid.uuid4()}@example.com","password":"correct-horse-battery-staple","role":"reviewer","reviewer_code":"development-reviewer"})
    client.headers["Authorization"]=f"Bearer {response.json()['access_token']}"
    return client


def _live() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


live = pytest.mark.skipif(not _live(), reason="postgres not running")


def _parent() -> TenderNotification:
    return TenderNotification(
        tender_id="CMU-12011/17/2026-CMU",
        title="Construction of boundary wall",
        issuing_authority="IIT (ISM) Dhanbad",
        submission_deadline=date(2026, 8, 22),
        pre_bid_query_deadline=date(2026, 8, 19),
        emd_amount=MoneyAmount(raw_text="Rs. 31,500/-"),
        contract_value_estimate=MoneyAmount(raw_text="Rs. 12,56,561/-"),
    )


def _cited(**kwargs) -> raw.RawCorrigendumChange:
    kwargs.setdefault("source_page", 2)
    kwargs.setdefault("source_snippet", "x")
    return raw.RawCorrigendumChange(**kwargs)


# --------------------------------------------------------------------------- #
# The diff
# --------------------------------------------------------------------------- #
def test_a_restated_deadline_is_diffed_against_what_we_already_hold() -> None:
    result = diff_corrigendum(
        _parent(),
        raw.RawCorrigendumHeader(
            corrigendum_id="CORRIGENDUM No. 1",
            parent_tender_id="CMU-12011/17/2026-CMU",
            issued_date="2026-08-12",
            submission_deadline="2026-09-05",
        ),
        [],
    )
    change = next(c for c in result.changed_fields if c.field_path == "submission_deadline")
    assert change.old_value == "2026-08-22", "the old value must come from our database"
    assert change.new_value == "2026-09-05"


def test_a_field_the_corrigendum_does_not_mention_is_unchanged_not_cleared() -> None:
    """Null means "this corrigendum says nothing about that field". Treating it
    as a change to null would report an amendment that never happened."""
    result = diff_corrigendum(
        _parent(),
        raw.RawCorrigendumHeader(submission_deadline="2026-09-05"),
        [],
    )
    paths = {c.field_path for c in result.changed_fields}
    assert paths == {"submission_deadline"}
    assert "emd_amount" not in paths
    assert "pre_bid_query_deadline" not in paths


def test_a_restated_value_that_did_not_change_is_not_reported_as_a_change() -> None:
    """Corrigenda reprint fields they did not amend. Reporting those would put a
    stale-tender banner in front of every vendor for a no-op."""
    result = diff_corrigendum(
        _parent(),
        raw.RawCorrigendumHeader(
            submission_deadline="2026-08-22",       # identical to the parent
            emd_amount_raw="Rs. 31,500/-",
        ),
        [],
    )
    assert result.changed_fields == []


def test_the_same_amount_printed_differently_is_not_a_change() -> None:
    """"Rs. 31,500/-" and "Rs. 31500" are the same money. A string comparison
    here would flag an amendment that did not occur."""
    result = diff_corrigendum(
        _parent(), raw.RawCorrigendumHeader(emd_amount_raw="Rs. 31500"), []
    )
    assert result.changed_fields == []


def test_a_genuine_emd_change_is_reported_with_both_printed_forms() -> None:
    result = diff_corrigendum(
        _parent(), raw.RawCorrigendumHeader(emd_amount_raw="Rs. 25,200/-"), []
    )
    change = next(c for c in result.changed_fields if c.field_path == "emd_amount")
    assert change.old_value == "Rs. 31,500/-"
    assert change.new_value == "Rs. 25,200/-"


def test_a_prose_change_is_classified_by_subject_and_value_shape() -> None:
    result = diff_corrigendum(
        _parent(),
        raw.RawCorrigendumHeader(),
        [
            _cited(subject="Average annual turnover", new_value="Rs. 6 Cr", old_value="Rs. 5 Cr"),
        ],
    )
    change = result.changed_fields[0]
    assert change.field_path == "eligibility_criteria.turnover"
    assert (change.old_value, change.new_value) == ("Rs. 5 Cr", "Rs. 6 Cr")


def test_a_change_that_reads_like_a_field_but_is_not_stays_unmapped() -> None:
    """"the pre-bid MEETING shall be held in hybrid mode" matches the pre-bid
    pattern but is not an amendment to the pre-bid DEADLINE.

    Getting this wrong is not cosmetic: it classified onto a field the same
    corrigendum had already amended, was deduplicated away as a restatement, and
    the change vanished from the vendor's banner entirely.
    """
    result = diff_corrigendum(
        _parent(),
        raw.RawCorrigendumHeader(pre_bid_query_deadline="2026-08-29"),
        [
            _cited(
                subject="Mode of conducting the pre-bid meeting",
                new_value="hybrid mode, with a video-conference link",
            )
        ],
    )
    paths = [c.field_path for c in result.changed_fields]
    assert "pre_bid_query_deadline" in paths
    assert any(p.startswith("unmapped:") for p in paths), (
        f"the meeting-mode change was lost: {paths}"
    )


def test_an_unmapped_change_is_reported_rather_than_dropped() -> None:
    result = diff_corrigendum(
        _parent(),
        raw.RawCorrigendumHeader(),
        [_cited(subject="Site inspection is now compulsory", new_value="compulsory")],
    )
    assert len(result.changed_fields) == 1
    assert result.changed_fields[0].field_path.startswith("unmapped:")


def test_the_model_is_never_asked_what_the_old_value_was() -> None:
    """Structural. `old_value` for a restated field is read from the parent, and
    a diff that took the model's word for it could not be audited."""
    import inspect

    from app.corrigendum import diff as diff_module

    source = inspect.getsource(diff_module._restated_fields)
    assert "getattr(parent," in source
    assert "header.old" not in source


# --------------------------------------------------------------------------- #
# Against the generated corrigendum's answer key
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not KEY_PATH.exists(), reason="run scripts.make_corrigendum first")
def test_the_generated_corrigendum_diffs_to_its_answer_key() -> None:
    """The amendments were fixed before the prose (Section 9.2.1). This asserts
    the diff against that key rather than against a re-read of our own output."""
    key = json.loads(KEY_PATH.read_text())
    entry = key["CMU-12011/17/2026-CMU"]

    header = raw.RawCorrigendumHeader(
        corrigendum_id=entry["corrigendum_id"],
        parent_tender_id="CMU-12011/17/2026-CMU",
        issued_date=entry["issued_date"],
        submission_deadline=entry["amendments"]["submission_deadline"]["new"],
        pre_bid_query_deadline=entry["amendments"]["pre_bid_query_deadline"]["new"],
        emd_amount_raw=entry["amendments"]["emd_amount"]["new"],
    )
    result = diff_corrigendum(_parent(), header, [])

    produced = {c.field_path: c.new_value for c in result.changed_fields}
    assert set(produced) == set(entry["amendments"])
    assert produced["emd_amount"] == "Rs. 25,200/-"
    assert produced["submission_deadline"] == "2026-09-05"
    assert produced["pre_bid_query_deadline"] == "2026-08-29"


# --------------------------------------------------------------------------- #
# Staleness
# --------------------------------------------------------------------------- #
@live
def test_a_corrigendum_flags_an_existing_report_stale(corrigendum_fixture) -> None:
    notification_id, submission, _ = corrigendum_fixture
    with session_scope() as session:
        row = session.get(type(submission), submission.id)
        state = staleness_for(session, notification_id, row)

    assert state.stale
    assert state.corrigendum_id == "TEST-CORR-1"
    assert "recheck your compliance" in state.banner
    assert "EMD amount" in state.banner or "deadline" in state.banner


@live
def test_a_vendor_who_never_ran_a_report_is_not_flagged_stale(corrigendum_fixture) -> None:
    """Nothing is out of date if nothing was ever read. A banner on a first
    visit would be noise about a report the vendor has not seen."""
    notification_id, submission, _ = corrigendum_fixture
    with session_scope() as session:
        row = session.get(type(submission), submission.id)
        row.last_gap_report_at = None
        session.flush()
        state = staleness_for(session, notification_id, row)
    assert not state.stale
    assert state.banner is None


@live
def test_an_explicit_recheck_clears_the_flag(corrigendum_fixture) -> None:
    notification_id, submission, _ = corrigendum_fixture
    with session_scope() as session:
        row = session.get(type(submission), submission.id)
        assert staleness_for(session, notification_id, row).stale

        mark_report_generated(row)
        session.flush()
        assert not staleness_for(session, notification_id, row).stale


@live
def test_a_corrigendum_older_than_the_report_does_not_flag_it(corrigendum_fixture) -> None:
    notification_id, submission, corrigendum = corrigendum_fixture
    with session_scope() as session:
        row = session.get(type(submission), submission.id)
        row.last_gap_report_at = datetime.now(timezone.utc) + timedelta(hours=1)
        session.flush()
        assert not staleness_for(session, notification_id, row).stale


@live
def test_a_corrigendum_does_not_silently_change_a_verdict(corrigendum_fixture) -> None:
    """The Part 2 boundary, asserted as an absence.

    Amending the EMD must not re-run anybody's compliance, alter a stored
    status, or set an elimination reason. Part 1's answer to "the tender
    changed" is to say so, not to quietly decide again on the vendor's behalf.
    """
    notification_id, submission, _ = corrigendum_fixture
    with session_scope() as session:
        row = session.get(type(submission), submission.id)
        assert row.status.value == "pending"
        assert row.elimination_reason is None
        # And the corrigendum has not been marked applied -- nothing propagated.
        from app.db.models import CorrigendumRow

        stored = session.scalars(
            select(CorrigendumRow).where(CorrigendumRow.notification_id == notification_id)
        ).all()
        assert stored and all(not c.applied for c in stored)


@pytest.fixture
def corrigendum_fixture():
    """A notification, a bid whose report has been seen, and a later corrigendum."""
    from app.db.models import (
        ChangedFieldRow,
        CorrigendumRow,
        TenderNotificationRow,
        VendorSubmissionRow,
    )

    tender_id = "CORR-TEST/2026/001"
    with session_scope() as session:
        session.execute(
            text("DELETE FROM tender_notifications WHERE tender_id = :t"), {"t": tender_id}
        )

    with session_scope() as session:
        notification = TenderNotificationRow(
            tender_id=tender_id, title="Corrigendum test", issuing_authority="Test"
        )
        session.add(notification)
        session.flush()

        submission = VendorSubmissionRow(
            vendor_id="V-CORR", vendor_name="Corr Test Ltd", notification_id=notification.id
        )
        session.add(submission)
        session.flush()
        # The vendor has already read a report; that is what a later amendment
        # makes out of date.
        submission.last_gap_report_at = datetime.now(timezone.utc) - timedelta(days=1)

        corrigendum = CorrigendumRow(
            corrigendum_id="TEST-CORR-1",
            notification_id=notification.id,
            parent_tender_id=tender_id,
            issued_date=date(2026, 8, 12),
        )
        corrigendum.changed_fields.append(
            ChangedFieldRow(
                field_path="emd_amount", old_value="Rs. 31,500/-", new_value="Rs. 25,200/-"
            )
        )
        session.add(corrigendum)
        session.flush()
        ids = (notification.id, submission, corrigendum)

    yield ids

    with session_scope() as session:
        session.execute(
            text("DELETE FROM tender_notifications WHERE tender_id = :t"), {"t": tender_id}
        )


# --------------------------------------------------------------------------- #
# The API surface the banner and the re-check button use
# --------------------------------------------------------------------------- #
@live
def test_the_gap_report_endpoint_surfaces_the_banner_and_clears_it_on_recheck(
    corrigendum_fixture,
) -> None:
    from fastapi.testclient import TestClient

    from app.api.main import app

    notification_id, submission, _ = corrigendum_fixture
    client = _reviewer_client()
    body = {"tender_id": "CORR-TEST/2026/001", "vendor_id": "V-CORR"}

    first = client.post("/api/gap-report", json=body)
    assert first.status_code == 200, first.text
    staleness = first.json()["staleness"]
    assert staleness["stale"] is True
    assert "recheck your compliance" in staleness["banner"]
    assert "EMD amount" in staleness["changed_fields"]

    # Viewing again does NOT clear it -- the vendor may not have acted on it yet.
    again = client.post("/api/gap-report", json=body)
    assert again.json()["staleness"]["stale"] is True

    # The one-click re-check does.
    rechecked = client.post("/api/gap-report", json={**body, "acknowledge_amendments": True})
    assert rechecked.json()["staleness"]["stale"] is False


@live
def test_the_corrigenda_endpoint_lists_the_diff(corrigendum_fixture) -> None:
    from fastapi.testclient import TestClient

    from app.api.main import app

    client = _reviewer_client()
    response = client.get("/api/notifications/CORR-TEST/2026/001/corrigenda")
    assert response.status_code == 200, response.text
    listing = response.json()
    assert len(listing) == 1
    assert listing[0]["corrigendum_id"] == "TEST-CORR-1"

    change = listing[0]["changed_fields"][0]
    assert change["field_path"] == "emd_amount"
    assert change["label"] == "EMD amount", "the UI needs a readable name, not a dotted path"
    assert (change["old_value"], change["new_value"]) == ("Rs. 31,500/-", "Rs. 25,200/-")


@live
def test_a_corrigendum_for_an_unknown_tender_is_refused_before_any_extraction() -> None:
    """Queueing it would spend LLM calls to find out three minutes later that
    there is nothing to diff against."""
    from fastapi.testclient import TestClient

    from app.api.main import app

    client = _reviewer_client()
    response = client.post(
        "/api/corrigenda",
        files={"file": ("c.pdf", b"%PDF-1.4 not a real pdf", "application/pdf")},
        data={"tender_id": "NO/SUCH/TENDER/2026"},
    )
    assert response.status_code == 404
