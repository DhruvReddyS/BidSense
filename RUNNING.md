# Running TenderIQ

## Authentication and authorization

Set unique `AUTH_SECRET` and `REVIEWER_REGISTRATION_CODE` values before sharing
the service. Vendor registration is open; reviewer registration additionally
requires the invitation code. The browser stores a short-lived bearer token and
sends it explicitly with protected requests.

Authentication establishes identity. RBAC is separate: company-pool routes
require the reviewer role, while vendor report routes verify `owner_user_id` and
return 404 rather than exposing another bidder's record.

Generate the isolated premium demo corpus and router metrics with:

```bash
cd backend
../.venv/bin/python -m scripts.make_premium_demo_corpus
../.venv/bin/python -m scripts.evaluate_router
```

Back up PostgreSQL and Qdrant with `scripts/backup.sh /absolute/backup/path`.

For a reproducible container deployment, set `.env` secrets and run
`docker compose --profile app up -d --build`. The ordinary `docker compose up -d`
continues to start only PostgreSQL and Qdrant for local development.

## One-time setup

```bash
# 1. Services (PostgreSQL + Qdrant)
docker compose up -d

# 2. Python environment
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

# 3. Create the schema and the vector collection
cd backend
../.venv/bin/python -m scripts.bootstrap
../.venv/bin/python -m scripts.verify      # should print PASS

# 4. Frontend dependencies
cd ../frontend && npm install
```

Optional but recommended — OCR for scanned tenders:

```bash
brew install tesseract poppler
```

PDF export requires Pango (1.44 or newer): `brew install pango` on macOS,
or `apt-get install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0`
on Debian/Ubuntu. The PDF regression tests also require Poppler (`poppler-utils`
on Debian/Ubuntu). Python dependencies include pinned WeasyPrint 69.0.
Bundled, licensed Noto fonts cover Latin, Greek, Cyrillic, Devanagari and Telugu.
An unsupported character returns HTTP 422 with a DOCX alternative, rather than
silently replacing source text. PDF copy/accessibility uses ActualText to preserve
Indic shaping; readers that ignore ActualText may extract reordered combining
marks. DOCX preserves the original Unicode text. Re-run the Unicode and concurrent
export tests when upgrading WeasyPrint: the ActualText adapter uses its draw hook.

Without these, a scanned page is reported as **content missing from
extraction** rather than being read. That is deliberate: silently returning an
empty page would read downstream as "this clause is not in the tender".

## Configuration

Everything lives in `.env` (copy from `.env.example`). The values that matter:

```bash
LLM_PROVIDER=gemini          # or 'ollama' — no code change either way
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
GEMINI_RPM=5                 # free-tier quota: 5 requests/minute per model
EMBEDDING_DEVICE=auto        # CUDA, then Apple Metal, then safe CPU fallback
EMBEDDING_BATCH_SIZE=64
INGEST_WORKERS=2             # raise to 6–12 only with matching paid LLM quota
INDEX_WORKERS=1
DEFER_VECTOR_INDEXING=true   # Level 1 ready before Level 3 search indexing
OCR_WORKERS=3
JOB_EXECUTION_MODE=thread    # local development
JOB_POLL_SECONDS=0.5
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=10
```

`GEMINI_RPM` is the single most important knob. The extraction graph makes six
requests per document, so at the free tier one document takes ~65 seconds. On a
paid key, raise it and the wall clock drops proportionally.

## Day-to-day

Two terminals:

```bash
# API
cd backend && ../.venv/bin/python -m uvicorn app.api.main:app --reload --port 8100

# Frontend
cd frontend && npm run dev
```

Then open **http://localhost:3000**. API docs are at
http://127.0.0.1:8100/docs, and http://127.0.0.1:8100/api/health reports each
dependency separately.

### Production / 1,000-user topology

The app Docker profile separates API and ingestion workers automatically:

```bash
docker compose --profile app up -d --build
docker compose --profile app up -d --scale worker=4
```

`JOB_EXECUTION_MODE=database` is injected into both services. Scale API replicas
behind a load balancer for request traffic and workers separately for document
throughput. Keep the sum of `WEB_CONCURRENCY × (DB_POOL_SIZE +
DB_MAX_OVERFLOW)` below PostgreSQL's connection ceiling; add PgBouncer before
scaling to many hosts. Provider RPM/TPM remains the extraction ceiling even
when compute capacity is available.

## Command line

The CLI is faster than the UI for bulk work and prints extraction diagnostics.

```bash
cd backend

# Parse only — no LLM, no database. Safe first look at any new document format;
# shows page count, per-page character counts, tables found, and OCR status.
../.venv/bin/python -m scripts.ingest inspect ../data/notifications/

# Full pipeline on one file or a whole folder
../.venv/bin/python -m scripts.ingest notification ../data/notifications/ --report run.json

# A vendor bid against a tender
../.venv/bin/python -m scripts.ingest vendor ../data/vendors/ \
    --tender-id "TSTS/2026/IT/0042"

# Skip vector indexing (faster when only checking extraction accuracy)
../.venv/bin/python -m scripts.ingest notification ../data/notifications/ --no-index
```

`--report` writes per-node timings, warnings and errors as JSON — this is what
feeds the latency and extraction-accuracy metrics in Section 10.

## Tests

```bash
cd backend && ../.venv/bin/python -m pytest -q
```

Tests that need PostgreSQL, Qdrant, the BGE model or the collected tender PDFs
skip themselves when those are unavailable, so the suite always runs.

```bash
../.venv/bin/python -m pytest -q -k "not real"    # skip the real-document tests
../.venv/bin/python -m pytest tests/test_compliance.py -q   # one module
```

## Switching the LLM

Section 8.1's fallback is a config change, not a code change:

```bash
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3:14b
OLLAMA_NUM_CTX=16384
OLLAMA_THINK=false     # true is ~4x slower but more faithful to verbatim text
```

Then restart the API. Note that a local 14B model takes minutes per call on a
24GB machine that is also running Docker; see the LLM table in the README.

## Resetting

```bash
cd backend
../.venv/bin/python -m scripts.bootstrap --recreate    # DROPS both stores
```

To stop everything:

```bash
docker compose down          # add -v to delete the data volumes too
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Cannot reach the TenderIQ API` in the browser | API not running | Start uvicorn on port 8100 |
| Upload returns 429 / `RESOURCE_EXHAUSTED` | Gemini free-tier quota | Already retried automatically; lower `GEMINI_RPM` if it persists |
| `403 PERMISSION_DENIED` from Gemini | The API key's project is blocked | Create a new project and key in AI Studio |
| Health shows `ocr_available: false` | Tesseract/poppler missing | `brew install tesseract poppler` |
| Health shows `qdrant: false` | Container down, or port taken | `docker compose up -d`; TenderIQ uses 5433/6343 to avoid clashes |
| Extraction returns nothing for a long tender | Page selection found no cues | Run `scripts.ingest inspect` to see what was parsed |

### Provider fallback and key replacement

Extraction reselects document pages for the context budget of each attempted
provider. The serving provider enforces its own concurrency limit, even when a
request started on a hosted tier before falling through to Ollama. Validation
uses the header pages from the final attempt. Cached entries without page
coverage metadata are checked against the source without claiming that the
original model saw those pages.

Persistent quota/authentication failures retire a tier for the backend process
lifetime; transient failures are retried on later calls. After revoking old keys
and installing replacements in `.env`, restart the backend to reload credentials
and clear retired clients. A successful request with a new key does not establish
that the old key was revoked.
