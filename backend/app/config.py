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
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    llm_temperature: float = 0.0
    llm_max_output_tokens: int = 8192

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
