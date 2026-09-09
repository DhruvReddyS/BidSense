"""API-level tests (Phase 2), driven through FastAPI's TestClient.

Ingestion is exercised with the scripted stub LLM so the route logic is tested
without an API key; the stores are real.
"""

from __future__ import annotations

from unittest.mock import patch
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.main import app
from app.config import settings
from app.db.session import engine, session_scope
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


live = pytest.mark.skipif(
    not (_services_up() and _embeddings_available()),
    reason="postgres/qdrant/embeddings unavailable",
)

TENDER_ID = NOTIFICATION_TRUTH["tender_id"]


@pytest.fixture
def client():
    client = TestClient(app)
    response = client.post("/api/auth/register", json={
        "email": f"reviewer-{uuid.uuid4()}@example.com",
        "password": "correct-horse-battery-staple",
        "role": "reviewer",
        "reviewer_code": "development-reviewer",
    })
    assert response.status_code == 201, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return client


@pytest.fixture
def pdf(tmp_path):
    return make_notification_pdf(tmp_path / "NOTIF_ITservices_01.pdf")


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


@pytest.fixture
def stubbed():
    """Route handlers construct their own LLM; patch the factory they call.

    Job submission is also made synchronous: uploads are queued to a thread pool
    in production, but a test that races a background worker is a flaky test.
    """
    from app.api import jobs as job_runner

    with patch("app.extraction.graph.get_llm", return_value=StubLLM()), patch.object(
        job_runner, "submit", job_runner.run_inline
    ):
        yield


def _await_job(client, response) -> dict:
    """Upload responses are 202 + a job id; resolve them to the finished job."""
    assert response.status_code == 202, response.text
    body = response.json()
    job = client.get(body["poll_url"]).json()
    assert job["status"] in {"succeeded", "partial", "failed"}, job
    return job


def _upload(client, pdf):
    with pdf.open("rb") as handle:
        return client.post(
            "/api/notifications",
            files={"file": (pdf.name, handle, "application/pdf")},
        )


def _upload_bid(client, pdf, vendor_id="V-04"):
    with pdf.open("rb") as handle:
        return client.post(
            "/api/submissions",
            files={"file": (pdf.name, handle, "application/pdf")},
            data={"vendor_id": vendor_id, "tender_id": TENDER_ID},
        )


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
@live
def test_health_reports_each_dependency_separately(client):
    """A partial outage must be diagnosable, not surface as a generic failure
    three screens into a user flow."""
    body = client.get("/api/health").json()
    assert body["status"] in {"ok", "degraded"}
    assert body["postgres"] is True
    assert body["qdrant"] is True
    assert "llm_provider" in body
    assert isinstance(body["ocr_missing"], list)


# --------------------------------------------------------------------------- #
# Upload
# --------------------------------------------------------------------------- #
@live
def test_upload_returns_immediately_with_a_job(client, pdf, clean, stubbed):
    """Extraction takes minutes under free-tier pacing. Holding the HTTP
    connection open for that long is a production failure, not a slow request."""
    response = _upload(client, pdf)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["poll_url"].endswith(body["job_id"])
    assert body["file_name"] == "NOTIF_ITservices_01.pdf"


@live
def test_job_reports_a_completed_extraction(client, pdf, clean, stubbed):
    job = _await_job(client, _upload(client, pdf))
    assert job["status"] == "succeeded"
    assert job["progress"] == 1.0
    assert job["steps_done"] == job["steps_total"] == 6
    assert job["tender_id"] == TENDER_ID

    result = job["result"]
    assert result["ok"] is True
    assert result["pages"] == 3
    assert result["chunks_indexed"] > 0
    assert result["extraction_errors"] == []
    assert set(result["node_timings"]) == {
        "header", "eligibility", "documents", "evaluation", "technical", "format_rules",
    }
    assert set(result["timing"]) == {"parse", "extract", "persist", "index"}
    assert result["index_state"] == "ready"

    performance = client.get("/api/review/performance")
    assert performance.status_code == 200
    pulse = performance.json()
    assert pulse["completed_jobs"] >= 1
    assert pulse["median_seconds"] is not None


@live
def test_partial_extraction_is_reported_as_partial_not_failed(client, pdf, clean):
    """A run with a failed field group still stored usable data. Calling that
    'failed' would tell the user to discard a document that is 5/6 extracted."""
    from app.api import jobs as job_runner

    with patch(
        "app.extraction.graph.get_llm", return_value=StubLLM(fail_on={"TechnicalList"})
    ), patch.object(job_runner, "submit", job_runner.run_inline):
        job = _await_job(client, _upload(client, pdf))

    assert job["status"] == "partial"
    assert len(job["result"]["extraction_errors"]) == 1
    assert job["result"]["identifier"] == TENDER_ID


def test_unknown_job_is_404(client):
    import uuid as _uuid

    assert client.get(f"/api/jobs/{_uuid.uuid4()}").status_code == 404


def test_malformed_job_id_is_400_not_500(client):
    assert client.get("/api/jobs/not-a-uuid").status_code == 400


@live
def test_uploaded_notification_appears_in_the_listing(client, pdf, clean, stubbed):
    _await_job(client, _upload(client, pdf))
    body = client.get("/api/notifications").json()
    entry = next(n for n in body["items"] if n["tender_id"] == TENDER_ID)
    assert entry["eligibility_count"] == 3
    assert entry["document_count"] == 5
    assert entry["submission_count"] == 0


@live
def test_listing_is_paginated(client, pdf, clean, stubbed):
    _await_job(client, _upload(client, pdf))
    body = client.get("/api/notifications?limit=1&offset=0").json()
    assert len(body["items"]) <= 1
    assert body["page"]["limit"] == 1
    assert body["page"]["offset"] == 0
    assert body["page"]["total"] >= 1


def test_pagination_rejects_absurd_limits(client):
    assert client.get("/api/notifications?limit=100000").status_code == 422
    assert client.get("/api/notifications?offset=-1").status_code == 422


@live
def test_full_notification_includes_provenance(client, pdf, clean, stubbed):
    _await_job(client, _upload(client, pdf))
    body = client.get(f"/api/notifications/{TENDER_ID}").json()
    turnover = next(
        c for c in body["eligibility_criteria"] if "turnover" in c["criterion"].lower()
    )
    assert turnover["threshold_amount"]["amount_inr"] == "50000000.00"
    assert turnover["provenance"]["clause_ref"] == "4.2"
    assert turnover["provenance"]["source_page"] == 2


def test_unsupported_file_type_is_rejected(client, tmp_path):
    stray = tmp_path / "notes.txt"
    stray.write_text("hello")
    with stray.open("rb") as handle:
        response = client.post(
            "/api/notifications", files={"file": ("notes.txt", handle, "text/plain")}
        )
    assert response.status_code == 415
    assert "PDF or DOCX" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Missing resources
# --------------------------------------------------------------------------- #
def test_unknown_tender_is_a_clear_404(client):
    response = client.post(
        "/api/gap-report", json={"tender_id": "DOES/NOT/EXIST", "vendor_id": "V-1"}
    )
    assert response.status_code == 404
    assert "DOES/NOT/EXIST" in response.json()["detail"]


@live
def test_unknown_vendor_against_a_real_tender_is_404(client, pdf, clean, stubbed):
    _await_job(client, _upload(client, pdf))
    response = client.post(
        "/api/gap-report", json={"tender_id": TENDER_ID, "vendor_id": "NOBODY"}
    )
    assert response.status_code == 404
    assert "NOBODY" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Gap report (Sections 4.3, 4.4, 4.6)
# --------------------------------------------------------------------------- #
@live
def test_bid_against_a_nonexistent_tender_fails_fast(client, pdf, stubbed):
    """Validated before queueing: otherwise the user waits three minutes to be
    told the tender does not exist."""
    with pdf.open("rb") as handle:
        response = client.post(
            "/api/submissions",
            files={"file": (pdf.name, handle, "application/pdf")},
            data={"vendor_id": "V-1", "tender_id": "NO/SUCH/TENDER"},
        )
    assert response.status_code == 404


@live
def test_gap_report_end_to_end(client, pdf, clean, stubbed):
    _await_job(client, _upload(client, pdf))
    _await_job(client, _upload_bid(client, pdf))

    body = client.post(
        "/api/gap-report", json={"tender_id": TENDER_ID, "vendor_id": "V-04"}
    ).json()

    report = body["report"]
    assert report["tender_id"] == TENDER_ID
    assert report["vendor_id"] == "V-04"
    assert report["items"]
    assert body["verdict"] in {"compliant", "needs_review", "not_compliant"}
    assert sum(body["counts"].values()) == len(report["items"])

    # Section 4.4: the fixture publishes no weightage, so no score may appear.
    assert report["score_preview"]["available"] is False
    assert report["score_preview"]["items"] == []

    # Section 4.6: an action list a non-technical vendor can act on.
    assert report["action_list"]
    assert all(a["action"] for a in report["action_list"])


@live
def test_gap_report_flags_the_missing_iso_certificate(client, pdf, clean, stubbed):
    """The stub bid marks the ISO certificate as not enclosed, and the tender
    requires it -- that must come back as a disqualifying gap."""
    _await_job(client, _upload(client, pdf))
    _await_job(client, _upload_bid(client, pdf))
    body = client.post(
        "/api/gap-report", json={"tender_id": TENDER_ID, "vendor_id": "V-04"}
    ).json()

    iso = next(i for i in body["report"]["items"] if "ISO" in i["requirement"])
    assert iso["status"] == "missing"
    assert iso["severity"] == "disqualifying"
    assert body["verdict"] == "not_compliant"
    assert any("ISO" in a["action"] for a in body["report"]["action_list"])


# --------------------------------------------------------------------------- #
# Ask (Section 4.5)
# --------------------------------------------------------------------------- #
@live
def test_ask_retrieves_and_cites(client, pdf, clean, stubbed):
    _await_job(client, _upload(client, pdf))

    scripted = StubLLM()
    scripted.generate_text = lambda prompt, system=None: "The EMD is Rs. 2,00,000 [1]."
    with patch("app.rag.answer.get_llm", return_value=scripted):
        body = client.post(
            "/api/ask",
            json={"question": "What is the EMD amount?", "tender_id": TENDER_ID},
        ).json()

    assert body["answer"]["answered"] is True
    assert body["answer"]["citations"]
    assert body["grounded"] is True
    citation = body["answer"]["citations"][0]
    assert citation["source_file"] == "NOTIF_ITservices_01.pdf"
    assert citation["source_page"] in (1, 2, 3)


@live
def test_ask_with_no_relevant_content_declines_rather_than_inventing(
    client, pdf, clean, stubbed
):
    _await_job(client, _upload(client, pdf))
    scripted = StubLLM()
    scripted.generate_text = lambda prompt, system=None: (
        "The uploaded documents do not state this."
    )
    with patch("app.rag.answer.get_llm", return_value=scripted):
        body = client.post(
            "/api/ask",
            json={
                "question": "What is the penalty for late delivery of bananas?",
                "tender_id": TENDER_ID,
            },
        ).json()
    assert body["answer"]["answered"] is False


def test_ask_validates_the_question(client):
    response = client.post("/api/ask", json={"question": "hi", "tender_id": "T-1"})
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Tender ids containing slashes (regression)
# --------------------------------------------------------------------------- #
@live
def test_slashed_tender_id_resolves_on_every_route(client, pdf, clean, stubbed):
    """Every real tender id in this project contains slashes -- "TENDER
    No.01/SE(Electrical)/GHMC/2024-25". The path converter needed for that is
    greedy, so a bare /{tender_id:path} route declared first swallows the
    "/submissions" suffix into the id and the sub-route 404s."""
    _await_job(client, _upload(client, pdf))
    _await_job(client, _upload_bid(client, pdf))

    encoded = TENDER_ID.replace("/", "%2F")

    detail = client.get(f"/api/notifications/{encoded}")
    assert detail.status_code == 200
    assert detail.json()["tender_id"] == TENDER_ID

    subs = client.get(f"/api/notifications/{encoded}/submissions")
    assert subs.status_code == 200, subs.text
    assert [s["vendor_id"] for s in subs.json()] == ["V-04"]


@live
def test_unencoded_slashes_also_resolve(client, pdf, clean, stubbed):
    """Browsers and fetch() do not always percent-encode the slashes in a path
    segment, so the raw form has to work too."""
    _await_job(client, _upload(client, pdf))
    _await_job(client, _upload_bid(client, pdf))

    subs = client.get(f"/api/notifications/{TENDER_ID}/submissions")
    assert subs.status_code == 200, subs.text
    assert [s["vendor_id"] for s in subs.json()] == ["V-04"]


# --------------------------------------------------------------------------- #
# Wedged jobs (regression: an extraction ran 5 hours at 0% CPU)
# --------------------------------------------------------------------------- #
@live
def test_a_wedged_job_is_reported_failed_not_running_for_ever(client):
    """Without this, a client polls a stuck job indefinitely with no way to tell
    "slow" from "stuck". The startup reaper only catches jobs orphaned by a
    restart; this catches one whose process is alive but hung."""
    from datetime import datetime, timedelta, timezone

    from app.api.jobs import STALE_AFTER_SECONDS
    from app.db.models import IngestJob, JobKind, JobStatus

    with session_scope() as session:
        job = IngestJob(
            kind=JobKind.NOTIFICATION,
            status=JobStatus.RUNNING,
            file_name="wedged.pdf",
            steps_done=2,
            steps_total=6,
            started_at=datetime.now(timezone.utc)
            - timedelta(seconds=STALE_AFTER_SECONDS + 120),
        )
        session.add(job)
        session.flush()
        job_id = str(job.id)

    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["status"] == "failed"
    assert body["stage"] == "timed out"
    assert "2/6 sections" in body["error"]
    assert "Re-upload" in body["error"]

    with session_scope() as session:
        session.execute(
            text("DELETE FROM ingest_jobs WHERE id = :i"), {"i": job_id}
        )


@live
def test_a_recently_started_job_is_left_alone(client):
    """Extraction legitimately takes minutes. The watchdog must not shoot a job
    that is merely being paced by the free-tier quota."""
    from datetime import datetime, timedelta, timezone

    from app.db.models import IngestJob, JobKind, JobStatus

    with session_scope() as session:
        job = IngestJob(
            kind=JobKind.NOTIFICATION,
            status=JobStatus.RUNNING,
            file_name="slow.pdf",
            started_at=datetime.now(timezone.utc) - timedelta(minutes=4),
        )
        session.add(job)
        session.flush()
        job_id = str(job.id)

    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "running"

    with session_scope() as session:
        session.execute(
            text("DELETE FROM ingest_jobs WHERE id = :i"), {"i": job_id}
        )


@live
def test_an_interrupted_job_can_be_replayed_from_its_retained_source(tmp_path, monkeypatch):
    from app.api import jobs as job_runner
    from app.db.models import IngestJob, JobKind, JobStatus

    source = tmp_path / "stored.pdf"
    source.write_bytes(b"retained source")
    with session_scope() as session:
        job = IngestJob(
            kind=JobKind.NOTIFICATION,
            status=JobStatus.QUEUED,
            stage="queued",
            file_name="original.pdf",
            source_hash="a" * 64,
        )
        session.add(job)
        session.flush()
        job_id = job.id

    dispatched = []
    monkeypatch.setattr(job_runner, "path_for", lambda _: source)
    monkeypatch.setattr(job_runner, "submit", lambda *args, **kwargs: dispatched.append((args, kwargs)))
    recovered, failed = job_runner.recover_interrupted_jobs()
    assert recovered >= 1 and failed == 0
    assert any(args[0] == job_id for args, _ in dispatched)
    assert next(args[2] for args, _ in dispatched if args[0] == job_id).name == "original.pdf"

    with session_scope() as session:
        session.execute(text("DELETE FROM ingest_jobs WHERE id = :i"), {"i": job_id})


# --------------------------------------------------------------------------- #
# Failure messages a user can act on
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raised", "expect"),
    [
        (
            'duplicate key value violates unique constraint "uq_vendor_per_tender"',
            "already recorded against this tender",
        ),
        (
            "gemini: every configured model has exhausted its daily free-tier quota",
            "daily free-tier quota is spent",
        ),
        (
            "gemini response was cut off at the output token limit (32768)",
            "more content than fits",
        ),
        ("403 PERMISSION_DENIED. Your project has been denied", "rejected the API key"),
        ("Unsupported format '.txt'", "PDF or DOCX"),
    ],
)
def test_known_failures_are_explained_not_dumped(raised: str, expect: str):
    """A raw IntegrityError with a database traceback tells a bidder nothing
    about what to do next, and these failures are all user-recoverable."""
    from app.api.jobs import _explain

    assert expect in _explain(RuntimeError(raised))


def test_an_unrecognised_failure_keeps_its_traceback():
    """Translating everything would hide the failures a developer needs to see."""
    from app.api.jobs import _explain

    message = _explain(ValueError("something entirely unexpected"))
    assert "ValueError" in message
    assert "something entirely unexpected" in message
