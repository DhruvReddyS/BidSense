"""Extraction caching and transient retry (Stage 5).

Both exist to protect the same thing: a free tier of twenty requests per model
per day, against six requests per document. One accidental re-upload of a tender
costs nearly a third of a model's daily quota, and a connection reset mid-run
used to cost the whole document.

Every test here counts what actually happened -- LLM calls made, requests
issued -- rather than asserting that the code contains a cache.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.db.session import engine, session_scope
from app.llm.base import LLMError
from app.llm.ratelimit import _is_transient, retry_transient
from app.schemas.common import DocumentKind


def _live() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        from app.vector.embeddings import get_model

        get_model()
        return True
    except Exception:
        return False


live = pytest.mark.skipif(not _live(), reason="postgres/qdrant or BGE unavailable")


# --------------------------------------------------------------------------- #
# Transient classification
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "exc",
    [
        ConnectionResetError("[Errno 54] Connection reset by peer"),
        ConnectionRefusedError("connection refused"),
        TimeoutError("timed out"),
        RuntimeError("503 UNAVAILABLE: the model is overloaded"),
        RuntimeError("502 Bad Gateway"),
        RuntimeError("504 Gateway Timeout"),
        RuntimeError("429 RESOURCE_EXHAUSTED"),
    ],
)
def test_transport_and_overload_failures_are_retried(exc) -> None:
    assert _is_transient(exc)


def test_a_wrapped_transport_error_is_found_through_the_cause_chain() -> None:
    """SDKs wrap transport errors in their own types, and the interesting one is
    usually two levels down. Matching only the outermost misses it."""
    inner = ConnectionResetError("[Errno 54] Connection reset by peer")
    try:
        try:
            raise inner
        except ConnectionResetError as cause:
            raise RuntimeError("ollama call failed") from cause
    except RuntimeError as wrapped:
        assert _is_transient(wrapped)


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("output failing RawHeader: Expecting value"),
        RuntimeError("400 INVALID_ARGUMENT"),
        RuntimeError("PERMISSION_DENIED: API key invalid"),
        RuntimeError(
            "429 RESOURCE_EXHAUSTED {'quotaId': "
            "'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}"
        ),
    ],
)
def test_permanent_failures_are_not_retried(exc) -> None:
    """Retrying these burns quota and delays the report that something is
    genuinely wrong. The last one is a DAILY cap -- it does not clear today."""
    assert not _is_transient(exc)


def test_retry_gives_up_and_re_raises_the_last_error(monkeypatch) -> None:
    monkeypatch.setattr("app.llm.ratelimit.time.sleep", lambda _: None)
    attempts = {"n": 0}

    def always_fails():
        attempts["n"] += 1
        raise ConnectionResetError("reset")

    with pytest.raises(ConnectionResetError):
        retry_transient(always_fails, attempts=3)
    assert attempts["n"] == 3


def test_retry_returns_as_soon_as_it_succeeds(monkeypatch) -> None:
    monkeypatch.setattr("app.llm.ratelimit.time.sleep", lambda _: None)
    attempts = {"n": 0}

    def fails_once():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionResetError("reset")
        return "ok"

    assert retry_transient(fails_once, attempts=4) == "ok"
    assert attempts["n"] == 2


def test_the_ollama_provider_retries_a_dropped_connection(monkeypatch) -> None:
    """Loading a 5GB model into VRAM takes seconds during which the server is up
    but not answering. Before this, that ended the document's extraction."""
    monkeypatch.setattr("app.llm.ratelimit.time.sleep", lambda _: None)
    from app.llm.ollama import OllamaProvider

    calls = {"n": 0}

    class _Response:
        def raise_for_status(self):
            return None

        @staticmethod
        def json():
            return {"message": {"content": "the answer"}}

    def flaky(url, json, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionResetError("[Errno 54] Connection reset by peer")
        return _Response()

    monkeypatch.setattr("app.llm.ollama.httpx.post", flaky)
    assert OllamaProvider().generate_text("hi") == "the answer"
    assert calls["n"] == 2, "the dropped connection was not retried"


def test_an_empty_ollama_response_is_named_not_left_as_a_json_error(monkeypatch) -> None:
    """Observed with gpt-oss-20b against a 17k-token prompt: the model returned
    nothing at all, and `Expecting value: line 1 column 1 (char 0)` was the only
    symptom -- which says nothing about the cause."""
    from app.llm.ollama import OllamaProvider
    from app.extraction.llm_schemas import RawHeader

    class _Response:
        def raise_for_status(self):
            return None

        @staticmethod
        def json():
            return {"message": {"content": "   "}}

    monkeypatch.setattr("app.llm.ollama.httpx.post", lambda *a, **k: _Response())
    with pytest.raises(LLMError) as exc:
        OllamaProvider().generate_structured("p", RawHeader)

    message = str(exc.value)
    assert "empty response" in message
    assert "context window" in message
    assert "OLLAMA_NUM_CTX" in message


# --------------------------------------------------------------------------- #
# Extraction cache
# --------------------------------------------------------------------------- #
@pytest.fixture
def clean_cache():
    from tests.doc_factory import NOTIFICATION_TRUTH

    def wipe():
        with session_scope() as session:
            session.execute(
                text("DELETE FROM tender_notifications WHERE tender_id = :t"),
                {"t": NOTIFICATION_TRUTH["tender_id"]},
            )
            session.execute(text("DELETE FROM extraction_cache"))

    wipe()
    yield
    wipe()


@pytest.fixture
def pdf(tmp_path_factory):
    from tests.doc_factory import make_notification_pdf

    return make_notification_pdf(tmp_path_factory.mktemp("cache") / "NOTIF_ITservices_01.pdf")


@live
def test_re_uploading_the_same_file_spends_no_llm_calls(pdf, clean_cache) -> None:
    from app.extraction import ingest_notification
    from tests.stub_llm import StubLLM

    first = StubLLM()
    report = ingest_notification(pdf, llm=first)
    assert len(first.calls) == 6, "baseline: six extractors, six calls"
    assert report.from_cache is False

    second = StubLLM()
    again = ingest_notification(pdf, llm=second)
    assert len(second.calls) == 0, "the cache did not prevent the model calls"
    assert again.from_cache is True
    # And the rows and chunks are still written -- only the model calls are skipped.
    assert again.chunks_indexed == report.chunks_indexed
    assert again.identifier == report.identifier


@live
def test_the_cache_is_keyed_on_content_not_filename(pdf, clean_cache, tmp_path) -> None:
    """The same tender arrives as NIT_final.pdf, NIT_final(1).pdf and
    tender.pdf. A filename key misses every one of those."""
    import shutil

    from app.extraction import ingest_notification
    from tests.stub_llm import StubLLM

    ingest_notification(pdf, llm=StubLLM())

    renamed = tmp_path / "NIT_final(1).pdf"
    shutil.copy(pdf, renamed)
    llm = StubLLM()
    assert ingest_notification(renamed, llm=llm).from_cache is True
    assert len(llm.calls) == 0


@live
def test_a_changed_prompt_invalidates_the_cache(pdf, clean_cache) -> None:
    """Changing a prompt is how this system changes what it extracts. An entry
    written by an older prompt is not a hit -- it is a silently stale answer,
    which is worse than paying for the call."""
    from app.extraction import cache as extraction_cache
    from app.extraction import ingest_notification
    from tests.stub_llm import StubLLM

    ingest_notification(pdf, llm=StubLLM())

    with patch.object(extraction_cache, "pipeline_version", lambda: "f" * 32):
        llm = StubLLM()
        report = ingest_notification(pdf, llm=llm)
    assert report.from_cache is False
    assert len(llm.calls) == 6, "a stale entry was served across a prompt change"


@live
def test_forced_re_extraction_bypasses_the_cache(pdf, clean_cache) -> None:
    from app.extraction import ingest_notification
    from tests.stub_llm import StubLLM

    ingest_notification(pdf, llm=StubLLM())
    llm = StubLLM()
    report = ingest_notification(pdf, llm=llm, use_cache=False)
    assert report.from_cache is False
    assert len(llm.calls) == 6


@live
def test_a_failed_extraction_is_not_cached(pdf, clean_cache) -> None:
    """Caching a partial run would make a transient API failure permanent for
    those bytes -- every future upload of that file would inherit the gap."""
    from app.extraction import ingest_notification
    from tests.stub_llm import StubLLM

    broken = ingest_notification(pdf, llm=StubLLM(fail_on={"EligibilityList"}))
    assert broken.extraction_errors

    llm = StubLLM()
    retry = ingest_notification(pdf, llm=llm)
    assert retry.from_cache is False, "a partial extraction was cached"
    assert len(llm.calls) == 6


@live
def test_a_cache_hit_reports_which_model_produced_it(pdf, clean_cache) -> None:
    """A hit inherits the quality of whatever wrote the entry. A report served
    from a local fallback must be able to say so."""
    from app.extraction import cache as extraction_cache
    from app.extraction import ingest_notification
    from tests.stub_llm import StubLLM

    digest = extraction_cache.content_hash(pdf)
    ingest_notification(pdf, llm=StubLLM())
    hit = extraction_cache.lookup(digest, DocumentKind.NOTIFICATION)
    assert hit is not None
    assert hit.model and "stub" in hit.model

    served = ingest_notification(pdf, llm=StubLLM())
    assert served.extracted_by == hit.model


@live
def test_a_cache_failure_never_stops_an_extraction(pdf, clean_cache) -> None:
    """The cost of a miss is an API call. The cost of raising here is a failed
    upload, which is strictly worse."""
    from app.extraction import cache as extraction_cache
    from app.extraction import ingest_notification
    from tests.stub_llm import StubLLM

    def explode(*args, **kwargs):
        raise RuntimeError("database is on fire")

    with patch.object(extraction_cache, "lookup", explode):
        with patch.object(extraction_cache, "store", explode):
            report = ingest_notification(pdf, llm=StubLLM())
    assert report.ok
    assert report.from_cache is False


def test_editing_a_prompt_changes_the_pipeline_version(tmp_path) -> None:
    """The behaviour, not the shape.

    An earlier version of this test asserted only that the version was 32
    characters -- which a hard-coded constant also satisfies, and a mutation
    replacing the digest with `"constant" * 4` passed it. That is the exact
    failure this guards against: a version that never changes serves an
    extraction produced by a prompt that no longer exists.
    """
    from app.extraction.cache import digest_of

    prompt = tmp_path / "prompts.py"
    prompt.write_text("EXTRACT = 'find every eligibility criterion'")
    before = digest_of([prompt])

    prompt.write_text("EXTRACT = 'find every eligibility criterion, including waived ones'")
    after = digest_of([prompt])

    assert before != after, "editing a prompt did not change the pipeline version"
    assert len(before) == 32


def test_the_version_covers_every_file_that_decides_an_extraction() -> None:
    from app.extraction import cache as extraction_cache

    covered = set(extraction_cache._VERSIONED_MODULES)
    for required in (
        "app/extraction/prompts.py",
        "app/extraction/convert.py",
        "app/extraction/llm_schemas.py",
        "app/extraction/graph.py",
        "app/extraction/selection.py",
    ):
        assert required in covered, f"{required} can change without invalidating the cache"


def test_the_version_is_stable_across_calls() -> None:
    from app.extraction import cache as extraction_cache

    assert extraction_cache.pipeline_version() == extraction_cache.pipeline_version()
