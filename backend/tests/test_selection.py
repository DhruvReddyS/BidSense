"""Page-selection tests (Phase 1).

Synthetic tests cover the mechanics. The tests marked `real` run against the
actual collected tender notifications and assert that pages known to contain a
specific clause are actually selected -- selection recall is the thing that
matters, because a page not selected is indistinguishable, downstream, from a
clause the model failed to find.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.extraction.selection import DEFAULT_CHAR_BUDGET, FIELD_GROUPS, select_pages
from app.ingest import parse_document
from app.ingest.models import ExtractionMethod, PageText, ParsedDocument
from app.schemas.common import DocumentKind

DATA = Path(__file__).resolve().parents[2] / "data" / "notifications"

real = pytest.mark.skipif(
    not DATA.exists() or not any(DATA.glob("*.pdf")),
    reason="no collected tender notifications in data/notifications/",
)


def synthetic(pages: list[str]) -> ParsedDocument:
    return ParsedDocument(
        file_name="synthetic.pdf",
        doc_kind=DocumentKind.NOTIFICATION,
        pages=[
            PageText(page_number=i, text=t, method=ExtractionMethod.NATIVE)
            for i, t in enumerate(pages, start=1)
        ],
    )


# --------------------------------------------------------------------------- #
# Mechanics
# --------------------------------------------------------------------------- #
def test_short_documents_are_passed_through_whole():
    """Selection is a cost for long documents and a risk for short ones."""
    document = synthetic(["page one text", "page two text"])
    text, pages = select_pages(document, "eligibility")
    assert pages == [1, 2]
    assert "page one" in text and "page two" in text


def test_long_document_is_reduced_to_the_relevant_pages():
    filler = "General conditions of contract. " * 400
    eligibility = (
        "4.2 The bidder shall have an average annual turnover of not less than "
        "Rs. 5 Cr during the last three financial years. Eligibility criteria apply. "
    ) * 5
    document = synthetic([filler] * 30 + [eligibility] + [filler] * 30)

    text, pages = select_pages(document, "eligibility", use_embeddings=False)
    assert 31 in pages, "the one eligibility page must be selected"
    assert len(pages) < document.page_count
    assert len(text) <= DEFAULT_CHAR_BUDGET


def test_selection_preserves_page_order_and_markers():
    """A clause referring to "the above" needs its neighbours still before it,
    and source_page provenance depends on the markers being right."""
    filler = "Boilerplate. " * 500
    document = synthetic(
        [filler, "turnover eligibility criteria", filler, "eligibility qualification", filler] * 8
    )
    text, pages = select_pages(document, "eligibility", use_embeddings=False)
    assert pages == sorted(pages)
    markers = [int(m) for m in __import__("re").findall(r"\[PAGE (\d+)\]", text)]
    assert markers == sorted(markers) == pages


def test_header_group_always_keeps_the_front_matter():
    """Identifiers and dates live in the front matter of every Indian tender,
    regardless of how cue-dense those pages look."""
    filler = "Technical specification clause. " * 500
    document = synthetic([filler] * 60)
    _, pages = select_pages(document, "header", use_embeddings=False)
    assert {1, 2, 3} <= set(pages)


def test_budget_is_respected():
    heavy = "eligibility turnover qualification experience " * 300
    document = synthetic([heavy] * 80)
    text, _ = select_pages(document, "eligibility", use_embeddings=False, char_budget=20_000)
    assert len(text) <= 20_000 + 2000  # markers add a little


def test_unknown_group_falls_back_to_the_whole_document():
    document = synthetic(["a" * 100_000, "b" * 100_000])
    text, pages = select_pages(document, "not_a_real_group")
    assert pages == [1, 2]


def test_no_cue_matches_still_returns_something():
    """An empty extraction is the worst possible outcome -- send the head of the
    document rather than nothing."""
    document = synthetic(["zzz " * 5000] * 40)
    text, pages = select_pages(document, "evaluation", use_embeddings=False)
    assert pages and text


def test_every_graph_node_has_a_field_group():
    """A node with no entry silently falls back to the full document, which is
    exactly the truncation this module exists to prevent."""
    from app.extraction.graph import _NOTIFICATION_NODES, _VENDOR_NODES

    for node in {**_NOTIFICATION_NODES, **_VENDOR_NODES}:
        assert node in FIELD_GROUPS, f"no page-selection cues defined for node {node!r}"


# --------------------------------------------------------------------------- #
# Recall against the real collected tenders
# --------------------------------------------------------------------------- #
@real
def test_real_tenders_reduce_below_a_workable_context():
    for path in sorted(DATA.glob("*.pdf")):
        document = parse_document(path, DocumentKind.NOTIFICATION)
        for group in ("header", "eligibility", "documents"):
            text, pages = select_pages(document, group, use_embeddings=False)
            assert len(text) <= DEFAULT_CHAR_BUDGET + 5000, (
                f"{path.name}/{group}: {len(text)} chars exceeds the budget"
            )
            assert pages, f"{path.name}/{group}: selected no pages"


@real
def test_iitism_turnover_clause_page_is_selected():
    """IIT (ISM) Dhanbad states its turnover requirement on page 7 -- "Average
    Annual Financial Turnover during the last 3 (three) financial years". If
    that page is not selected, the eligibility extractor cannot possibly find
    the criterion."""
    path = DATA / "NOTIF_civilworks_01.pdf"
    if not path.exists():
        pytest.skip("NOTIF_civilworks_01.pdf not collected")

    document = parse_document(path, DocumentKind.NOTIFICATION)
    truth_page = next(
        p.page_number
        for p in document.pages
        if "average annual financial turnover" in p.combined_text().lower()
    )
    _, pages = select_pages(document, "eligibility", use_embeddings=False)
    assert truth_page in pages


@real
def test_ghmc_emd_page_is_selected_for_the_header_group():
    """GHMC prints its EMD (Rs. 2,98,720.00) in the front-matter data sheet."""
    path = DATA / "NOTIF_supply_01.pdf"
    if not path.exists():
        pytest.skip("NOTIF_supply_01.pdf not collected")

    document = parse_document(path, DocumentKind.NOTIFICATION)
    truth_page = next(
        p.page_number for p in document.pages if "2,98,720" in p.combined_text()
    )
    _, pages = select_pages(document, "header", use_embeddings=False)
    assert truth_page in pages


@real
def test_document_checklist_page_is_selected():
    """IIT (ISM) lists required documents on page 13 ("Sl. Name of Documents")."""
    path = DATA / "NOTIF_civilworks_01.pdf"
    if not path.exists():
        pytest.skip("NOTIF_civilworks_01.pdf not collected")

    document = parse_document(path, DocumentKind.NOTIFICATION)
    truth_pages = [
        p.page_number
        for p in document.pages
        if "name of documents" in p.combined_text().lower()
    ]
    _, pages = select_pages(document, "documents", use_embeddings=False)
    assert truth_pages, "expected a document checklist page in this tender"
    assert set(truth_pages) & set(pages)
