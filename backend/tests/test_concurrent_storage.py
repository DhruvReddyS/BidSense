"""Concurrent operations must retain whole documents and exact cache accounting."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import uuid

from sqlalchemy import delete, select, text
import pytest

from app.config import settings
from app.documents import store as documents
from app.extraction import cache
from app.db.models.cache import ExtractionCacheRow
from app.db.session import session_scope
from app.schemas.common import DocumentKind


def test_same_document_concurrent_writers_publish_complete_bytes(tmp_path, monkeypatch):
    source = tmp_path / 'input.pdf'
    source.write_bytes(b'%PDF concurrent document\n' * 40000)
    monkeypatch.setattr(settings, 'document_store_path', str(tmp_path / 'store'))
    barrier = Barrier(8)
    copyfile = documents.shutil.copyfile

    def simultaneous_copy(src, dst):
        copyfile(src, dst)
        barrier.wait(timeout=10)

    monkeypatch.setattr(documents.shutil, 'copyfile', simultaneous_copy)
    with ThreadPoolExecutor(max_workers=8) as pool:
        digests = list(pool.map(lambda _: documents.store_document(source), range(8)))
    assert len(set(digests)) == 1
    assert documents.path_for(digests[0]).read_bytes() == source.read_bytes()
    assert not list((tmp_path / 'store').rglob('*.part'))


def test_failed_copy_is_invisible_and_cleans_staging(tmp_path, monkeypatch):
    source = tmp_path / 'input.pdf'
    source.write_bytes(b'complete bytes')
    monkeypatch.setattr(settings, 'document_store_path', str(tmp_path / 'store'))

    def fail(src, dst):
        from pathlib import Path
        Path(dst).write_bytes(b'partial')
        raise OSError('disk full')

    monkeypatch.setattr(documents.shutil, 'copyfile', fail)
    with pytest.raises(OSError, match='disk full'):
        documents.store_document(source)
    assert documents.path_for(documents.content_hash(source)) is None
    assert not list((tmp_path / 'store').rglob('*.part'))


def test_concurrent_cache_lookups_count_every_hit():
    try:
        with session_scope() as session:
            session.execute(text('SELECT 1'))
    except Exception:
        pytest.skip('PostgreSQL unavailable')
    digest = uuid.uuid4().hex * 2
    try:
        cache.store(digest, DocumentKind.NOTIFICATION, {'test': digest})
        barrier = Barrier(8)
        def read_batch(_):
            barrier.wait(timeout=10)
            return [cache.lookup(digest, DocumentKind.NOTIFICATION) for _ in range(8)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            hits = [hit for batch in pool.map(read_batch, range(8)) for hit in batch]
        assert all(hit is not None and hit.payload == {'test': digest} for hit in hits)
        assert sorted(hit.hits for hit in hits) == list(range(1, 65))
        with session_scope() as session:
            row = session.scalar(select(ExtractionCacheRow).where(ExtractionCacheRow.content_hash == digest))
            assert row.hits == 64
    finally:
        with session_scope() as session:
            session.execute(delete(ExtractionCacheRow).where(ExtractionCacheRow.content_hash == digest))
