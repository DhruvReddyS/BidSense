# TenderIQ

Tender intelligence platform. Build spec: [TenderIQ_Scope_v2.md](TenderIQ_Scope_v2.md).

**Status: Phases 0–2 complete.** Schema and stores, ingestion and extraction, and the Part 1 vendor tool (gap report, RAG Q&A, Next.js frontend). Phase 3 (company-side elimination) not started.

The stack has been run end to end against a real LLM: PDF upload → parse →
LangGraph extraction → PostgreSQL + Qdrant → gap report with cited clauses →
grounded Q&A. **Extraction quality is currently limited by the LLM available —
see [LLM status](#llm-status).**

## Quick start

```bash
cp .env.example .env          # ports 5433 / 6343 avoid the multi-agent-legal-rag stack
docker compose up -d
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend
../.venv/bin/python -m scripts.bootstrap   # Alembic migrate + create Qdrant collection
../.venv/bin/python -m scripts.verify      # health check
../.venv/bin/python -m pytest -q           # 187 tests
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
  extraction/   LangGraph agents, prompts, page selection, converters, pipeline
  compliance/   gap report engine, three-tier document-name matching
  rag/          scoped retrieval, citation-grounded answers
  api/          FastAPI routes (Part 1)
backend/migrations/  Alembic
backend/scripts/     bootstrap.py, verify.py, ingest.py
frontend/            Next.js 14 App Router + Tailwind
data/                collected tenders + Section 9.4 tracking sheets
```

## Running the app

```bash
# terminal 1 — API
cd backend && ../.venv/bin/python -m uvicorn app.api.main:app --port 8100

# terminal 2 — frontend
cd frontend && npm install && npm run dev    # http://localhost:3000
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

## Phase 2 decisions

| Decision | Choice | Why |
|---|---|---|
| Document-name matching | exact → alias table → BGE embedding, recording which tier matched | Section 6 rules out exact matching. The alias table exists because embeddings alone confuse "PAN Card" with "TAN Certificate" — lexically close, entirely different documents |
| Unreadable values | `not_assessable`, never `missing` | "We could not read your number" must never reach a vendor as "you failed" |
| Format rules | always `manual_check` | Section 4.3 — they are visual, and claiming to have verified them would be a lie |
| Score preview | absent unless weightage is published | Section 4.4 — `available: false` is a first-class result, not an error |
| Retrieval scope | pre-filtered by metadata, never post-filtered | Answering about tender A with a clause from tender B is a wrong answer that looks well-cited; and a post-filter leaks other bids through score ordering (Section 5.7) |
| Citations | verified after generation, invented ones stripped | A hallucinated `[7]` looks exactly as authoritative as a real one in the UI |

### Long documents: page selection

Real tenders are enormous — the HGCL solar notification in `data/` is 382 pages
(~200k tokens). Sending the whole document either truncates silently or buries
three relevant clauses in 380 pages of contract boilerplate. Each extractor
therefore reads only the pages likely to hold its field group, chosen by lexical
cue scoring with embedding re-ranking as a fallback. This cuts that document to
~15k tokens per field group. `tests/test_selection.py` asserts recall against
the real documents: the page carrying the turnover clause, the EMD, and the
document checklist must each be selected.

## LLM status

Section 8.1 specifies Gemini 2.5 Flash as primary with Ollama as fallback. As of
this build:

| Option | State |
|---|---|
| `gemini-2.5-flash` | **Retired** — 404 for new API keys |
| `gemini-3.x` (any) | **403 "Your project has been denied access"** — a project-level block, not a model issue |
| `qwen3:14b` local | Works, good extraction quality, but minutes per call on this hardware |
| `qwen3:4b` local | ~6s per call, but misses fields and narrates its reasoning into answers |

The provider abstraction did its job — every swap above was a `.env` change, no
code. But **the primary path needs a working Gemini key**: create a fresh Google
Cloud project and generate a new key, or use a different account.

## What's still needed

1. **A working Gemini API key.** The current one's project is denied access.
2. **`brew install tesseract poppler`** — until then, scanned pages are reported
   as missing (loudly, by design). All three collected tenders are native text,
   so this is not yet blocking.
3. **More notifications** — 3 of the 5–10 Section 9.1 asks for, covering two of
   three sectors. IT services and at least one scanned document are missing.
4. **`portal_source` in `data/tracking_notifications.csv`** — only the collector
   knows which portal each document came from.

## Not yet built

Phases 3–7: elimination rule engine, shortlist, query router, evaluation harness.
