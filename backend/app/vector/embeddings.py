"""BGE embeddings via sentence-transformers, local (Section 8).

Kept behind a small interface for the same reason as the LLM layer: the Qdrant
collection is built around a fixed vector size, so the dimension is asserted at
load time rather than discovered as a silent mismatch at upsert time.

BGE asymmetric retrieval: queries are prefixed with the model's instruction,
passages are not. Getting this backwards costs measurable retrieval precision,
which Section 10 grades -- hence the separate embed_query/embed_passages calls.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:  # pragma: no cover
    from sentence_transformers import SentenceTransformer

BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


@lru_cache(maxsize=1)
def get_model() -> "SentenceTransformer":
    """Load once per process. First call downloads ~440MB for bge-base-en-v1.5."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(settings.embedding_model, device=settings.embedding_device)
    # Renamed in sentence-transformers 6.x; keep both paths so the guard works
    # on either version rather than silently skipping the dimension check.
    get_dim = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
    actual_dim = get_dim()
    if actual_dim != settings.embedding_dim:
        raise RuntimeError(
            f"EMBEDDING_DIM={settings.embedding_dim} but {settings.embedding_model} "
            f"produces {actual_dim}-d vectors. Fix the config, then recreate the "
            f"Qdrant collection -- changing dimension requires re-embedding."
        )
    return model


def embed_passages(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Embed document chunks for indexing. No instruction prefix."""
    if not texts:
        return []
    model = get_model()
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,  # cosine distance assumes unit vectors
        show_progress_bar=False,
    )
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> list[float]:
    """Embed a search query. BGE expects the instruction prefix here."""
    model = get_model()
    vector = model.encode(
        BGE_QUERY_INSTRUCTION + text, normalize_embeddings=True, show_progress_bar=False
    )
    return vector.tolist()
