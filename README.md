# TenderIQ

Tender intelligence platform. Build spec: [TenderIQ_Scope_v2.md](TenderIQ_Scope_v2.md).

**Status: Phase 1 complete** (Section 12 — schema/stores, then OCR + parsing + LangGraph extraction). Phase 2 (vendor tool) not started.

One step of Phase 1 is still open: extraction has not yet been run against a real LLM or real tender PDFs. Both need input from you — see **What's blocked** below.

## Quick start

```bash
cp .env.example .env          # ports 5433 / 6343 avoid the multi-agent-legal-rag stack
docker compose up -d
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend
../.venv/bin/python -m scripts.bootstrap   # Alembic migrate + create Qdrant collection
../.venv/bin/python -m scripts.verify      # health check
../.venv/bin/python -m pytest -q           # 108 tests
```

`--recreate` on bootstrap drops and rebuilds both stores. Destructive.

## Layout

```
backend/app/
  schemas/      Section 6 shared extraction schema (Pydantic)
  db/models/    SQLAlchemy tables (hybrid normalized + JSONB)
  vector/       Qdrant collection, payload schema, BGE embeddings
  llm/          Section 8.1 provider interface (Gemini primary, Ollama fallback)
  normalize/    Indian-notation currency canonicalization
  ingest/       PDF/DOCX parsing, Tesseract OCR fallback, page-aware chunking
  extraction/   LangGraph agents, prompts, converters, persistence, pipeline
backend/migrations/  Alembic
backend/scripts/     bootstrap.py, verify.py, ingest.py
```

## Ingesting documents (Phase 1)

```bash
cd backend
# parse only -- no LLM, no database. Safe first look at any new format.
../.venv/bin/python -m scripts.ingest inspect ../data/notifications/

# full pipeline: parse -> extract -> Postgres + Qdrant
../.venv/bin/python -m scripts.ingest notification ../data/notifications/ --report run.json
../.venv/bin/python -m scripts.ingest vendor ../data/vendors/ --tender-id TSTS/2026/IT/0042
```

## Phase 1 decisions

| Decision | Choice | Why |
|---|---|---|
| Extraction shape | One specialist LangGraph node per field group, fanned out in parallel | Focused prompts beat one monolithic schema call; a failing node loses one field group, not the document; per-node timings feed Section 10 |
| Who normalizes | Code, never the model | The LLM returns amounts verbatim ("Rs. 5 Cr"); `app.normalize.money` canonicalizes. Section 2.1.3's logic applied to arithmetic — a model that converts is doing maths we cannot audit |
| LLM output models | Separate flat models in `extraction/llm_schemas.py`, not the Section 6 schema | Nested schemas raise constrained-decoding failure rates; the split is also where "verbatim" is enforced |
| Chunking | Never spans a page boundary | A chunk covering pages 7–8 cannot honestly cite either one |
| Table extraction | Ruled lines first, guarded text-alignment fallback | Many real tender tables are unruled. The fallback is gated on column-count stdev and cell density, measured to separate real grids (0.4 / 0.96) from prose (2.0 / 0.67) |

### Failures are loud, never silent

A page yielding no text with OCR unavailable produces a warning saying the content is **missing from extraction**. Silently returning an empty page reads downstream as "this clause is not in the tender" — a wrong answer, not a missing feature.

### Re-ingestion replaces, it does not merge

Re-extracting a tender deletes its previous rows and purges its previous chunks before writing. A partial merge would leave criteria from an earlier, possibly wrong, extraction silently in force; and because a replaced SQL row gets a new id, deterministic chunk ids alone would strand the old chunks as citable orphans.

## Phase 0 decisions

| Decision | Choice | Why |
|---|---|---|
| SQL shape | Hybrid | Normalized child tables for what the Level 1 rule engine (5.2) and Level 3 structured router (5.4) query; JSONB for display-only lists |
| Embeddings | `BAAI/bge-base-en-v1.5`, 768-d, cosine | Balance of CPU speed and retrieval quality, which Section 10 grades |
| Auth | `users` table + owner FKs now | Section 5.7 needs role separation; columns now avoids a migration against populated tables later |
| Provenance | `clause_ref` + `source_page` + `source_snippet` | Makes 4.3/4.5/5.2 citations resolve to real text and Section 10's citation faithfulness measurable |

### Two invariants enforced in the database, not just in Python

- `ck_vendor_submissions_eliminated_requires_reason` — Section 5.2 requires elimination to be defensible if challenged, so a status of `eliminated` without a reason is rejected by Postgres.
- Postgres enum labels are the Pydantic enum **values** (`eliminated`, not `ELIMINATED`), via `values_callable`. Without this, hand-written SQL in the Level 3 router matches nothing silently.

### Status lives in two stores

Postgres is authoritative; Qdrant carries `status` as a filter tag (Section 7). Every write that changes `vendor_submissions.status` must call `app.vector.qdrant.retag_status`, or status-scoped retrieval answers off a stale tag.

### Unparseable numbers stay NULL

`amount_inr IS NULL` means "seen but not parseable" and must surface as needs-manual-check. It is never coerced to 0 — that would auto-eliminate a vendor whose figure merely failed to parse. SQL `NULL` semantics already exclude such rows from threshold comparisons; keep it that way.

## Swapping the LLM (Section 8.1)

Set `LLM_PROVIDER=ollama` in `.env`. No code change — both providers implement `generate_structured` with native schema-constrained decoding.

## What's blocked (needs you)

1. **`GEMINI_API_KEY` in `.env`** — https://aistudio.google.com/apikey. Until then extraction runs only against the scripted stub in `tests/stub_llm.py`.
2. **`brew install tesseract poppler`** — without these, scanned pages are reported as missing rather than OCR'd.
3. **5–10 real tender notifications** in `data/notifications/` (Section 9.1 — download manually from GeM/CPPP, do not scrape). Phase 1 is not finished until extraction has been checked against real documents.

## Not yet built

Phases 2–7: gap report, RAG Q&A, elimination rule engine, shortlist, query router, frontend, evaluation harness.
