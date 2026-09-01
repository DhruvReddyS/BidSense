# Running TenderIQ

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
