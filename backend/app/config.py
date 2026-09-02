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

    # --- Qdrant ---
    qdrant_host: str = "localhost"
    qdrant_port: int = 6343
    qdrant_api_key: str | None = None
    qdrant_collection: str = "tenderiq_chunks"

    # --- Embeddings (Section 8: BGE, local, no API dependency) ---
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    embedding_dim: int = 768
    embedding_device: str = "cpu"

    # --- LLM (Section 8.1) ---
    llm_provider: Literal["gemini", "ollama"] = "gemini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    # Free-tier quota, requests per minute per model. Raise on a paid key.
    # Each model has its own daily free-tier quota, so exhausting one is
    # recoverable: fail over to the next rather than stopping the run.
    gemini_fallback_models: str = "gemini-3.5-flash,gemini-3.5-flash-lite,gemini-2.5-flash"
    gemini_rpm: int = 5
    gemini_retries: int = 4
    # Milliseconds. Generous enough for a large structured extraction, bounded
    # enough that a stalled connection cannot hold a worker for ever.
    gemini_timeout_ms: int = 180_000
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
