"""Citation click-through: opening a cited passage on its source page.

A citation that is only a label -- "page 5, clause 1.1" -- asks the vendor to
take our word for it. This is what turns it into something they can check, and
the tests split into two halves accordingly: that the right passage is found,
and that a passage which cannot be found is NOT marked. A confidently wrong
highlight points a vendor at the wrong clause, which is worse than none.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.documents.render import MIN_MATCH_RATIO, find_highlight_boxes, render_page
from app.documents.store import content_hash, path_for, store_document

DATA = Path(__file__).resolve().parents[2] / "data" / "notifications"
real = pytest.mark.skipif(
    not (DATA / "NOTIF_civilworks_01.pdf").exists(), reason="no collected tenders"
)


def _words(*pairs: tuple[str, float]) -> list[dict]:
    """Words laid out left to right on one line."""
    return [
        {"text": text, "x0": x, "x1": x + 20, "top": top, "bottom": top + 10}
        for text, (x, top) in ((t, (i * 25.0, 100.0)) for i, (t, _) in enumerate(pairs))
        for _ in [0]
    ]


def _line(text: str, top: float = 100.0) -> list[dict]:
    out = []
    for index, token in enumerate(text.split()):
        out.append({"text": token, "x0": index * 25.0, "x1": index * 25.0 + 20,
                    "top": top, "bottom": top + 10})
    return out


# --------------------------------------------------------------------------- #
# Finding the passage
# --------------------------------------------------------------------------- #
def test_an_exact_snippet_is_located() -> None:
    words = _line("The Earnest Money Deposit shall be Rs. 31,500 payable to the Director")
    boxes = find_highlight_boxes(words, "Earnest Money Deposit shall be Rs. 31,500")
    assert len(boxes) == 1
    x0, top, x1, bottom = boxes[0]
    assert x0 < x1 and top < bottom


def test_a_snippet_whose_whitespace_changed_still_matches() -> None:
    """"Verbatim" does not survive a trip through PDF text extraction with its
    whitespace intact, so an exact-string matcher finds nothing on real files."""
    words = _line("Average Annual financial turnover during the last 3 three financial years")
    boxes = find_highlight_boxes(
        words, "Average  Annual\nfinancial   turnover during the last 3 (three) financial years"
    )
    assert boxes


def test_a_passage_spanning_lines_gets_one_box_per_line() -> None:
    """One box around the whole run would be a rectangle covering everything
    between the lines, including text either side of it."""
    words = _line("Average Annual financial turnover during", top=100.0)
    words += _line("the last three financial years ending", top=118.0)
    boxes = find_highlight_boxes(
        words, "Average Annual financial turnover during the last three financial years"
    )
    assert len(boxes) == 2, f"expected one box per line, got {len(boxes)}"
    assert boxes[0][1] < boxes[1][1]


def test_an_unrelated_sentence_is_not_highlighted() -> None:
    """The property that matters most. A highlight on the wrong clause is worse
    than no highlight -- it actively misdirects."""
    words = _line("The contractor shall maintain all plant and machinery in working order")
    assert find_highlight_boxes(words, "Average annual turnover of not less than Rs. 5 Cr") == []


def test_a_one_word_snippet_is_refused() -> None:
    """A single common word matches somewhere on every page."""
    words = _line("The Earnest Money Deposit shall be Rs. 31,500")
    assert find_highlight_boxes(words, "the") == []


def test_the_match_floor_is_a_real_threshold_not_a_formality() -> None:
    assert 0.3 < MIN_MATCH_RATIO < 0.95


def test_an_empty_page_or_snippet_is_handled() -> None:
    assert find_highlight_boxes([], "anything at all") == []
    assert find_highlight_boxes(_line("some words here"), "") == []


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
def test_a_document_is_stored_and_found_by_its_hash(tmp_path, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "document_store_path", str(tmp_path / "store"))
    source = tmp_path / "tender.pdf"
    source.write_bytes(b"%PDF-1.4 pretend")

    digest = store_document(source)
    assert len(digest) == 64
    stored = path_for(digest)
    assert stored is not None and stored.read_bytes() == b"%PDF-1.4 pretend"


def test_the_same_bytes_under_two_filenames_are_stored_once(tmp_path, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "document_store_path", str(tmp_path / "store"))
    first = tmp_path / "NIT_final.pdf"
    second = tmp_path / "NIT_final(1).pdf"
    first.write_bytes(b"%PDF same")
    second.write_bytes(b"%PDF same")

    assert store_document(first) == store_document(second)
    root = Path(settings.document_store_path)
    assert len(list(root.rglob("*.pdf"))) == 1


def test_an_unknown_hash_resolves_to_nothing(tmp_path, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "document_store_path", str(tmp_path / "store"))
    assert path_for("0" * 64) is None


@pytest.mark.parametrize("bad", ["", "short", "../../etc/passwd", "x" * 64, "/" * 64])
def test_a_malformed_hash_cannot_escape_the_store(bad, tmp_path, monkeypatch) -> None:
    """The hash arrives from a URL path. A traversal here would serve any file
    on the host."""
    from app.config import settings

    monkeypatch.setattr(settings, "document_store_path", str(tmp_path / "store"))
    assert path_for(bad) is None


def test_a_partial_copy_is_never_visible_as_a_complete_document(tmp_path, monkeypatch) -> None:
    """Written beside the target and renamed, so a crash mid-copy cannot leave a
    truncated file that every later reader treats as the whole document."""
    import inspect

    from app.documents import store as store_module

    source = inspect.getsource(store_module.store_document)
    assert ".part" in source and "replace(target)" in source


# --------------------------------------------------------------------------- #
# End to end on a real tender
# --------------------------------------------------------------------------- #
@real
def test_a_real_clause_is_highlighted_on_its_real_page() -> None:
    pdf = DATA / "NOTIF_civilworks_01.pdf"
    rendered = render_page(
        pdf, 5, highlight="Last Date and Time for uploading of Bids", dpi=80
    )
    assert rendered.highlights >= 1
    assert rendered.page == 5 and rendered.page_count == 101
    assert rendered.png[:8] == b"\x89PNG\r\n\x1a\n"


@real
def test_a_snippet_that_is_not_on_the_page_leaves_it_unmarked() -> None:
    pdf = DATA / "NOTIF_civilworks_01.pdf"
    rendered = render_page(
        pdf, 5, highlight="The solar photovoltaic modules shall be ALMM compliant", dpi=80
    )
    assert rendered.highlights == 0, "an unrelated snippet was highlighted"


@real
def test_a_page_beyond_the_document_is_clamped_not_crashed() -> None:
    rendered = render_page(DATA / "NOTIF_civilworks_01.pdf", 9999, dpi=60)
    assert rendered.page == 101


# --------------------------------------------------------------------------- #
# Through the API
# --------------------------------------------------------------------------- #
@real
def test_the_endpoint_serves_a_page_with_its_metadata() -> None:
    from fastapi.testclient import TestClient

    from app.api.main import app
    from app.config import settings

    pdf = DATA / "NOTIF_civilworks_01.pdf"
    digest = store_document(pdf)
    client = TestClient(app)

    response = client.get(
        f"/api/documents/{digest}/page/5",
        params={"highlight": "Last Date and Time for uploading of Bids", "dpi": 80},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["X-Page"] == "5"
    assert response.headers["X-Page-Count"] == "101"
    assert int(response.headers["X-Highlights"]) >= 1


def test_a_document_that_was_never_retained_is_a_clear_404() -> None:
    """Rows ingested before the store existed have no file. The message says
    that rather than implying the tender is broken."""
    from fastapi.testclient import TestClient

    from app.api.main import app

    response = TestClient(app).get(f"/api/documents/{'a' * 64}/page/1")
    assert response.status_code == 404
    assert "not retained" in response.json()["detail"]
