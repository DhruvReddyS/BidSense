"""Central configuration. Everything env-driven so provider swaps are config, not code."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # --- PostgreSQL ---
    postgres_user: str = "tenderiq"
    postgres_password: str = "tenderiq"
    postgres_db: str = "tenderiq"
    postgres_host: str = "localhost"
    postgres_port: int = 5433

    # --- Authentication ---
    auth_secret: str = "development-only-change-me"
    auth_token_minutes: int = 60
    reviewer_registration_code: str = "development-reviewer"

    # Worker concurrency is deliberately environment-sized. Two is safe for a
    # free-tier/local setup; a paid hosted provider can raise this without a
    # code change. Provider gates and token buckets remain the final authority.
    ingest_workers: int = Field(default=2, ge=1, le=64)
    index_workers: int = Field(default=1, ge=1, le=16)
    defer_vector_indexing: bool = False
    ocr_workers: int = Field(default=3, ge=1, le=16)

    # --- Qdrant ---
    qdrant_host: str = "localhost"
    qdrant_port: int = 6343
    qdrant_api_key: str | None = None
    qdrant_collection: str = "tenderiq_chunks"

    # --- Embeddings (Section 8: BGE, local, no API dependency) ---
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    embedding_dim: int = 768
    # `auto` prefers CUDA, then Apple Metal, and falls back to CPU. Explicit
    # cpu/cuda/mps values remain available for reproducible benchmarks.
    embedding_device: str = "auto"
    embedding_batch_size: int = Field(default=64, ge=1, le=512)

    # --- LLM (Section 8.1) ---
    llm_provider: Literal["gemini", "groq", "xai", "ollama", "chain"] = "gemini"
    # Ordered fallback chain, used when LLM_PROVIDER=chain. Each tier is tried
    # in turn and a tier that fails for a persistent reason (quota spent, key
    # rejected) is retired for the process rather than retried on every call.
    llm_chain: str = "gemini,groq,ollama"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    # Free-tier quota, requests per minute per model. Raise on a paid key.
    # Each model has its own daily free-tier quota, so exhausting one is
    # recoverable: fail over to the next rather than stopping the run.
    gemini_fallback_models: str = "gemini-3.5-flash,gemini-3.5-flash-lite,gemini-2.5-flash"
    # Requests/minute AND tokens/minute. 5 rpm was tuned for gemini-2.5-flash
    # and made every model pay its price; the flash-lite tiers allow more. An
    # occasional 429 now costs about a second and a fall to the next tier,
    # rather than a stall, because the retry is impatient when a tier is live.
    gemini_rpm: int = 15
    gemini_tpm: int = 240_000
    gemini_retries: int = 4
    # Milliseconds. Generous enough for a large structured extraction, bounded
    # enough that a stalled connection cannot hold a worker for ever.
    gemini_timeout_ms: int = 180_000
    # --- Retained source documents (citation click-through) ---
    # Uploaded files are kept so a citation can be shown on the page it came
    # from. Content-addressed, so the same tender uploaded twice is stored once.
    document_store_path: str = "../data/store"
    # Render resolution for a cited page. 110 is legible on a laptop without
    # producing a megabyte per page.
    page_render_dpi: int = 110

    # --- Groq (tier 2: hosted, own quota) ---
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"
    # A ceiling, not the real control. The binding limit is TOKENS per minute,
    # and the limiter paces on that: a 1,500-token question no longer waits as
    # long as a 4,400-token extraction, which was 30s of latency around 1.6s of
    # generation.
    groq_rpm: int = 20
    groq_retries: int = 3
    groq_timeout_s: int = 180
    # Free tier is 8,000 TPM, measured from a 413. Raise on a paid tier.
    groq_tpm: int = 8000

    # --- xAI / Grok (tier 2 alternative) ---
    xai_api_key: str | None = None
    xai_model: str = "grok-3"
    xai_rpm: int = 60
    xai_retries: int = 3
    xai_timeout_s: int = 180
    xai_tpm: int = 16000

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3-14b-40k:latest"
    # Qwen3 reasons before answering. Thinking roughly quadruples latency but
    # measurably improves verbatim fidelity (it keeps "Rs. 2,00,000" rather than
    # returning "2,00,000"), which is what source_snippet citations depend on.
    # Off for fast iteration, on for the runs whose accuracy gets reported.
    ollama_think: bool = False
    # Tender notifications run long; the default 4k context silently truncates
    # them, which looks like a model that "missed" clauses on later pages.
    ollama_num_ctx: int = 40960
    # Seconds. A local model on a loaded machine is slow but not unbounded --
    # the same argument as gemini_timeout_ms, at local speeds.
    ollama_timeout_s: int = 300
    # Fewer than the hosted path: a local retry re-runs generation on hardware
    # that is already the bottleneck.
    ollama_retries: int = 2
    llm_temperature: float = 0.0
    # Real tenders yield long lists -- a 382-page notification can produce
    # dozens of eligibility criteria, each with a verbatim snippet. 8k truncates
    # those mid-JSON; gemini-2.5-flash allows far more.
    llm_max_output_tokens: int = 32768

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
