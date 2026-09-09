# Track A continuation and Track B UI — 7 September 2026

## Outcome

Track A's remaining 17/19 benchmark discrepancy was traced to a synthetic-source
defect: the two IIT pass fixtures asserted a site visit but did not contain the
signed Annexure-V self-certification required on notification page 79. The
generator now includes the requirement and renders an executed tender-specific
form. It does not relax document-identity matching, confuse the bidder's internal
Annexure V with the tender form, or change the answer-key outcomes.

Track B's redesign was continued and interaction-hardened. The command
palette now tolerates partial bid-index failures, resets stale results, uses
unique command identifiers, and supports Home/End navigation. Citation peeks
close on ancestor scrolling, stay within the viewport, and work better on small
screens. Compact report rows are materially denser. A shared document-processing
animation now carries one motion language across extraction, matching, and
committee evaluation: stacked records are scanned and receive a decision stamp.
It includes a reduced-motion fallback.

Part 1 is production-certified at the application level. Part 2 Level 1 is now
implemented: mandatory criteria are evaluated deterministically, decisions and
reasons persist to PostgreSQL, Qdrant status tags stay synchronized, and the new
company reviewer workspace supports filtering, search, evidence drill-down, and
reruns. Final selection remains explicitly assigned to the evaluation committee.

The remaining core company workflow is also complete: multi-file bid intake,
reviewer-selected Level 2 factors and a non-ranked qualified pool, Level 3
structured/vector/hybrid/audit routing, persistent shortlist status with Qdrant
retagging, and PDF/DOCX committee exports. The UI presents these as one deliberate
three-stage journey and keeps the human decision caveat at every judgment boundary.

Authentication and RBAC are independent. Authentication provides salted PBKDF2
credentials and expiring signed tokens; RBAC separately enforces reviewer-only
pool operations and per-vendor ownership without disclosing a competitor's record.
Reviewer self-registration requires an invitation code. Typed corrigenda update
the authoritative notification and replay Level 1; unsupported changes stay
visibly unapplied.

An isolated premium corpus adds **45 PDFs / 4,887 pages** with 18 compliant and
27 elimination outcomes, 9 exact-threshold cases, 6 debarment cases, and mixed
prose quality. Every file has a pre-declared JSON/CSV answer key.

## Changed in this continuation

- `backend/app/bidgen/tenders.py`
- `backend/app/bidgen/render.py`
- `backend/tests/test_bidgen.py`
- `backend/app/compliance/elimination.py`
- `backend/app/api/routes.py`
- `backend/app/api/schemas.py`
- `backend/tests/test_elimination.py`
- `frontend/components/CommandPalette.tsx`
- `frontend/components/Cited.tsx`
- `frontend/components/DocumentProcess.tsx`
- `frontend/components/ReviewerWorkspace.tsx`
- `frontend/app/tenders/[tenderId]/review/page.tsx`
- `frontend/app/globals.css`
- regenerated ignored IIT vendor PDFs in `data/vendors/`

Regenerated pass-fixture hashes:

- `VENDOR_civilworks_01_01.pdf`: `a6668fd7dc2c58142b00fa3039198b7cccc521fe6c57a0ebff72a79d6e31a8f1`
- `VENDOR_civilworks_01_05.pdf`: `937266e6ef4b4fe3b6e7511476c7f90453957d7d8223ad8179f75788bf60a5f1`

## Verification

- Certified 19-row benchmark: **19/19 outcomes**, **100% precision**, **100%
  recall**, **100% F1**, **100% accuracy**, and **100% reason accuracy**.
- Full backend suite with PostgreSQL and Qdrant: **764 passed** in 510.28
  seconds.
- Final post-authentication/RBAC/propagation/dataset full suite: **776 passed**
  in 495.82 seconds.
- Focused Level 1 endpoint and database suite: **41 passed**.
- Combined focused regression suite: **103 passed**; earlier generation and
  matching slice: **153 passed, 5 skipped**.
- Frontend `npm run build`: passed, including TypeScript and Next lint checks.
- Part 2 focused workflow/API/export suite: **36 passed**.
- Security, propagation, router, API, and premium-corpus gate: **59 passed**.
- Labelled Level 3 router evaluation: **12/12 (100%)**.
- Live authentication: vendor registration **201**; reviewer registration
  without invitation **403**; reviewer registration with invitation **201**.
- Docker Compose base and `app` profiles validate; production frontend standalone
  build passes; PostgreSQL/Qdrant backup script is included.
- Live Level 1 run: **5 submissions, 2 eliminated, 3 cleared**, with exact
  reasons and source references persisted.
- Browser QA: command palette, light/dark themes, reviewer register, filters,
  evidence links, and the shared processing state render correctly.
- `git diff --check`: passed.
- PDF text-layer check: both regenerated pass fixtures contain `TENDER ANNEXURE
  V — SELF-CERTIFICATION/UNDERTAKING`.

## External account action

The previously exposed provider key still needs to be confirmed revoked/rotated
by the account owner. Repository and application verification cannot prove that
external account action.
