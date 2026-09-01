"""BGE embedding contract (Section 8). Skipped if the model isn't downloaded.

The Qdrant collection is created with a fixed vector size, so the dimension
guard in get_model() is the thing standing between a config typo and a silent
upsert failure later.
"""

import pytest

pytest.importorskip("sentence_transformers")

from app.config import settings  # noqa: E402
from app.vector.embeddings import embed_passages, embed_query  # noqa: E402


@pytest.fixture(scope="module")
def vectors():
    try:
        passages = embed_passages(
            [
                "The bidder shall have an average annual turnover of Rs. 5 Cr.",
                "Tea and biscuits will be served during the pre-bid meeting.",
            ]
        )
        query = embed_query("What is the minimum turnover requirement?")
    except Exception as exc:  # model not cached / no network
        pytest.skip(f"BGE model unavailable: {exc}")
    return passages, query


def test_dimension_matches_the_qdrant_collection(vectors):
    passages, query = vectors
    assert len(query) == settings.embedding_dim
    assert all(len(p) == settings.embedding_dim for p in passages)


def test_vectors_are_unit_normalized(vectors):
    """Cosine distance in Qdrant assumes unit vectors."""
    passages, query = vectors
    for v in [*passages, query]:
        assert abs(sum(x * x for x in v) ** 0.5 - 1.0) < 1e-3


def test_query_prefix_yields_usable_separation(vectors):
    """A sanity floor, not a benchmark -- Section 10 measures retrieval properly.
    This just catches the query/passage prefix being wired backwards."""
    (relevant, irrelevant), query = vectors
    sim = lambda a, b: sum(x * y for x, y in zip(a, b))  # noqa: E731
    assert sim(query, relevant) > sim(query, irrelevant)


def test_empty_input_short_circuits():
    assert embed_passages([]) == []
