# BidSense — demo runbook

## Before the panel arrives

```bash
docker compose up -d
cd backend && ../.venv/bin/python -m uvicorn app.api.main:app --port 8100
cd frontend && npm run dev
```

Then **do one throwaway upload and delete it**, or leave the API process running
from a previous session. This is measured, not a precaution:

```
notification, cold chain   181 s   ← 121 s of it was one model's exhaustion discovery
bid, warm chain             61 s
```

Gemini's free-tier models are discovered as exhausted one at a time, and each
discovery costs a request plus a retry backoff. The first upload after an API
restart pays for all of them; every upload after that goes straight to the live
tier. Restarting the API just before a demo is the one avoidable way to make the
first extraction look slow.

Warm the two slow paths:

```bash
curl -s http://127.0.0.1:8100/api/health
curl -s -X POST http://127.0.0.1:8100/api/gap-report -H 'Content-Type: application/json' \
  -d '{"tender_id":"TENDER No.01/SE(Electrical)/GHMC/2024-25","vendor_id":"VENDOR_supply_01_01"}' >/dev/null
```

## What is already loaded

Three tenders, five bids each, every report verified rendering.

| tender | notification | requirements | bids | use for |
|---|---|---|---|---|
| **GHMC** LED street lights | 68 p | **73** | 5 × ~95 p | the main walkthrough — densest report |
| **HGCL** 13 MW solar EPC | **382 p** | 60 | 5 × ~172 p | scale: page selection on a huge document |
| IIT (ISM) boundary wall | 101 p | 32 | 5 × ~60 p | the corrigendum / staleness story |

## Which bid to open, and why

Ranked by blocking items first, then requirements met.

**GHMC — open `VENDOR_supply_01_05` (best) then `VENDOR_supply_01_04` (worst).**

| bid | verdict | met | blocking |
|---|---|---|---|
| supply_01_05 | needs review | 52/73 | **0** |
| supply_01_01 | needs review | 50/73 | 0 |
| supply_01_02 | not compliant | 51/73 | 1 — turnover ₹1.8 Cr below ₹3 Cr |
| supply_01_03 | not compliant | 48/73 | 1 — manufacturer's authorisation absent |
| supply_01_04 | not compliant | 52/73 | 2 — debarment disclosed in the bid text |

The pair worth showing is **01_04 against 01_05**: 01_04 *meets more requirements
than anybody* (52/73) and is still the worst bid in the set, because it discloses
its own debarment. That is the whole argument for a count that is explicitly not
a score — a ranking by "requirements met" would have put it top.

**HGCL — `civilworks_02_01` (0 blocking) vs `civilworks_02_02`** (liquidity
₹18.4 Cr against a ₹49.855 Cr floor). Good for showing a relative threshold
resolved from the tender's own estimated cost.

**IIT (ISM) — `civilworks_01_05`** is cleanest; `civilworks_01_04` carries the
turnover shortfall and is the one with the **staleness banner** already armed.

## The route

1. **Home** → three tenders, 153 requirements.
2. **GHMC** → key facts row; note the 68-page notification reduced to the pages
   that matter.
3. **Open `supply_01_05`** → verdict, the count with its "not a score" caveat.
4. **Hover any figure** → the dotted rule goes solid and names its destination
   (`page 12 ↗`) *before* the click. This is the product's core claim.
5. **Click it** → the source page, scrolled to the highlighted clause.
6. **Switch to `supply_01_04`** → same tender, more requirements met, worse bid.
   Read the blocking item: it quotes the bidder's own words.
7. **Ask tab** → "What is the EMD amount?" → strong-match answer, click a
   citation.
8. **Export PDF** → the same report as a file.
9. **IIT (ISM) → `civilworks_01_04`** → the amendment banner and one-click
   re-check.

## Say this before someone finds it

- **Ask takes ~30 s per question.** Gemini's daily quota is spent, so answers
  come from Groq, paced at 2 requests/minute to respect an 8,000 tokens/minute
  free-tier cap. That is a rate limiter doing its job, not the model thinking.
- **A live notification upload takes 1–3 minutes.** Six extractors, free-tier
  pacing. Start it and talk over it. Measured end to end on a tender the system
  had never seen: 181 s cold, and the bid that followed took 61 s.
- **Nothing is ever reported as fully clear.** Formatting and signing are always
  left to a human, so the best possible verdict is "needs review".

## If something breaks

| symptom | fix |
|---|---|
| every API call fails | `docker compose up -d`, then restart uvicorn |
| `MODULE_NOT_FOUND` in the web app | `cd frontend && rm -rf .next && npm run dev` — something ran `next build` against a live dev server |
| upload fails with a quota message | every tier is spent; set `LLM_PROVIDER=ollama` in `.env` and restart the API (slower, offline) |
| a citation says "not retained" | that document predates the store; re-upload it |
