# Document identity hardening — 6 September 2026

This supersedes the previous 19/19 outcome claim for the current code. Track A is not certified; Track B and Part 2 remain unstarted under the requested sequencing.

## Implemented

- Deduplication preserves explicit Annexure, Appendix and Form identifiers, including identifiers inside parentheses or after boilerplate. It no longer collapses SBI Annexure-B and Annexure-II.
- Matching rejects conflicting identifiers before alias, lexical and embedding matching. A generic title cannot establish which numbered form was submitted; it becomes a review candidate. Explicit tender aliases still work.
- A bidder’s explicit NOT ENCLOSED declaration takes precedence over a positive match to another similarly named enclosure.
- Evaluation supports explicit numeric clause lists with **all-of** semantics. Clause 5 alone cannot satisfy “5, 6, 8 and 20.” Unstructured named-requirement prose remains unresolved rather than guessed.
- Filled the original HGCL answer key’s missing reference using independent source evidence: clause 11 on page 24, II(a)(h) on page 25, Form F-12. Changed no expected outcome or bid content. Exact before/after and source hash are recorded in `answer-key-citation-repair.json`.

## Evidence and findings

- New document-identity regressions reproduced **5 failures / 2 passes before the fix**.
- Focused matching, requirements, compliance, action and evaluation suite: **169 passed**. Final identity suite, including the additional explicit-absence regression: **9 passed**. These counts overlap.
- Four mutations were caught in disposable copies: remove form identity from deduplication; permit conflicting forms; remove explicit-absence priority; use any-of instead of all-of for expected clauses. The explicit-absence mutation initially survived, so an additional positive-lexical-candidate regression was added, verified passing in the real checkout, and verified failing under mutation.
- Current evaluation: **17/19 outcome matches** (12 TP, 5 TN, 2 FP, 0 FN), **10/12 reason matches**, no blank expected clauses. The original 15 subset is **13/15 outcomes**, with **9/9 elimination reason checks**. The CLI exits nonzero, as required.
- SBI Version 3 now exposes two separate blockers: Demand Draft and **Process Compliance Statement (Annexure-II)**. The latter is grounded at notification page 8 but has no numbered clause. The existing compound prose expectation needs a structured named-requirement/page assertion. SBI Version 1 still lacks an automated clause-1 elimination; it must not be marked correct simply because another expected clause was found.
- IIT bids `VENDOR_civilworks_01_01` and `VENDOR_civilworks_01_05` are marked pass by the answer key but lack the required Annexure-V self-certification in their stored enclosure lists. Notification page 13 requires it; page 79 defines the site-inspection undertaking. Their own Annexure V (pages 57 and 55) instead contains certifications/accreditations. The old matcher could use a differently numbered annexure. Their source hashes and evidence are in `iit-source-review.json`. No bid or expected pass status was changed to make this metric green. The extraction/source/fixture discrepancy needs reconciliation.

## Stage boundary

Unresolved evaluation evidence and unconfirmed old-key revocation still prevent Track A certification. The earlier bounded live-provider and citation tests remain documented in the preceding report; this pass does not expand them into a claim of sustained provider exhaustion/recovery or universal multilingual export parity. The requested real 73-row GHMC preview is also not present in the stored data. No Track B approval or Part 2 completion is claimed.

Live API verification: the restarted API returned HTTP 200 and a separate missing Annexure-II item with notification page 8; see `sbi-live-api.json`.

Final full backend suite: **746 passed, no failures or skips, 552.63 seconds**. Backend source remained unchanged after that run started. One additional explicit-absence regression was added afterward and passed in the separate nine-test identity suite; the full run therefore does not include that additional test. `git diff --check` also passed.
