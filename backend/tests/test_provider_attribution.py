"""Attribution belongs to each call, including simultaneous fallback/recovery."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from app.llm.base import LLMProvider, LLMError
from app.llm.chain import ChainProvider

class Tier(LLMProvider):
    def __init__(self, name, index):
        self.name, self.index = name, index
        self.last_model_used = name + '-test'
    def generate_text(self, prompt, **kwargs):
        if self.index < int(prompt) % 3:
            raise LLMError('transient timeout')
        self.last_model_used = self.name + '-test'
        return self.name
    def generate_structured(self, *args, **kwargs):
        raise NotImplementedError


def test_concurrent_tier_recovery_keeps_attribution_with_the_call(monkeypatch):
    names = ['gemini', 'groq', 'ollama']
    tiers = {n: Tier(n, i) for i, n in enumerate(names)}
    monkeypatch.setattr('app.llm.build_provider', lambda name: tiers[name])
    chain = ChainProvider(names)
    barrier = Barrier(8)
    def run(i):
        actual = chain.generate_text(str(i))
        barrier.wait(timeout=10)
        reported = chain.active_provider
        barrier.wait(timeout=10)
        return actual, reported
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, range(40)))
    assert all(reported == f'{actual}:{actual}-test' for actual, reported in results)
    assert not chain.retired


def test_failed_call_does_not_inherit_previous_success(monkeypatch):
    tier = Tier('gemini', 0)
    monkeypatch.setattr('app.llm.build_provider', lambda _: tier)
    chain = ChainProvider(['gemini'])
    chain.generate_text('0')
    import pytest
    with pytest.raises(LLMError):
        chain.generate_text('1')
    assert chain.active_provider is None


def test_model_label_is_local_to_each_worker():
    tier = Tier('gemini', 0)
    barrier = Barrier(8)
    def run(i):
        tier.last_model_used = f'model-{i}'
        barrier.wait(timeout=10)
        return tier.last_model_used
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(run, range(8))) == [f'model-{i}' for i in range(8)]


import pytest

@pytest.mark.parametrize('destination', ['groq', 'ollama'])
def test_lower_tier_pipeline_records_provider_and_flags_regex_misses(destination, tmp_path, monkeypatch):
    import uuid
    from sqlalchemy import delete, text
    from app.db.session import session_scope
    from app.db.models import TenderNotificationRow
    from app.extraction.pipeline import ingest_notification
    from app.extraction.llm_schemas import RawHeader
    from app.extraction.validate import Severity
    from tests.doc_factory import make_notification_pdf
    from tests.stub_llm import StubLLM

    try:
        with session_scope() as session: session.execute(text('SELECT 1'))
    except Exception:
        pytest.skip('PostgreSQL unavailable')
    tender_id = f'ATTRIBUTION-{uuid.uuid4()}'
    class EmptyHeader(StubLLM):
        name = destination
        def generate_structured(self, prompt, schema, **kwargs):
            self.last_model_used = 'test-model'
            if schema is RawHeader:
                return RawHeader(tender_id=tender_id, title='Attribution fixture')
            return super().generate_structured(prompt, schema, **kwargs)
    class Exhausted(EmptyHeader):
        def generate_structured(self, *args, **kwargs):
            raise LLMError('invalid_api_key')
    tiers = {name: EmptyHeader() if name == destination else Exhausted() for name in ['gemini', 'groq', 'ollama']}
    monkeypatch.setattr('app.llm.build_provider', lambda name: tiers[name])
    chain = ChainProvider(['gemini', 'groq', 'ollama'])
    path = make_notification_pdf(tmp_path / 'attribution.pdf')
    try:
        report = ingest_notification(path, llm=chain, index=False, use_cache=False)
        assert report.ok and report.needs_review
        assert report.extracted_by == f'{destination}:test-model'
        assert any(f.severity is Severity.ERROR and 'appears to state it' in f.message for f in report.validation)
    finally:
        with session_scope() as session:
            session.execute(delete(TenderNotificationRow).where(TenderNotificationRow.tender_id == tender_id))


def test_graph_keeps_every_nodes_serving_tier(tmp_path, monkeypatch):
    from app.extraction.graph import extract_notification
    from app.ingest import parse_document
    from app.schemas.common import DocumentKind
    from tests.doc_factory import make_notification_pdf
    from tests.stub_llm import StubLLM
    names = ['gemini', 'groq', 'ollama']
    class Routed(StubLLM):
        def __init__(self, index):
            super().__init__()
            self.index, self.name = index, names[index]
        def generate_structured(self, prompt, schema, **kwargs):
            required = {'RawHeader': 1, 'EligibilityList': 2}.get(schema.__name__, 0)
            if self.index < required:
                raise LLMError('transient timeout')
            self.last_model_used = 'test-model'
            return super().generate_structured(prompt, schema, **kwargs)
    tiers = {name: Routed(i) for i, name in enumerate(names)}
    monkeypatch.setattr('app.llm.build_provider', lambda name: tiers[name])
    document = parse_document(make_notification_pdf(tmp_path / 'mixed.pdf'), DocumentKind.NOTIFICATION)
    _, result = extract_notification(document, llm=ChainProvider(names))
    assert not result['errors']
    providers = dict(result['providers'])
    assert len(providers) == 6
    assert providers['header'] == 'groq:test-model'
    assert providers['eligibility'] == 'ollama:test-model'
    assert providers['documents'] == 'gemini:test-model'
