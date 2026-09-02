"""Extraction cache (Section 8.1 -- the free tier is the binding constraint).

Re-uploading a file that has already been extracted must not spend the LLM
budget again. Six requests per document against twenty per model per day means a
single accidental re-upload costs nearly a third of a model's daily quota, and
during a demo the same three notifications get uploaded repeatedly.

Keyed on the CONTENT, not the filename: the same tender arrives as
`NIT_final.pdf`, `NIT_final(1).pdf` and `tender.pdf`, and a filename key would
miss every one of those while a content key catches all three.
"""

from __future__ import annotations

from sqlalchemy import Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey


class ExtractionCacheRow(Base, UUIDPrimaryKey, Timestamps):
    __tablename__ = "extraction_cache"
    __table_args__ = (
        # The pipeline version is part of the key, not a column to check after
        # the fact. A cached extraction produced by an older prompt is not a
        # cache hit -- it is a silently stale answer, and the whole point of the
        # prompts is that changing them changes what comes out.
        UniqueConstraint(
            "content_hash", "doc_kind", "pipeline_version", name="uq_extraction_cache_key"
        ),
        Index("ix_extraction_cache_lookup", "content_hash", "doc_kind"),
    )

    #: SHA-256 of the file bytes.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    doc_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Short digest of the extraction code that produced this -- prompts, output
    #: schemas, converters and the graph. See `app.extraction.cache`.
    pipeline_version: Mapped[str] = mapped_column(String(32), nullable=False)

    #: The Section 6 schema instance, serialised. Not the raw LLM response: the
    #: conversion is deterministic and its source is part of the version key, so
    #: storing the converted form saves re-running it without risking staleness.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    #: Which provider and model produced it. A cache hit inherits the quality of
    #: whatever wrote the entry, so a report served from cache must be able to
    #: say it came from a local fallback rather than from Gemini.
    model: Mapped[str | None] = mapped_column(String(120))
    source_file: Mapped[str | None] = mapped_column(Text)
    #: How many times this entry has been served. Cheap, and it is the only
    #: evidence that the cache is doing anything.
    hits: Mapped[int] = mapped_column(default=0, nullable=False)
