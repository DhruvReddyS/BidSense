"""API-level tests (Phase 2), driven through FastAPI's TestClient.

Ingestion is exercised with the scripted stub LLM so the route logic is tested
without an API key; the stores are real.
"""

from __future__ import annotations

from unittest.mock import patch

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
    return TestClient(app)


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
    """Route handlers construct their own LLM; patch the factory they call."""
    with patch("app.extraction.graph.get_llm", return_value=StubLLM()):
        yield


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
def test_upload_notification_returns_extraction_summary(client, pdf, clean, stubbed):
    response = _upload(client, pdf)
    assert response.status_code == 201
    body = response.json()
    assert body["ok"] is True
    assert body["identifier"] == TENDER_ID
    assert body["pages"] == 3
    assert body["chunks_indexed"] > 0
    assert body["extraction_errors"] == []


@live
def test_uploaded_notification_appears_in_the_listing(client, pdf, clean, stubbed):
    _upload(client, pdf)
    listing = client.get("/api/notifications").json()
    entry = next(n for n in listing if n["tender_id"] == TENDER_ID)
    assert entry["eligibility_count"] == 3
    assert entry["document_count"] == 5
    assert entry["submission_count"] == 0


@live
def test_full_notification_includes_provenance(client, pdf, clean, stubbed):
    _upload(client, pdf)
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
    _upload(client, pdf)
    response = client.post(
        "/api/gap-report", json={"tender_id": TENDER_ID, "vendor_id": "NOBODY"}
    )
    assert response.status_code == 404
    assert "NOBODY" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Gap report (Sections 4.3, 4.4, 4.6)
# --------------------------------------------------------------------------- #
@live
def test_gap_report_end_to_end(client, pdf, clean, stubbed):
    _upload(client, pdf)
    assert _upload_bid(client, pdf).status_code == 201

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
    _upload(client, pdf)
    _upload_bid(client, pdf)
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
    _upload(client, pdf)

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
    _upload(client, pdf)
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
