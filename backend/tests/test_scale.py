"""Behaviour that only shows up on large documents and large tenders.

The bid set runs from 60 to 173 pages, and the GHMC tender asks for 49
documents. Several defects were invisible at nine pages and obvious at a
hundred: redundant embedding work, whole-document upserts, and leaked uploads.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.compliance.matching import _clear_vector_cache, _VECTORS, match_document
from app.extraction.persist import UPSERT_BATCH

DATA = Path(__file__).resolve().parents[2] / "data" / "vendors"

real = pytest.mark.skipif(
    not DATA.exists() or not any(DATA.glob("*.pdf")),
    reason="no generated vendor bids in data/vendors/",
)


# --------------------------------------------------------------------------- #
# Embedding reuse
# --------------------------------------------------------------------------- #
def test_document_names_are_embedded_once_not_once_per_requirement():
    """A gap report checks every requirement against the same enclosure list.
    Caching per (requirement, haystack) pair re-embeds that list once per
    requirement: 49 requirements against 50 documents becomes ~2,500 embeddings
    where 99 distinct ones exist, and the report takes minutes."""
    # Deliberately share no identifying vocabulary: the exact, alias and lexical
    # tiers all short-circuit before the model, and this test is about how often
    # the model is called. Names that resolve lexically would measure nothing.
    requirements = [f"Kestrel{i} widget attestation" for i in range(20)]
    submitted = [f"Marlin{i} gizmo confirmation" for i in range(25)]

    _clear_vector_cache()
    embedded: list[str] = []
    batches: list[int] = []

    def spy(texts, **kw):
        embedded.extend(texts)
        batches.append(len(texts))
        return [[0.1] * 768 for _ in texts]

    with patch("app.vector.embeddings.embed_passages", side_effect=spy):
        for requirement in requirements:
            match_document(requirement, submitted)

    distinct = len(set(embedded))
    assert distinct == len(embedded), "a name was embedded more than once"
    assert distinct == len(requirements) + len(submitted), (
        f"expected {len(requirements) + len(submitted)} embeddings, got {distinct}"
    )
    # The naive implementation would be requirements x (1 + submitted).
    assert distinct < len(requirements) * len(submitted) / 4

    # The haystack arrives as ONE batch, not one call per candidate. Correct-
    # but-separate calls are a forward pass each: measured on 85 real document
    # names, 85 calls of one take 2,590 ms against 250 ms for a single batch.
    #
    # The remaining calls here are single requirement names, because this test
    # drives `match_document` one requirement at a time. A caller that knows its
    # whole working set does better --
    # `test_a_whole_gap_report_costs_one_embedding_call` covers that, and it is
    # the path the product actually uses.
    assert max(batches) == len(submitted) + 1, (
        f"the candidate list was not embedded as one batch: {batches}"
    )
    assert sum(1 for b in batches if b > 1) == 1


def test_repeated_reports_reuse_the_cache():
    """Checking a second vendor against the same tender must not re-embed the
    tender's requirement names."""
    requirements = [f"Kestrel{i} widget attestation" for i in range(10)]
    _clear_vector_cache()
    embedded: list[str] = []

    def spy(texts, **kw):
        embedded.extend(texts)
        return [[0.1] * 768 for _ in texts]

    with patch("app.vector.embeddings.embed_passages", side_effect=spy):
        for requirement in requirements:
            match_document(requirement, ["Marlin gizmo confirmation"])
        first = len(embedded)
        for requirement in requirements:
            match_document(requirement, ["Marlin gizmo confirmation"])
        second = len(embedded)

    assert second == first, "the second pass recomputed embeddings"
    assert first > 0, "nothing was embedded; the test is measuring nothing"


# --------------------------------------------------------------------------- #
# Indexing at scale
# --------------------------------------------------------------------------- #
def test_upserts_are_batched():
    """A whole-document upsert of a few hundred points is a multi-megabyte
    request, and the failure would land after the embedding work was paid for."""
    from app.extraction.persist import _index
    from app.ingest.chunking import Chunk
    from app.schemas.common import ChunkSection, DocumentKind

    chunks = [
        Chunk(text=f"passage {i}", page_number=1 + i // 10, chunk_index=i,
              section=ChunkSection.GENERAL)
        for i in range(UPSERT_BATCH * 2 + 7)
    ]

    calls: list[int] = []
    with patch(
        "app.extraction.persist.embed_passages",
        side_effect=lambda texts, **kw: [[0.0] * 768 for _ in texts],
    ), patch("app.extraction.persist.get_client") as client:
        client.return_value.upsert.side_effect = lambda *a, **kw: calls.append(
            len(kw["points"])
        )
        total = _index(
            chunks, {"doc_kind": DocumentKind.SUBMISSION}, owner_key="x"
        )

    assert total == len(chunks)
    assert len(calls) == 3, f"expected 3 batches, got {len(calls)}"
    assert max(calls) <= UPSERT_BATCH


# --------------------------------------------------------------------------- #
# Uploads
# --------------------------------------------------------------------------- #
def test_a_failed_queue_does_not_leak_the_upload(tmp_path):
    """The worker deletes the upload when it finishes. If queueing fails there
    is no worker, so the temp directory would be orphaned -- a
    tens-of-megabytes leak per failed upload."""
    from fastapi.testclient import TestClient

    from app.api.main import app
    from tests.doc_factory import make_notification_pdf

    pdf = make_notification_pdf(tmp_path / "NOTIF.pdf")
    leaked: list[Path] = []

    def explode(kind, file_name, **kwargs):
        raise RuntimeError("database unavailable")

    with patch("app.api.jobs.create_job", side_effect=explode), patch(
        "app.api.routes.shutil.rmtree",
        side_effect=lambda p, **kw: leaked.append(Path(p)),
    ):
        with pdf.open("rb") as handle:
            response = TestClient(app, raise_server_exceptions=False).post(
                "/api/notifications",
                files={"file": (pdf.name, handle, "application/pdf")},
            )

    assert response.status_code == 500
    assert leaked, "the upload directory was not cleaned up"


# --------------------------------------------------------------------------- #
# Page selection recall on genuinely large bids
# --------------------------------------------------------------------------- #
@real
@pytest.mark.parametrize(
    "stem", ["VENDOR_civilworks_02_03", "VENDOR_supply_01_03", "VENDOR_civilworks_01_03"]
)
def test_the_enclosure_checklist_is_selected_from_a_large_bid(stem: str):
    """The checklist sits near the end of a 173-page bid. If page selection
    misses it, extraction finds no enclosed documents and every vendor is
    reported as missing everything."""
    from app.extraction.selection import select_pages
    from app.ingest import parse_document
    from app.schemas.common import DocumentKind

    path = DATA / f"{stem}.pdf"
    if not path.exists():
        pytest.skip(f"{stem} not generated")

    document = parse_document(path, DocumentKind.SUBMISSION)
    truth = [p.page_number for p in document.pages if "[X]" in p.combined_text()]
    assert truth, "expected an enclosure checklist in the generated bid"

    _, selected = select_pages(document, "submitted_documents", use_embeddings=False)
    assert set(truth) & set(selected), (
        f"{stem}: checklist on {truth} not among selected {selected[:12]}"
    )


@real
@pytest.mark.parametrize(
    "stem", ["VENDOR_civilworks_02_02", "VENDOR_supply_01_02", "VENDOR_civilworks_01_04"]
)
def test_the_turnover_table_is_selected_from_a_large_bid(stem: str):
    from app.extraction.selection import select_pages
    from app.ingest import parse_document
    from app.schemas.common import DocumentKind

    path = DATA / f"{stem}.pdf"
    if not path.exists():
        pytest.skip(f"{stem} not generated")

    document = parse_document(path, DocumentKind.SUBMISSION)
    truth = [
        p.page_number for p in document.pages if "Financial Year" in p.combined_text()
    ]
    assert truth

    _, selected = select_pages(document, "turnover", use_embeddings=False)
    assert set(truth) & set(selected)


@real
def test_large_bids_stay_within_the_extraction_budget():
    """Selection exists so a 173-page bid still fits a model's context."""
    from app.extraction.selection import DEFAULT_CHAR_BUDGET, select_pages
    from app.ingest import parse_document
    from app.schemas.common import DocumentKind

    path = DATA / "VENDOR_civilworks_02_01.pdf"
    if not path.exists():
        pytest.skip("large bid not generated")

    document = parse_document(path, DocumentKind.SUBMISSION)
    assert document.page_count > 100, "expected a genuinely large bid"

    for group in ("vendor_header", "turnover", "certifications",
                  "past_projects", "submitted_documents"):
        text, pages = select_pages(document, group, use_embeddings=False)
        assert len(text) <= DEFAULT_CHAR_BUDGET + 5000, f"{group}: {len(text)} chars"
        assert pages


def test_a_whole_gap_report_costs_one_embedding_call():
    """The end-to-end property, at the call site rather than inside the matcher.

    The matcher batches what it is given, but a caller that hands it one
    requirement at a time still produces one forward pass per requirement --
    measured at 37 calls for a single GHMC report, 36 of them a batch of one.
    The gap report knows its whole working set before it starts, so it settles
    the cheap tiers first and embeds only the remainder, together.
    """
    from unittest.mock import patch

    from app.compliance.gap import build_gap_report
    from app.compliance.matching import _clear_vector_cache
    from app.schemas.common import Provenance
    from app.schemas.notification import MandatoryDocument, TenderNotification
    from app.schemas.submission import SubmittedDocument, VendorSubmission

    prov = Provenance(clause_ref="1", source_page=1, source_snippet="x")
    notification = TenderNotification(
        tender_id="T-1", title="t", issuing_authority="a",
        mandatory_documents=[
            MandatoryDocument(doc_name=f"Kestrel{i} widget attestation", provenance=prov)
            for i in range(20)
        ],
    )
    submission = VendorSubmission(
        vendor_id="V-1", vendor_name="V", tender_id="T-1",
        documents_submitted=[
            SubmittedDocument(doc_name=f"Marlin{i} gizmo confirmation", present=True, provenance=prov)
            for i in range(15)
        ],
    )

    batches: list[int] = []

    def spy(texts, **kw):
        batches.append(len(texts))
        return [[0.1] * 768 for _ in texts]

    _clear_vector_cache()
    with patch("app.vector.embeddings.embed_passages", side_effect=spy):
        build_gap_report(notification, submission)

    assert len(batches) == 1, f"a report should cost one embedding call, got {batches}"


def test_names_settled_by_the_cheap_tiers_are_never_embedded():
    """Pre-embedding everything up front would also be one call, and would pay
    for the names that exact/alias/vocabulary already resolved -- on the GHMC
    tender that is 44 of 49."""
    from unittest.mock import patch

    from app.compliance.gap import build_gap_report
    from app.compliance.matching import _clear_vector_cache
    from app.schemas.common import Provenance
    from app.schemas.notification import MandatoryDocument, TenderNotification
    from app.schemas.submission import SubmittedDocument, VendorSubmission

    prov = Provenance(clause_ref="1", source_page=1, source_snippet="x")
    notification = TenderNotification(
        tender_id="T-1", title="t", issuing_authority="a",
        mandatory_documents=[
            MandatoryDocument(doc_name="PAN Card", provenance=prov),
            MandatoryDocument(doc_name="GST Registration Certificate", provenance=prov),
        ],
    )
    submission = VendorSubmission(
        vendor_id="V-1", vendor_name="V", tender_id="T-1",
        documents_submitted=[
            SubmittedDocument(doc_name="Permanent Account Number", present=True, provenance=prov),
            SubmittedDocument(doc_name="GST Registration Certificate", present=True, provenance=prov),
        ],
    )

    embedded: list[str] = []

    def spy(texts, **kw):
        embedded.extend(texts)
        return [[0.1] * 768 for _ in texts]

    _clear_vector_cache()
    with patch("app.vector.embeddings.embed_passages", side_effect=spy):
        report = build_gap_report(notification, submission)

    assert all(i.status.value == "match" for i in report.items)
    assert embedded == [], f"the model was called for names the tables resolved: {embedded}"
