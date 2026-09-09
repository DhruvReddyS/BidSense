"""Fallback must respect the tier that actually serves each request."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time

from app.llm.base import LLMError, LLMProvider
from app.llm.chain import ChainProvider
from app.extraction.llm_schemas import RawHeader


class CapacityTier(LLMProvider):
    def __init__(self, name, budget=None, concurrency=4, fail=False):
        self.name = name
        self.budget = budget
        self.max_concurrency = concurrency
        self.fail = fail
        self.prompts = []
        self.running = self.peak = 0
        self.lock = Lock()

    @property
    def input_char_budget(self):
        return self.budget

    def generate_structured(self, prompt, schema, **kwargs):
        if self.fail:
            raise LLMError('invalid_api_key')
        self.prompts.append(prompt)
        self.last_model_used = 'capacity-test'
        return RawHeader(tender_id='T', title='Tender')

    def generate_text(self, prompt, **kwargs):
        if self.fail:
            raise LLMError('invalid_api_key')
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
        try:
            time.sleep(.025)
            self.last_model_used = 'capacity-test'
            return prompt
        finally:
            with self.lock:
                self.running -= 1


def tiers(monkeypatch):
    hosted = CapacityTier('gemini', fail=True)
    local = CapacityTier('ollama', budget=17, concurrency=1)
    monkeypatch.setattr('app.llm.build_provider', lambda name: {'gemini': hosted, 'ollama': local}[name])
    return ChainProvider(['gemini', 'ollama']), local


def test_fallback_rebuilds_prompt_for_actual_tier(monkeypatch):
    chain, local = tiers(monkeypatch)
    budgets = []
    def prompt(budget):
        budgets.append(budget)
        return 'x' * (budget or 1200)
    chain.generate_structured_from(prompt, RawHeader)
    assert budgets == [None, 17]
    assert local.prompts == ['x' * 17]
    assert chain.active_provider == 'ollama:capacity-test'


def test_bursty_fallback_uses_local_concurrency_limit(monkeypatch):
    chain, local = tiers(monkeypatch)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(chain.generate_text, map(str, range(16)))) == list(map(str, range(16)))
    assert local.peak == 1


def test_graph_reselects_pages_after_tier_switch(monkeypatch):
    from app.extraction import graph
    chain, local = tiers(monkeypatch)
    seen = []
    def select(document, node, **kwargs):
        budget = kwargs.get('char_budget', 1200)
        seen.append(budget)
        return 'x' * budget, [1] if budget == 17 else [1, 2]
    monkeypatch.setattr(graph, 'select_pages', select)
    result = graph.extract_header({'document': object(), 'llm': chain})
    assert not result['errors']
    assert seen == [1200, 17]
    assert 'x' * 1200 not in local.prompts[0]
    assert result['selections'] == [('header', [1])]


def test_validation_uses_actual_header_pages(monkeypatch, tmp_path):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from app.extraction import pipeline
    from app.schemas.notification import TenderNotification
    path = tmp_path / 'coverage.pdf'
    path.write_bytes(b'coverage probe')
    document = SimpleNamespace(page_count=20, ocr_page_count=0, parse_warnings=[])
    notification = TenderNotification(tender_id='COVERAGE', title='Coverage probe')
    monkeypatch.setattr(pipeline, 'parse_document', lambda *_: document)
    monkeypatch.setattr(pipeline, '_safe_store_document', lambda *_: None)
    monkeypatch.setattr(pipeline, 'extract_notification', lambda *a, **k: (
        notification, {'errors': [], 'timings': [], 'providers': [('header', 'ollama:test')],
                       'selections': [('header', [1, 7])]}))
    monkeypatch.setattr(pipeline, 'session_scope', lambda: nullcontext(None))
    monkeypatch.setattr(pipeline, 'save_notification', lambda *a, **k: SimpleNamespace(id=None))
    seen = []
    monkeypatch.setattr(pipeline, 'validate_notification',
                        lambda *a, **k: seen.append(k['selected_pages']) or [])
    pipeline.ingest_notification(path, index=False, use_cache=False)
    assert seen == [[1, 7]]


def test_deferred_index_returns_structured_data_before_embedding(monkeypatch, tmp_path):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from app.extraction import pipeline
    from app.schemas.notification import TenderNotification

    path = tmp_path / "fast-review.pdf"
    path.write_bytes(b"fast review")
    document = SimpleNamespace(page_count=1, ocr_page_count=0, parse_warnings=[])
    notification = TenderNotification(tender_id="FAST", title="Fast review")
    monkeypatch.setattr(pipeline, "parse_document", lambda *_: document)
    monkeypatch.setattr(pipeline, "_safe_store_document", lambda *_: None)
    monkeypatch.setattr(pipeline, "extract_notification", lambda *a, **k: (
        notification, {"errors": [], "timings": [], "providers": [], "selections": []}
    ))
    monkeypatch.setattr(pipeline, "session_scope", lambda: nullcontext(None))
    monkeypatch.setattr(pipeline, "save_notification", lambda *a, **k: SimpleNamespace(id="row"))
    monkeypatch.setattr(pipeline, "validate_notification", lambda *a, **k: [])
    indexed = []
    monkeypatch.setattr(pipeline, "index_notification", lambda *a: indexed.append(True) or 17)

    report = pipeline.ingest_notification(
        path, index=True, defer_index=True, use_cache=False
    )

    assert report.ok and report.index_deferred
    assert report.chunks_indexed == 0 and indexed == []
    assert report._index_task is not None and report._index_task() == 17
    assert indexed == [True]
