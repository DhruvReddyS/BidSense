# BidSense

Tender intelligence platform. Build spec: [BidSense_Scope_v2.md](BidSense_Scope_v2.md).

**Status: Phases 0–2 complete.** Schema and stores, ingestion and extraction, and the Part 1 vendor tool (gap report, RAG Q&A, Next.js frontend). Phase 3 (company-side elimination) not started.

The stack has been run end to end against a real LLM: PDF upload → parse →
LangGraph extraction → PostgreSQL + Qdrant → gap report with cited clauses →
grounded Q&A across a three-tier provider chain — **every tier verified to
extract correctly**, see [Model routing](#model-routing-section-81).

## Quick start

```bash
cp .env.example .env          # ports 5433 / 6343 avoid the multi-agent-legal-rag stack
docker compose up -d
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend
../.venv/bin/python -m scripts.bootstrap   # Alembic migrate + create Qdrant collection
../.venv/bin/python -m scripts.verify      # health check
../.venv/bin/python -m pytest -q           # 574 tests
```

`--recreate` on bootstrap drops and rebuilds both stores. Destructive.

## Layout

```
backend/app/
  schemas/      Section 6 shared extraction schema (Pydantic)
  db/models/    SQLAlchemy tables (hybrid normalized + JSONB)
  vector/       Qdrant collection, payload schema, BGE embeddings
  llm/          Section 8.1 provider chain (Gemini -> Groq -> Ollama)
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

Set `LLM_PROVIDER` to `gemini`, `groq`, `xai`, `ollama`, or `chain` (the
default, which walks `LLM_CHAIN` in order). No code change — every provider
implements `generate_structured` with native schema-constrained decoding, and
page selection sizes itself to whichever one is active. See
[Model routing](#model-routing-section-81).

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

## Model routing (Section 8.1)

**One chain serves both extraction and RAG. It is a speed and availability
ladder, not a capability ladder.**

```
LLM_PROVIDER=chain
LLM_CHAIN=gemini,groq,ollama
```

| tier | provider / model | role |
|---|---|---|
| 1 | Gemini (`gemini-3.6-flash` + fallbacks) | primary; best quality, hardest quota |
| 2 | Groq `openai/gpt-oss-120b` | hosted, own quota, absorbs most exhaustion |
| 3 | Ollama `qwen3:4b` | offline last resort |

Measured on the 101-page IIT (ISM) tender, six header fields, ground truth read
from the PDF rather than from another model:

| tier | model | header | eligibility | documents | seconds |
|---|---|---|---|---|---|
| 1 | gemini-3.5-flash-lite | **6/6** | 14 | 10 | 27.5 |
| 2 | groq openai/gpt-oss-120b | **6/6** | — | — | **2.9** |
| 2 | groq qwen/qwen3.8-27b | **6/6** | 14 | — | 12.3 |
| 3 | ollama qwen3:4b | **6/6** | 10 | 10 | 80.4 |
| — | ollama qwen2.5:14b-instruct-q4_K_M | **6/6** | — | — | 49.1 |
| — | ollama qwen3:14b | **6/6** | — | — | 59.2 |

**All three tiers extract correctly.** The chain exists to keep working when a
quota runs out, not to trade accuracy for availability.

### The correction that produced this

An earlier version of this README said `qwen3:4b` "misses fields". That was
wrong, and it was wrong in a way worth recording: the fields were missing
because the prompt had instructions but no worked examples, not because the
model could not find them.

| document | bare prompt | with worked examples |
|---|---|---|
| IIT (ISM) 101p | 2/6 | **6/6** |
| GHMC 68p | 0/2 | **2/2** |

Same model, same document, same selected pages. Under the bare prompt the model
returned the literal string `"None"`, which read as a hallucination and was
actually the model saying it could not find the field. No value leaked from the
examples — every extracted value is the document's own.

The effect is not only accuracy. Both local 14B models **time out at 601s under
the bare prompt** and answer 6/6 in under a minute with the examples — under
schema-constrained decoding a model that does not know what shape the answer
takes will fill the schema indefinitely. The examples make it converge.

Two more operational findings worth keeping, both measured on qwen2.5:14b:

- **Schema-constrained decoding costs ~19x.** The same 19k-character prompt
  takes 13.5s as free text and 253.7s with a JSON schema attached. Local
  structured extraction is not the same workload as local chat.
- **Two 14B models cannot share this machine.** Cycling between them thrashes
  VRAM (15.2GB each on 25.7GB) and turns a 13.5s call into 254s. Benchmark one
  local model at a time or the numbers measure the swapping, not the model.

The lesson generalises: a capability gap and a prompting gap are
indistinguishable from outside, so `scripts/benchmark_extraction.py` holds the
document, the page selection and the scoring fixed and varies one thing at a
time. `--verify-truth` separately confirms every expected value is present in
the pages actually sent, so "the model missed it" and "selection never sent it"
cannot be confused either.

### RAG uses the same chain

No separate routing. Retrieval hands the model a handful of scored passages, and
every tier answers that well — `qwen3:4b` answered 8 of 8 real questions
correctly with citations while scoring 2/6 on bare-prompt extraction of the same
tender. Q&A over retrieved chunks is a much smaller task than reading 28 pages.

### Quota, which is the real constraint

| provider | limit | consequence |
|---|---|---|
| Gemini | 5 req/min, **20 req/day per model** | 6 calls/document → ~3 documents/day/model; fails over across 4 models |
| Groq | 30 req/min, **8,000 tokens/min** | the binding limit is tokens: a 15,009-token request is refused outright |
| Ollama | none | bounded by local hardware |

**Groq's 8,000 TPM cap is why tier 2's 2.9 seconds is not a full-document
number.** That figure is one field group (~4,400 tokens) on a warm connection.
A whole document is six such groups, and at 8,000 TPM they must be paced —
hence `GROQ_RPM=2`, which puts a full six-group extraction at roughly three
minutes rather than eighteen seconds. Page selection sizes itself to the active
provider (`input_char_budget`), so the same document that sends 60,000
characters to Gemini sends 15,400 to Groq.

A hosted provider having a *smaller* usable window than the local one is not the
intuitive ordering, and is exactly the kind of thing that shows up as
unexplained 413s if it is not written down.

### Not in the chain

- **Llama 3.3 70B** — not available on this Groq account. `openai/gpt-oss-120b`
  is the substitute, benchmarked above at 6/6.
- **xAI / Grok** — the provider is built and unit-tested (`app/llm/xai.py`), and
  the key is valid, but the account has no credits: every endpoint returns 403.
  A billing blocker, not a code one. Add credits and put `xai` in `LLM_CHAIN`.

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

Across all three real tenders, 15 bids of 60–172 pages each:

| Metric | Value |
|---|---|
| Elimination precision | **100%** |
| Elimination recall | **100%** |
| F1 | **100%** |
| Reason accuracy | **100%** |

15 of 15 correct — 9 eliminations, 6 passes, no false positives or negatives,
and every elimination citing the clause the answer key names.

| Tender | Eliminations, with the clause cited |
|---|---|
| IIT (ISM) | `1.1(4)` similar work below 80% of estimate · `2.6(b)` no digital signature certificate · `1` turnover below 30% of estimate |
| GHMC | `5` turnover below ₹3 Cr · `7` no manufacturer's authorisation · `3, 4` debarment |
| HGCL | `28.1 vi)` liquidity below ₹49.855 Cr · `11.II(a)(h)` missing declaration · `2.2, 2.3` liquidation and debarment |

Both relative thresholds on the IIT tender resolve correctly (80% and 30% of the
estimated cost), and the borderline vendor sitting exactly on both passes —
"not less than" is `>=`, and an off-by-one there would flip that vendor alone.

Note that a passing vendor reports `needs_review`, not `compliant`: formatting
and signing rules are always left to a human (Section 4.3), so nothing is ever
declared fully clear. That is the honest answer, and it is why `verdict` is
four-way rather than a boolean — the fourth state, `not_checked`, exists so that
a run which extracted nothing cannot be mistaken for a pass.

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

15 synthetic bids, 5 per notification, written as real Indian technical bids.
Length is sized to the tender rather than chosen arbitrarily:

| Tender | Value | Bid length | Scale |
|---|---|---|---|
| IIT (ISM) boundary wall | ₹12.5 lakh | ~60 pages | compact |
| GHMC LED street lights | ₹29.9 crore | ~95 pages | standard |
| HGCL 13 MW solar EPC | ₹99.7 crore | ~172 pages | comprehensive |

The length comes from the sections that make real bids long — clause-by-clause
specification compliance, a CV per named person, a method statement per
activity, a case study per cited work, a declaration per page, an item-wise
price schedule, reproduced annexures, and for the EPC a design basis report,
an O&M plan and a survey sheet per roof block. Not padding: this is what page
selection exists to handle, and a nine-page bid never exercised it. Ground truth is fixed **before** the prose (Section 9.2.1) and
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
