"""Parallel page parsing must be an optimisation, never a behaviour change.

Parsing is where ingestion time goes. Measured on a 172-page generated bid,
text extraction plus table detection is 99.9% of the pipeline -- 14.9s against
11ms for chunking -- and inside that, the text-based table fallback is 56% at
~58ms per page it runs on. It is CPU-bound Python, so threads cannot help, but
it parallelises across page ranges: 12.66s to 5.26s (2.41x) on four processes,
with an identical SHA-256 over every page's text and tables.

The whole value of that depends on the output being the same, so that is what
these tests assert -- not the speedup, which is hardware-dependent and would
make for a flaky test.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.ingest.loader import parse_document
from app.ingest.pdf import _parse_page_span, _parse_pages
from app.schemas.common import DocumentKind
from tests.doc_factory import make_notification_pdf


@pytest.fixture(scope="module")
def pdf(tmp_path_factory):
    return make_notification_pdf(
        tmp_path_factory.mktemp("parallel") / "NOTIF_parallel.pdf"
    )


def snapshot(document):
    return [
        (page.page_number, str(page.method), page.text, page.tables)
        for page in document.pages
    ]


def test_parallel_parsing_returns_byte_identical_pages(pdf, monkeypatch):
    serial = parse_document(str(pdf), DocumentKind.NOTIFICATION)

    # The fixture is short, so lower the threshold rather than generate a
    # 24-page document just to cross it.
    monkeypatch.setattr(settings, "pdf_parse_parallel_min_pages", 2)
    monkeypatch.setattr(settings, "pdf_parse_workers", 2)
    parallel = parse_document(str(pdf), DocumentKind.NOTIFICATION)

    assert snapshot(parallel) == snapshot(serial)


def test_pages_come_back_in_order_not_completion_order(pdf, monkeypatch):
    """Spans finish out of order; the assembled document must not."""
    monkeypatch.setattr(settings, "pdf_parse_parallel_min_pages", 2)
    monkeypatch.setattr(settings, "pdf_parse_workers", 3)
    document = parse_document(str(pdf), DocumentKind.NOTIFICATION)
    numbers = [page.page_number for page in document.pages]
    assert numbers == sorted(numbers) == list(range(1, len(numbers) + 1))


def test_a_short_document_stays_serial(pdf, monkeypatch):
    """Spawning interpreters must not cost more than it saves."""
    monkeypatch.setattr(settings, "pdf_parse_workers", 4)
    monkeypatch.setattr(settings, "pdf_parse_parallel_min_pages", 10_000)

    called = {"pool": False}
    import app.ingest.pdf as pdf_module

    original = pdf_module.ProcessPoolExecutor

    class Tripwire:
        def __init__(self, *args, **kwargs):
            called["pool"] = True
            raise AssertionError("a short document must not spawn a pool")

    monkeypatch.setattr(pdf_module, "ProcessPoolExecutor", Tripwire)
    try:
        parse_document(str(pdf), DocumentKind.NOTIFICATION)
    finally:
        monkeypatch.setattr(pdf_module, "ProcessPoolExecutor", original)
    assert not called["pool"]


def test_one_worker_never_spawns_a_pool(pdf, monkeypatch):
    monkeypatch.setattr(settings, "pdf_parse_workers", 1)
    monkeypatch.setattr(settings, "pdf_parse_parallel_min_pages", 2)
    import app.ingest.pdf as pdf_module

    class Tripwire:
        def __init__(self, *args, **kwargs):
            raise AssertionError("workers=1 must stay serial")

    monkeypatch.setattr(pdf_module, "ProcessPoolExecutor", Tripwire)
    assert parse_document(str(pdf), DocumentKind.NOTIFICATION).pages


def test_an_unavailable_process_pool_falls_back_rather_than_failing(pdf, monkeypatch):
    """A sandbox may forbid process creation; that is slower, not broken."""
    monkeypatch.setattr(settings, "pdf_parse_parallel_min_pages", 2)
    monkeypatch.setattr(settings, "pdf_parse_workers", 2)
    import app.ingest.pdf as pdf_module

    def refuse(*args, **kwargs):
        raise OSError("process creation denied")

    monkeypatch.setattr(pdf_module, "ProcessPoolExecutor", refuse)
    document = parse_document(str(pdf), DocumentKind.NOTIFICATION)
    assert document.pages, "parsing must still produce pages"
    assert any(page.text for page in document.pages)


def test_a_span_covers_exactly_its_range(pdf):
    """Off-by-one here would silently drop or duplicate a page."""
    rows = _parse_page_span((str(pdf), 1, 3, True))
    assert [row[0] for row in rows] == [2, 3]


def test_spans_tile_the_document_without_gaps_or_overlap(pdf, monkeypatch):
    monkeypatch.setattr(settings, "pdf_parse_parallel_min_pages", 2)
    monkeypatch.setattr(settings, "pdf_parse_workers", 3)
    rows = _parse_pages(str(pdf), 3, True)
    assert [row[0] for row in rows] == [1, 2, 3]
