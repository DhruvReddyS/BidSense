"""Concurrent uploads reuse one extraction without serializing unrelated files."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import uuid
import pytest
from sqlalchemy import delete, text

from app.config import settings
from app.db.session import session_scope
from app.db.models import TenderNotificationRow
from app.db.models.cache import ExtractionCacheRow
from app.extraction import cache
from app.extraction.pipeline import ingest_notification
from tests.doc_factory import make_notification_pdf
from tests.stub_llm import StubLLM


def test_simultaneous_uploads_call_the_graph_once(tmp_path, monkeypatch):
    try:
        with session_scope() as s: s.execute(text('SELECT 1'))
    except Exception:
        pytest.skip('PostgreSQL unavailable')
    version = uuid.uuid4().hex
    tender_id = f'SINGLEFLIGHT-{version}'
    monkeypatch.setattr(cache, 'pipeline_version', lambda: version)
    monkeypatch.setattr(settings, 'document_store_path', str(tmp_path/'store'))
    pdf = make_notification_pdf(tmp_path/'input.pdf')
    stub = StubLLM()
    stub.script['RawHeader'].tender_id = tender_id
    barrier = Barrier(8)
    def ingest(_):
        barrier.wait(timeout=15)
        return ingest_notification(pdf, llm=stub, index=False)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            reports = list(pool.map(ingest, range(8)))
        assert all(r.ok for r in reports)
        assert len(stub.calls) == 6
        assert sum(r.from_cache for r in reports) == 7
        assert len({r.row_id for r in reports}) == 1
    finally:
        with session_scope() as s:
            s.execute(delete(TenderNotificationRow).where(TenderNotificationRow.tender_id == tender_id))
            s.execute(delete(ExtractionCacheRow).where(ExtractionCacheRow.pipeline_version == version))


def test_lock_is_released_when_extraction_raises(tmp_path, monkeypatch):
    from app.schemas.common import DocumentKind
    monkeypatch.setattr(settings, 'document_store_path', str(tmp_path))
    with pytest.raises(ValueError):
        with cache.extraction_lock('a'*64, DocumentKind.NOTIFICATION):
            raise ValueError('failed producer')
    with cache.extraction_lock('a'*64, DocumentKind.NOTIFICATION, timeout=0):
        pass


def test_different_documents_do_not_block_one_another(tmp_path, monkeypatch):
    from app.schemas.common import DocumentKind
    monkeypatch.setattr(settings, 'document_store_path', str(tmp_path))
    barrier = Barrier(2)
    def work(key):
        with cache.extraction_lock(key, DocumentKind.NOTIFICATION):
            barrier.wait(timeout=3)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(work, ['a'*64, 'b'*64]))
