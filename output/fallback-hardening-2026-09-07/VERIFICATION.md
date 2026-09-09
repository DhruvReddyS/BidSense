# Fallback capacity hardening — 7 September 2026

## Implemented code

- Structured extraction accepts a prompt factory. On every attempted tier, the chain reselects source pages using that tier's context budget. A Gemini-sized prompt is no longer reused unchanged after falling through to Ollama.
- Each serving provider enforces its own concurrency limit. A chain semaphore created while Gemini was live no longer allows six simultaneous requests into a single-request Ollama tier. Queued requests recheck retirement before calling a tier already retired by another worker.
- Graph results retain selected pages per node. The post-extraction header validation checks those actual pages, rather than silently selecting again with a hosted-provider budget. Cache records without coverage metadata do not invent original model coverage.

## Verification

- Final complete backend suite after all code changes: **755 passed, no failures or skips, 549.97 seconds**. This includes all nine registry deletion checks and the new fallback and Unicode regressions. `git diff --check` passed.

- Three behavioral regressions failed before the fixes: fallback prompt sizing, burst concurrency and graph reselection.
- Four final new tests pass, including validation coverage. The broader focused suite passed 95 tests; counts overlap.
- All three independent mutations were killed in disposable copies: ignore the lower-tier budget, remove the serving-tier semaphore, and discard actual validation coverage.
- Full live extraction on the actual 101-page IIT notification, with one graph running through Groq and one through Ollama concurrently. Upstream quota retirement was injected; lower-tier responses were real. No source documents, cache records or benchmark rows were overwritten.
- Ollama `qwen3:4b`: all six nodes returned without an extraction error in 264.714 seconds. Every node reports the actual local model. This measures graph completion, not perfect extraction recall.
- Groq `openai/gpt-oss-120b`: three of six nodes returned in 194.997 seconds. Eligibility failed remote JSON validation, format rules hit an output limit, and header exceeded the 8,000-token account limit (8,443 requested). The graph retained those errors and validation findings instead of claiming a clean result. This isolated Groq probe intentionally had no live tier below it.
- The regex cross-check detects the missing deadline under both lower tiers using the actual header selection. The Groq header was already missing after its request failed; the Ollama deadline was deliberately cleared for the negative check.
- These runs and the concurrency/mutation tests strengthen the evidence. They are not a claim that real provider quotas were deliberately exhausted or that permanent retirement automatically recovers without a backend restart.
- Evaluation remains **17/19 outcome matches**, **10/12 elimination-reason matches**, with the original subset at **13/15 outcomes**. The CLI correctly exits 1. The two IIT pass fixtures lack the required Annexure-V undertaking; a whole-source search is retained here alongside the earlier page-level source audit. No expected pass status or source bid was changed to force green results.

## Required stage boundary

The user confirmed key rotation is **not completed**. Benchmark/source discrepancies also remain unresolved. Track A is not certified. Track B and Part 2 have not started, following the user's explicit instruction to finish every Track A gate first. The existing UI's visible redesign cannot begin on the strength of passing unit tests alone.

Evidence: `mutations.json`, `live-groq.json`, `live-ollama.json`, `live-graphs.log`, `evaluation.json`, `evaluation.log`, `iit-whole-source-search.json`, and `code-manifest.json`. PDF export verification is in `../pdf-hardening-2026-09-06/VERIFICATION.md`.
