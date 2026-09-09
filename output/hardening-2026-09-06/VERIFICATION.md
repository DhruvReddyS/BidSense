# BidSense verification — 6 September 2026

Track A has improved substantially but its production gate remains unmet. Track B and Part 2 have not been implemented. Existing uncommitted work is preserved.

## Verified results

- Final full backend suite after the last code change: **733 passed, no failures or skips, 422.08 seconds**. The preceding full run passed 732 tests; a browser check prompted one additional action-list regression and fix.
- Frontend TypeScript check and `git diff --check` passed.
- Evaluation: **19/19 correct elimination outcomes**, including **15/15 original outcomes**. Correct outcomes include bids explicitly left for review; they are not all verified compliant bids.
- **8/12 elimination reasons verified** by the strict clause check; three compound SBI expectations do not match and one original HGCL expectation is an em dash with no clause assertion. The evaluation CLI correctly exits **1** and records `passed: false`.
- Six live header extractions on the real 101-page IIT notification: two concurrent requests per configured tier, each correct on all six expected fields. Actual models: Gemini `gemini-3.6-flash`, Groq `openai/gpt-oss-120b`, Ollama `qwen3:4b`. Gemini encountered service errors and Groq encountered rate limiting before successful recovery. This is a bounded header test, not full-document live extraction or sustained quota exhaustion.
- Six new deliberate mutations all caught: evaluation exit status, narrative honesty, explicit absence, certificate guard, quality-warning propagation to export, and duplicate-extraction locking. Mutations ran in disposable copies.
- Eight concurrent identical ingests execute one six-node graph, yield seven cache hits and one persisted tender. Eight independent processes also pass an exclusive-lock probe with no overlapping critical section. This is host/shared-filesystem locking, not distributed locking across separate hosts.
- **24 actual HTTP citation requests, six workers, 4.588 seconds**, against pages 1/100/200/382 of the real 382-page HGCL PDF at 110 DPI. Every response is a valid PNG with correct page metadata and nonzero highlights. This is loopback concurrency, not network saturation or capacity certification.
- Browser verification: the real GHMC report shows the extraction-audit warning above its verdict; details expand; citation click opens page 15 of 68 with the clause text and visibly highlighted passage. Final standalone report shows the corrected instruction to review the relevant bid section. These are existing-interface correctness checks, not approval of a Track B design.

## Changes

1. Strict evaluation rejects unassessed/missing results, missing expected clauses, substring-only clause coincidences, duplicate IDs and invalid statuses. Failure now returns nonzero.
2. Same-document extraction misses are coalesced with a bounded file lock; cache invalidation now covers parsing, normalization and canonical schemas as well as extraction prompts/graph/converters.
3. Extraction audit metadata is persisted through an applied Alembic migration. Original errors, parser warnings, validation findings and provider labels feed shared gap-report, Ask and export quality reporting. Legacy records explicitly report unknown original audit/provider instead of appearing clean.
4. Missing enclosure-list entries no longer prove substantive bid narrative is absent. Such content requires review; explicitly absent narrative and absent formal certificates still fail. Matched documents retain bid provenance, and unknown narrative actions instruct the user to inspect the relevant section.
5. Both export formats now use the same completion sentence, including the undetermined count.
6. Source-guarded GHMC data repair changes manufacturer authorization reference from `22` to `22, item 7`. Page 15 establishes parent clause 22; page 16 contains table item 7. The source hash and exact table row were verified before mutation. Requirement, snippet, page and verdict are preserved. The before/after audit is in `ghmc-citation-repair.json`; this is a specific stored-data correction, not a claim that future extraction cannot repeat this omission.

## Outstanding gates

- API-key rotation remains unconfirmed. Live success proves usable keys, not revocation of the previous keys. A status-only confirmation was requested; no secret values are needed.
- Resolve the remaining reason expectations against source evidence. SBI Version 1 expects clauses 1/5/6/8, while its blockers lack 1; Version 2 expects 5/6/8/20, all of which appear, but the current evaluator does not parse compound prose; Version 3 also names a Process Compliance Statement requirement. These need explicit, grounded multi-clause expectations, not relaxed matching to force a pass. The HGCL em-dash expectation needs an independently established clause assertion.
- Full live graph/burst exhaustion testing remains narrower than the requested production stress gate. Persistent provider retirement lasts for the process lifetime; simulated transient recovery is not automatic recovery from permanent retirement.
- PDF Latin-1 substitutions still prevent universal Unicode PDF/DOCX text equivalence; rendered layout QA across unseen multilingual inputs is not complete.
- Current real GHMC gap report has **56 checked requirements** (the tender requirements tab displays 62 across its categories), not 73. No rows have been invented to satisfy the requested preview density.
- Only after Track A verification: build the command palette, citation peek and dense gap-report slice in both themes for the user’s explicit feel/interaction approval. Broad rollout and Part 2 remain behind that approval, as requested.

## Evidence

`final-tests.log`, `final-focused.log`, `evaluation.json`, `evaluation.log`, `live-headers.json`, `live-headers.log`, `mutations.json`, `process-lock.json`, `citation-http-load.json`, and `ghmc-citation-repair.json` contain measured results. Probe scripts are retained alongside them. `code-manifest.json` binds the final source/test files to their SHA-256 hashes. Focused counts overlap with the full suite and must not be added.
