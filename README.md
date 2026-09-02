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
../.venv/bin/python -m pytest -q           # 226 tests
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

See **[RUNNING.md](RUNNING.md)** for setup, configuration, the CLI and
troubleshooting. The short version:

```bash
docker compose up -d
cd backend && ../.venv/bin/python -m uvicorn app.api.main:app --port 8100
cd frontend && npm run dev    # http://localhost:3000
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

Gemini works. The binding constraint is **quota, not capability**:

| Limit | Value | Consequence |
|---|---|---|
| Requests/minute | 5 (free tier) | Paced by `RateLimiter`; ~65s per document |
| Requests/**day** | **20 per model** (`gemini-2.5-flash`) | 6 calls/document → **3 documents/day per model** |

The daily cap is the real problem, and it cannot be waited out. Each model
carries its *own* daily quota, so the provider fails over automatically:

```bash
GEMINI_MODEL=gemini-3.6-flash
GEMINI_FALLBACK_MODELS=gemini-3.5-flash,gemini-3.5-flash-lite,gemini-2.5-flash
```

A per-minute breach is retried (it clears in seconds); a per-day cap is not
(it does not), so the provider retires that model and moves to the next.
Transient `503 "high demand"` responses are retried too — the shared free tier
emits them regularly.

Ollama remains the offline fallback, unchanged. Measured on this machine:
`qwen3:14b` gives good extraction but takes minutes per call under memory
pressure; `qwen3:4b` answers in ~6s but misses fields and narrates its reasoning.

## Verified on real tenders

All three collected notifications extract cleanly — **3/3, zero errors**:

| Document | Pages | Chunks | Time | Extracted reference |
|---|---|---|---|---|
| IIT (ISM) Dhanbad | 101 | 212 | 195s | `CMU-12011/17/2026-CMU` |
| HGCL solar EPC | 382 | 796 | 196s | `BID NOTICE No.178/CGM(T)/HGCL/…` |
| GHMC LED lights | 68 | 129 | 120s | `TENDER No.01/SE(Electrical)/GHMC/2024-25` |

Wall-clock is dominated by free-tier pacing, not by document size — the
382-page tender took the same time as the 101-page one.

### OCR

Tesseract 5.5.3 and poppler are installed, and the OCR path is verified against
a genuine pixel-only scan: `tests/test_ocr.py` renders a clause to an image,
wraps it in a PDF, and asserts that "Rs. 5 Cr" and "2,00,000" come back and
normalize to the same rupee values as native text would. Pages that already
carry a text layer skip OCR entirely — on a 382-page tender that is the
difference between minutes and hours.

Both branches stay covered regardless of the developer machine: the
"OCR unavailable" degradation path is forced off with a monkeypatch rather than
skipped, because that is what a fresh checkout gets.

### Relative thresholds

Indian works tenders express eligibility as a *share of the estimated cost*
rather than an absolute figure: IIT (ISM) requires turnover of "30% of the
estimated cost". Read naively that is a threshold of ₹30, which every bidder
clears. Such thresholds are now resolved against the contract value extracted
from the same document (₹12,56,561 × 30% = ₹3,76,968.30), in code rather than by
the model. When the estimate is unknown the criterion stays unresolved and
surfaces as needs-manual-check — inventing an absolute figure from an unknown
base would be worse than admitting it cannot be computed.

## Evaluation (Section 10)

`scripts/evaluate.py` compares every vendor's outcome against the answer key in
`data/tracking_vendors.csv` and reports elimination precision, recall and — the
number that matters for defensibility — **reason accuracy**: eliminated, and for
the clause the key names. A rule engine that rejects everybody scores perfect
recall and is useless; one that rejects the right vendor for the wrong clause is
not defensible if challenged, which is the point of Section 5.2.

Against the GHMC tender — the real 68-page notification, 5 synthetic bids:

| Metric | Value |
|---|---|
| Elimination precision | 100% |
| Elimination recall | 100% |
| F1 | 100% |
| Reason accuracy | 100% |

| Vendor | Intended | Predicted | Clause cited |
|---|---|---|---|
| 01 | pass | needs_review | — |
| 02 | eliminate | not_compliant | 5 (turnover) ✓ |
| 03 | eliminate | not_compliant | 7 (missing authorisation) ✓ |
| 04 | eliminate | not_compliant | 3, 4 (debarment) ✓ |
| 05 | pass (exactly on both thresholds) | needs_review | — |

Note that a passing vendor reports `needs_review`, not `compliant`: formatting
and signing rules are always left to a human (Section 4.3), so nothing is ever
declared fully clear. That is the honest answer, and it is why `verdict` is
three-way rather than a boolean.

The first run scored 67% recall. The miss was a bidder that **disclosed its own
debarment in the bid text** while `is_blacklisted` — a manual flag under Section
5.8 — was unset, so the rule engine never saw it. Self-declared debarment is now
extracted, and the elimination quotes the bidder's own words:

> Your bid discloses that you are debarred or under insolvency proceedings:
> *"We disclose that our firm was debarred by the Public Health Engineering
> Department, Government of Chhattisgarh vide order dated 11.07.2023…"*

A reviewer's manual flag still wins when set: knowledge of an official
debarment list outranks what a bidder chose to admit.

```bash
cd backend
../.venv/bin/python -m scripts.evaluate                       # all tenders
../.venv/bin/python -m scripts.evaluate --tender NOTIF_supply_01 --json run.json
```

## Test data (Section 9.2)

15 synthetic bids, 5 per notification, 9–10 pages each, written as real Indian
technical bids. Ground truth is fixed **before** the prose (Section 9.2.1) and
written to the tracking sheet in the same run, so the answer key cannot drift
from the files.

Each tender's set contains a compliant bidder, one missing exactly one document,
one below a numeric threshold, one sitting **exactly** on the thresholds, and —
across the corpus — debarred bidders. Strong and weak write-ups are mixed so the
Section 5.4 fluency-bias guard is testable: one of the passing vendors on every
tender writes badly.

Enclosure checklists are generated from the requirement list the pipeline
actually extracted from that notification, not from a hand-written list. The
first evaluation run failed because of exactly this: the GHMC tender demands 49
documents and the bids enclosed 14, so a compliant vendor was reported
non-compliant — the fixture was wrong, not the pipeline.

```bash
cd backend && ../.venv/bin/python -m scripts.make_vendor_bids
```

## What's still needed

1. **More notifications** — 3 of the 5–10 Section 9.1 asks for, covering two of
   three sectors. IT services and at least one scanned document are missing.
2. **`portal_source` in `data/tracking_notifications.csv`** — only the collector
   knows which portal each document came from.
3. **Synthetic vendor bids** (Section 9.2) — none yet, so the gap report has
   only been exercised against fixtures. Ground truth goes in
   `data/tracking_vendors.csv` **before** generating each document.

## Not yet built

Phases 3–7: elimination rule engine, shortlist, query router, evaluation harness.
