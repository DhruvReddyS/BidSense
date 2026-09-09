# BidSense — current-code verification, 5 September 2026

**Part 1's production gate is not met. Track A is partially hardened; Track B and Part 2 have not started.** Existing uncommitted work was preserved. No UI implementation or answer-key changes were made in this pass.

## Current state, checked rather than inherited

- The initial checkout collected 673 backend tests. With PostgreSQL/Qdrant initially stopped, the full baseline completed with **597 passed, 71 skipped, 5 failed** in 584.24 seconds. Two failures were database connection errors. Three were an obsolete `_FastLimiter.acquire()` test-double signature that no longer accepted the token-cost argument used by the current Gemini implementation.
- Started the existing configured PostgreSQL and Qdrant containers with `docker compose up -d`; did not recreate their volumes or bootstrap/reseed the database.
- Final full-suite result: **694 passed, zero failed, zero skipped**, in **663.87 seconds (11 minutes 3 seconds)**, after the final code changes and with both services available. See `final-tests.log`.
- `npx tsc --noEmit` passed. No browser interaction or UI approval claim is made.
- Current evaluation covers **19 bids**, not 15: **12 true eliminations, 5 true passes, 2 false eliminations, 0 missed eliminations** against the current answer key. That is **17/19 correct outcomes**, with **8/12 eliminations matching the expected-clause check**. Precision is 12/14, recall 12/12, F1 12/13. The original 15-bid subset is **13/15 correct**, with 8/9 expected-clause matches.
- The two false eliminations are `VENDOR_supply_01_01` and `VENDOR_supply_01_05`. The former is rejected for missing technical manpower information; the latter also has an alternative-proposal finding. Staffing information is actually present in the source bids on pages 30 and 26, respectively, but absent from their stored submitted-document lists. The extraction prompt and page-selection logic focus on enclosures; body evidence requires further grounded handling.
- The current GHMC report for the first bid has **56 requirements**, not the requested 73. No sparse or fabricated state was substituted for the requested future design review.
- **API-key rotation is unverified.** A local key's presence or a successful API call would not establish that the previous credential was revoked. Confirmation was requested without asking for secret values. No secrets were copied into this report.

## Fixes made and checked

| Subsystem | Reproduced failure | Change and evidence |
|---|---|---|
| Citation document store | Eight simultaneous same-document writes produced seven `FileNotFoundError`s because all writers shared one `.part` filename. Failed copies also left staging files. | Unique staging file per writer, atomic replacement, cleanup in `finally`. Regression tests failed before the change and passed after it. |
| Extraction cache | 64 successful concurrent lookups recorded only 16 hits in the initial probe. | Atomic SQL `UPDATE ... RETURNING` increments. Database conflict handling retains one winning payload and its matching provider. An additional eight-writer probe produced one row with consistent payload/provider and no warnings. |
| Provider attribution | Only 15/40 simulated burst requests reported their own serving tier; failed calls could retain a previous success label. | Execution-context-local provider/model labels, reset before each chain call, serialized provider construction. Graph nodes carry their own labels through LangGraph reducers; ingestion aggregates successful node labels instead of reading a process-wide last result. |
| Token pacing | The refill spent by one waiting caller was spent again by the next caller. A controlled clock measured 2 seconds where two successive reservations required 4. | Reserve token debt while waiting. New regression plus existing pacing tests pass. |
| PDF export | Literal `<b>…</b>` in source data disappeared from PDF but remained in DOCX. | Escape source data before ReportLab paragraph parsing while keeping application-authored formatting separate. Text round-trip regression passes. |
| Existing test infrastructure | Three Gemini failover tests failed before reaching the provider assertions. | Updated the test limiter to accept the current token-cost argument; retained all dead-model request-count and successful-caller assertions. |

## Verification scope

- **Storage/citation/cache focused suite:** 52 passed.
- **Routing/extraction/pipeline/cache focused suite:** 143 passed. Additional model-context and mixed-tier graph tests passed.
- **Export and registry probes:** 34 passed.
- **Pacing suites and refill regression:** 26 passed.
- **Concurrent exports:** four different synthetic reports, each containing 73 requirements, rendered concurrently to PDF and DOCX. Recovered text contains every request's 73 unique requirements, its bidder identity, and the count-not-score caveat, with no other request's bidder identity. These are adversarial fixtures, not the real GHMC report or a claim of universal PDF/DOCX byte equivalence.
- **Large-document citation rendering:** 12 requests, four workers, pages 1/100/200/382 of the actual 382-page HGCL PDF. Direct renderer at 72 DPI completed in 3.588 seconds. A second run through FastAPI TestClient at the configured 110 DPI completed in 6.276 seconds. All returned valid PNGs, correct page/page-count metadata, and nonzero highlights. This checks concurrent endpoint execution; it is not an external-network saturation benchmark, memory-capacity measurement, or browser click-through verification.
- **Lower-tier extraction:** controlled Gemini→Groq and Gemini→Groq→Ollama fallback tests execute the real graph, conversion, validation, and SQL persistence with scripted provider responses. Both produce provider labels and regex-derived missing-field findings. These prove code-path behavior, not live Groq/Ollama extraction accuracy.
- **Registry deletion mutations:** removing each of the nine actual registry entries independently triggers the existing inverse guard. Nine parameterized regression checks now preserve this verification.
- **Six implementation mutations:** cache increment, atomic document publication, chain attribution, graph attribution, token reservation, and literal export text. Every mutation was made in a disposable copy and caught by its targeted test. The working checkout was never mutated for these experiments. See `mutations.json`.

Focused counts overlap and must not be added together as a total.

## Remaining gates and limits

1. Resolve the evaluation discrepancies against source evidence, including the GHMC body-evidence omissions and clause-grounding differences. The SBI expected-clause descriptions are compound prose, while the evaluator currently uses substring matching; its failed clause scores cannot be corrected by simply relaxing the match. One original expected clause is an em dash and is accepted without a clause assertion. Thus the reported reason metric itself needs a stricter, explicit definition.
2. Verify old-key revocation and replacement-key installation, then perform controlled live-provider extraction/burst tests. Persistent retirement currently lasts for the process lifetime; the simulated recovery tests exercise transient failures, not automatic recovery of a permanently retired tier.
3. Carry extraction degradation and provider provenance through all report/API/export/frontend surfaces. The current job result includes attribution, but the export route does not supply `ExportContext.extracted_by`, and UI components do not consistently render the available provider field. This pass fixes attribution at its origin; it does not claim complete presentation coverage.
4. Concurrent cache misses can still duplicate LLM work before one cache insertion wins. Atomic insertion/hit counting is not single-flight extraction. Cross-process ingest/upsert contention needs broader stress coverage before certification.
5. PDF still uses Latin-1 substitutions while DOCX retains Unicode; universal text identity for unseen multilingual documents is not established. Full rendered layout QA is also pending. The two renderers have a known difference in the explicit undetermined-count phrase, which appears in PDF's completion sentence but not DOCX's equivalent sentence.
6. The evaluation CLI currently exits zero after printing an unsuccessful evaluation. A zero exit status must not be used as evidence that the evaluation passed.
7. After those Track A gates pass, build only the requested command palette, citation peek, and real dense gap-report approval slice in both themes. Broader UI rollout requires the user's approval of that actual interaction. Part 2 remains behind completed and approved Track B.

## Reproduction and artifacts

Run backend commands from the repository's `backend` directory:

```sh
../.venv/bin/python -m pytest -vv
../.venv/bin/python -m scripts.evaluate --json ../output/hardening-2026-09-05/evaluation-rerun.json
../.venv/bin/python -m pytest tests/test_concurrent_storage.py tests/test_provider_attribution.py tests/test_hardening_probes.py -q
```

`final-tests.log`, `final-evaluation.json`, `baseline-tests.log`, `baseline-evaluation.json`, before/after focused logs, `mutations.json`, `citation-api-load.json`, and `cache-concurrent-writes.json` retain the measured evidence. Auxiliary mutation/API/cache probe scripts in this directory run from `backend` with `PYTHONPATH=.` using the existing virtual environment. They isolate mutations and clean up their own temporary cache rows.

`code-manifest.json` records SHA-256 hashes for 122 backend source/test/config files and the starting Git commit. The checkout remains uncommitted; these hashes bind the evidence to the actual files tested.
