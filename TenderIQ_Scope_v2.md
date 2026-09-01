# TenderIQ — Tender Intelligence Platform
### Major Project Scope & Build Specification (v2)

---

## 1. Problem Statement

Tender processes in India (government e-procurement and corporate RFPs) suffer from two mirrored problems:

- **Vendors** applying for tenders often submit non-compliant bids — missing a mandatory certificate, an undersigned annexure, a wrong turnover format — and get rejected on technical grounds without ever reaching evaluation. There's no quick way to self-check a submission against the tender notification before filing.
- **Companies/authorities** issuing tenders receive dozens to hundreds of vendor submissions and spend 3–4 months manually reading each one to eliminate non-compliant vendors and shortlist the rest. This is slow, inconsistent (different reviewers apply criteria differently), and hard to audit later ("why was Vendor X rejected?").

TenderIQ addresses both sides of the same document-heavy, criteria-matching problem using a shared extraction + RAG + agent architecture.

---

## 2. Solution Overview

Two user-facing parts, **one shared backend architecture**:

| | Part 1 — Vendor Tool | Part 2 — Company Tool |
|---|---|---|
| User | A vendor preparing/reviewing their bid | A company/authority reviewing 100s of bids |
| Core job | "Is my submission compliant? What am I missing?" | "Eliminate non-compliant vendors, shortlist the rest, let me query across them" |
| Core tech | RAG cross-verification (2 documents) | Structured extraction + hybrid RAG + agent over N documents |

Both parts extract tender data into the **same structured schema** (Section 6), because a vendor's compliance checklist and a company's eligibility criteria are literally the same clauses read from two directions. This shared schema is the architectural backbone of the whole project — build it first.

---

## 2.1 NLP Focus & Why RAG Is Central (Not Sidelined)

**This is the single most important section to get right in your report and viva.** Reviewers will default to reading this as "an agent/pipeline-engineering project with some LLM calls" unless you explicitly walk them through where the NLP research effort actually goes. Use this section as your script.

### 2.1.1 The core claim, stated once, clearly

> *"Extraction and retrieval are the NLP core of this system. The rule engine and query router are lightweight logic layers that consume NLP outputs — they don't compete with the NLP work, they depend on it. The system's accuracy lives or dies on extraction quality and retrieval grounding, and that is where the measurable, evaluatable research effort goes."*

Memorize this sentence. It is your answer to "isn't this just an app with an LLM in it?"

### 2.1.2 Mapping features → NLP subfields (use this table directly in your report)

| System feature | NLP subfield it maps to | Why it's non-trivial |
|---|---|---|
| Schema-guided extraction from tender notifications & bids | Information Extraction (IE) — closely related to Named Entity Recognition + slot/relation extraction | Real-world messy input: mixed formatting, OCR'd scans, inconsistent numeric notation. Same extraction problem as Corpusil, applied to a harder legal-procurement domain. |
| Part 1 compliance Q&A | Retrieval-Augmented Generation | Dense embedding retrieval (BGE) over notification + submission, generation grounded in retrieved chunks, answers must cite source clause. |
| Part 2 Level 3 query agent | Hybrid RAG + query-intent classification | Deciding whether a query needs structured lookup, vector retrieval, or both is itself an intent-classification problem — a lightweight classifier or prompt-based router over query type. This is the project's most defensible "novel contribution" claim. |
| Elimination stage (deliberately NOT RAG) | Deterministic rule evaluation over extracted structured fields | This is a *design choice*, not a gap — see 2.1.3. |
| Number normalization ("₹5 Cr" vs "50,00,000") | Semantic/lexical normalization | Requires more than string matching — canonicalization logic, possibly embedding-assisted matching for units/phrasing variance. |
| Document-name matching ("GST Registration Certificate" vs "Goods & Services Tax Certificate") | Semantic similarity / synonym resolution | Exact string match produces false negatives; needs embedding similarity or an alias table. |
| Retrieval evaluation (Section 10) | IR/NLP evaluation methodology | Precision@k-style retrieval measurement, citation/grounding faithfulness checks — gives you a proper "results" chapter, not just a working demo. |

### 2.1.3 Pre-empting the obvious question: "Why isn't elimination done with RAG/LLM judgment?"

Address this head-on in your report rather than waiting for a panel member to ask it:

- Extraction (turning free text into structured fields) **is** the NLP task, and it's where errors can actually occur and be measured.
- Once a field is extracted (e.g., turnover = ₹4.2 Cr), comparing it against a threshold (≥ ₹5 Cr) is a deterministic, auditable rule check — not a judgment call, and definitely not something you want an LLM guessing at when a vendor's disqualification is legally consequential.
- Using extracted structured data for downstream rule-matching is standard practice in real IE pipelines (e.g., clinical NLP, financial compliance) — it doesn't dilute your NLP contribution, it's evidence you understand *when* to stop using a language model and start using logic.
- RAG's job stays exactly where RAG is actually good: the qualitative, free-text material — methodology sections, past-performance narratives, cross-document Q&A, "why was this vendor eliminated" audit lookups paired with cited clauses.

### 2.1.4 Retrieval evaluation is a first-class deliverable, not an afterthought

Don't let RAG quietly become "we called an embedding API and it worked." Section 10 gives you concrete metrics — retrieval precision@k, citation faithfulness, router accuracy — that turn RAG into a chapter with numbers, not a feature bullet. Build the labeled query set (Section 9) specifically so you can report these numbers.

### 2.1.5 One-slide summary (for your viva deck)

```
NLP CORE                          LOGIC LAYER (consumes NLP output)
─────────────────────             ──────────────────────────────────
Structured extraction (IE)   →    Elimination rule engine (deterministic)
Dense retrieval (RAG)        →    Query router (structured/vector/hybrid)
Semantic normalization        →    Compliance diffing (Part 1 gap report)
Query-intent classification   →    Shortlist summarization (grounded, non-ranked)
```

---

## 3. Users & Personas

1. **Vendor / bidder** (small-to-mid contractor, IT vendor, supplier) — not necessarily tech-savvy, wants a fast yes/no + gap list, not a dashboard.
2. **Procurement officer / evaluation committee member** — needs defensible, auditable, traceable decisions (not a black box), works across many tenders at once.
3. **(Optional stretch) Auditor / senior reviewer** — wants to verify why a vendor was eliminated or why the shortlist looks the way it does, after the fact.

---

## 4. Part 1 — Vendor-Side Compliance & RAG Assistant

### 4.1 Feature: Tender Notification Ingestion
Upload the official tender notification (PDF/DOCX). System extracts into the shared schema: eligibility criteria, mandatory documents list, technical requirements, submission format rules, deadlines, evaluation criteria (if stated).
**Why it matters:** this is the single source of truth every downstream check is measured against.

### 4.2 Feature: Vendor Submission Ingestion
Upload the vendor's draft bid (possibly multiple files — technical proposal, financial bid, annexures, certificates).
Extracted into the same schema fields, so each field can be directly diffed against the notification's requirement.

### 4.3 Feature: Compliance Cross-Check ("Gap Report")
For every mandatory clause in the notification, show: **Required → Found in submission? → Match/Partial/Missing**, with the exact source clause cited.
- Hard document checklist (e.g. GST certificate, EMD proof, experience certificates) → simple presence/absence check.
- Numeric eligibility (turnover ≥ X, experience ≥ Y years) → extracted number vs threshold, pass/fail.
- Format/procedural rules (page limits, signing/stamping, annexure order) → flagged as "needs manual check" since these are often visual, not textual.
**Why it matters:** this is the single most useful feature for a vendor — catches disqualifying mistakes before submission, when it's still fixable.

### 4.4 Feature: Evaluation Metrics Preview (conditional)
If — and only if — the tender notification states scoring weightage (e.g. QCBS: 70% technical / 30% financial, or point-based technical scoring), show the vendor an estimated self-score against stated criteria, clause by clause.
**Important honesty constraint:** if the notification does not publish scoring weightage, do NOT invent a score. Show compliance status only. State this limitation explicitly in the UI — this is a credibility feature for your project demo, showing you understand the difference between "grounded" and "hallucinated" scoring.

### 4.5 Feature: RAG Query Assistant
Free-text Q&A over both documents together: "What's the EMD amount?", "Is a partnership firm eligible?", "What's the last date for pre-bid queries?"
Every answer must cite the source clause (document + page/section).
**Why it matters:** demonstrates a proper RAG system (retrieval + citation grounding), not just a checklist — this is your core NLP/IR component for evaluation purposes.

### 4.6 Feature: Missing-Item Action List
A prioritized, plain-language to-do list generated from the gap report: "Upload GST certificate", "Turnover proof shows ₹3.2Cr, requirement is ₹5Cr — you do not currently qualify", etc.
**Why it matters:** converts a technical gap report into something a non-technical vendor can act on directly — good UX story for your demo.

---

## 5. Part 2 — Company-Side Evaluation Agent System

### 5.1 Feature: Bulk Tender Ingestion
Upload N vendor submissions (PDF/DOCX, possibly zipped) against one tender notification. Each is parsed into the shared schema and stored with `vendor_id`, `status`, and full field set.
**Why it matters:** this is what makes "100s of tenders in 3-4 months" tractable — batch extraction instead of manual reading.

### 5.2 Feature: Level 1 — Automated Elimination
Every vendor is checked against the notification's **mandatory eligibility criteria** (hard filters, not judgment calls): turnover thresholds, required certifications, minimum years of experience, mandatory document presence, disqualifying conditions (blacklist status, incomplete forms).
- Output per vendor: `status: eliminated | pending` — vendors that pass elimination move to `pending` (awaiting the Level 2 shortlist decision; matches the `status` enum in Section 6, which does not have a separate "passed" state), plus `elimination_reason` citing the exact failed clause and the extracted value that failed it (e.g. "Turnover ₹2.1Cr < required ₹5Cr, per clause 4.2").
- **No LLM judgment calls at this stage** — pure rule evaluation over extracted structured fields. This keeps elimination deterministic, explainable, and defensible if challenged.
**Why it matters:** this is your strongest, lowest-risk automation — and the most demo-friendly, because you can show a clean before/after (100 vendors → 32 eliminated, each with a stated reason).

### 5.3 Feature: Level 2 — Qualified Shortlist (non-ranked)
Among vendors who passed elimination, the user picks how many they want to shortlist (e.g. top 10/15/20) and which factors matter most (experience, past project scale, technical approach quality, pricing competitiveness — user-weighted).
System returns a **qualified pool**, presented as "these are strong candidates" — explicitly **not a forced numeric ranking**. Each shortlisted vendor comes with a short grounded summary of why they stand out (extracted facts, not invented scores).
**Why "no ranking" is a deliberate design choice, not a limitation:** tender scoring is often legally sensitive; claiming an authoritative rank (#1, #2, #3) implies a level of certainty an LLM-assisted tool shouldn't claim. Presenting a qualified shortlist that a human still makes the final call on is both more honest and more realistic for actual procurement use — say this explicitly in your project report/viva, it's a strength, not a gap.
**Why it matters:** solves the actual bottleneck (100 → unmanageable) → (15-20 → reviewable by a human committee in a normal meeting).

### 5.4 Feature: Level 3 — Cross-Vendor Query Agent
Conversational interface over the full vendor pool, across every status — `eliminated`, `pending`, and `shortlisted` (see Section 5.5) — with tool-routed queries:
- **Structured lookup** ("Which vendors have turnover above ₹5Cr?") → routed to structured-data query, not vector search.
- **Comparative** ("Compare top 3 shortlisted vendors on experience and past project value") → structured aggregation across multiple vendor rows.
- **Qualitative** ("Which vendor's technical approach best addresses the scalability requirement?") → routed to vector RAG over free-text sections (methodology, past performance narratives).
- **Audit** ("Why was Vendor X eliminated?") → structured lookup + cited clause.
**Why it matters:** this is the "proper agent" component of the project — the interesting technical contribution is the **router** that decides whether a query needs SQL-style structured lookup, vector retrieval, or both, and merges the results. This is worth calling out explicitly as your novel contribution in a project report.
**Fluency bias guard:** qualitative summaries must be grounded in *what a vendor claims to have done* (extracted facts/claims), not rewarded for polished writing. A vendor with plain but complete prose should not be summarized as "weaker" than one with fluent but vague prose. Worth a one-line disclaimer in the UI and a line in your report — this is a known LLM-evaluator failure mode and flagging it shows awareness.
**Human-in-the-loop framing:** the agent assists and summarizes — it does not decide. State this explicitly in the UI (e.g. a persistent note: "Final selection remains with the evaluation committee") and in your report. This matters both for tool credibility and because it's the realistic and defensible way such a system would actually be deployed.

### 5.5 Feature: Unified Audit Trail
Every vendor — eliminated or shortlisted — stays queryable in the same structured store + vector index (tagged by `status`), so any decision can be explained after the fact.
**Why it matters:** solves a real procurement pain point (disputes over "why wasn't my company even considered") and is a strong differentiator for a major project — few student projects think about auditability, and it's exactly the kind of design choice that impresses evaluators.

### 5.6 Feature: Corrigendum / Amendment Handling
Real tenders get amended after the original notification — deadline extensions, changed eligibility criteria, clarifications. Support uploading a corrigendum, re-extracting into the schema, and **diffing** it against the original notification's fields, with changes flagged and propagated to any already-extracted vendor evaluations.
**Why it matters:** without this, the system silently evaluates against a stale version of the tender — a real correctness bug, not a nice-to-have, and a good "we thought about the messy real-world case" talking point.

### 5.7 Feature: Access Control (Role Separation)
Two roles minimum: **vendor** (Part 1 — sees only their own submission and the public notification) and **company reviewer** (Part 2 — sees all vendor data). Vendors must never see other vendors' bids, elimination reasons, or shortlist status.
**Why it matters:** this isn't a nice-to-have for a procurement tool — confidentiality between competing bidders is a hard requirement in real tendering. Even a minimal auth layer (role flag + route guarding) is enough for a student project demo, but it must exist and be stated in the report.

### 5.8 Feature: Blacklist / Debarment Flag
Add an `is_blacklisted` field to the vendor schema. In a real deployment this would check an official debarment list; since you won't have live access to one, stub it as a manually-set flag (e.g. entered by the reviewer, or seeded in your synthetic test data) and wire it into the elimination rule engine as a hard-fail condition.
**Why it matters:** shows you understood a real disqualifying criterion in government tendering even though you can't fully automate it — flag the limitation honestly rather than omitting it.

### 5.9 Feature: Exportable Committee Report
One-click export of the shortlist + elimination summary + audit trail as a formatted PDF/DOCX, meant to be carried into an actual committee meeting (not just viewed in-app).
**Why it matters:** small to build (reuses your existing docx/pdf generation experience), but it's the difference between a chat demo and a tool that produces something a reviewer would actually walk into a meeting with — strong demo payoff for relatively little effort.

---

## 6. Shared Extraction Schema (build this first)

This schema is populated once per document (tender notification or vendor submission) and is the backbone of both parts.

```
Tender Notification Schema:
- tender_id, title, issuing_authority, sector
- submission_deadline, pre_bid_query_deadline
- eligibility_criteria: [ { criterion, type: numeric/boolean/document, threshold, clause_ref } ]
- mandatory_documents: [ { doc_name, clause_ref } ]
- evaluation_criteria: [ { factor, weightage_if_stated, clause_ref } ]  // null if not published
- technical_requirements: [ { requirement, clause_ref } ]
- submission_format_rules: [ { rule, clause_ref } ]
- emd_amount, contract_value_estimate

Vendor Submission Schema:
- vendor_id, vendor_name
- turnover: [ { year, amount } ]
- years_in_business
- certifications: [ { name, valid_till, doc_present: bool } ]
- past_projects: [ { client, value, year, description } ]
- documents_submitted: [ { doc_name, present: bool } ]
- technical_approach_text (free text → vector store)
- pricing_summary
- is_blacklisted: bool (manually set / seeded — see Section 5.8)
- status: eliminated | shortlisted | pending
- elimination_reason: nullable, cites clause_ref

Notification Amendment (Corrigendum) Schema:
- corrigendum_id, parent_tender_id, issued_date
- changed_fields: [ { field_path, old_value, new_value, clause_ref } ]
```

Store structured fields in a relational table (SQL). Store free-text narrative fields (technical approach, past performance descriptions, methodology) in a vector store, chunked and tagged with `vendor_id` + `status` metadata for scoped retrieval.

**Number normalization note:** Indian tender documents express amounts inconsistently — "₹5 Cr", "50,00,000", "5,00,00,000" may all appear for the same figure across documents. Every numeric field in the schema must pass through a normalization step (canonical absolute-rupee value) at extraction time, or downstream elimination rules will silently misfire. Treat this as a required extraction sub-task, not an edge case.

**Document-name matching note:** the same required document is often named differently across notification and submission ("GST Registration Certificate" vs "Goods & Services Tax Certificate"). Exact string matching on `doc_name` will produce false negatives — use embedding similarity or a small synonym/alias table for the presence check in Section 4.3 / 5.2.

---

## 7. System Architecture

```
                     ┌─────────────────────────┐
                     │   Document Upload (UI)   │
                     └────────────┬─────────────┘
                                  │
                     ┌────────────▼─────────────┐
                     │   OCR (if scanned) +      │
                     │   Extraction Agent(s)     │   ← LangGraph multi-agent
                     │   (LLM + schema-guided     │      extraction, same as
                     │    structured extraction)  │      Corpusil's pattern
                     └────────────┬─────────────┘
                                  │
                  ┌───────────────┴───────────────┐
                  ▼                                ▼
      ┌────────────────────┐          ┌────────────────────────┐
      │  Structured Store   │          │   Vector Store          │
      │  (PostgreSQL)       │          │   (Qdrant)               │
      │  - hard fields       │          │  - free-text sections    │
      │  - status, elim.reason│         │  - tagged vendor_id/status│
      └──────────┬──────────┘          └────────────┬────────────┘
                 │                                    │
                 └───────────────┬────────────────────┘
                                  ▼
                     ┌─────────────────────────┐
                     │      Agent Router         │
                     │  (structured lookup /     │
                     │   vector RAG / hybrid)     │
                     └────────────┬─────────────┘
                                  │
                     ┌────────────▼─────────────┐
                     │   Part 1: Compliance UI   │
                     │   Part 2: Elimination +   │
                     │   Shortlist + Chat UI     │
                     └───────────────────────────┘
```

---

## 8. Recommended Tech Stack

Reusing your existing, proven stack from Corpusil keeps this build fast and lets you focus effort on the new logic (elimination rules, agent router, schema) instead of re-learning tooling.

- **Frontend:** Next.js 14 (App Router), Tailwind
- **Backend:** FastAPI
- **Orchestration / agents:** LangGraph (multi-agent extraction pipeline + query router)
- **Structured store:** PostgreSQL
- **Vector store:** Qdrant
- **Embeddings:** BGE — already free and runs locally (via `sentence-transformers`/HuggingFace), no API dependency either way; no change needed here regardless of which LLM option below you pick.
- **OCR:** Tesseract — free/offline, no change needed here either.
- **LLM (extraction + agent reasoning):** no paid API — choose between, or combine, the two options below.

### 8.1 LLM decision: Gemini free tier (primary), Ollama (fallback)

**Go with Google Gemini (2.5 Flash) free tier as the primary LLM for extraction, RAG generation, and agent reasoning.**

Why this over local/offline as the default:
- Extraction/retrieval accuracy is the core deliverable this project is evaluated on (Section 10) — Gemini Flash is materially more reliable at clean structured JSON output than a 7B–8B open-weight model, and that reliability is exactly what your evaluation numbers measure.
- No GPU dependency. Most student setups can't run a 7B–14B model at usable speed on CPU, which would slow down every iteration of the extraction pipeline during development, not just the final demo.
- The free tier's quota is generous enough for a project this size (hundreds of documents, not millions) — cost isn't the binding constraint here, dev speed and reliability are.

**Keep Ollama (Qwen2.5 7B/14B-Instruct) as a fallback, not the default:**
- Use it if you hit free-tier rate limits during a heavy testing push, or need an offline demo with no internet at the venue.
- Because the LLM call is abstracted behind one interface (below), switching to it is a config change, not a rewrite.
- Optional bonus: if time allows, run one comparison pass with Ollama and report the accuracy delta vs. Gemini in Section 10 — a legitimate extra finding, not required for core scope.

Either way, use **schema-constrained decoding** (Gemini's structured-output/JSON mode, or `outlines`/`guidance` for the Ollama path) so the model can't return malformed output — this matters more for whichever model you pick less reliable, i.e. Ollama if you fall back to it.

**Recommendation:** abstract the LLM call behind a single interface so you can swap Gemini ↔ Ollama via config rather than code changes.

---

## 9. Data Sources, Collection & Synthetic Generation — Team Playbook

This is the section every reviewer probes hardest, and the one most likely to stall if it isn't broken into concrete, assignable tasks. Below is a step-by-step plan written so any teammate can pick up a task without needing the full project context first.

### 9.1 Real tender notifications (collect manually — do not scrape)

**Sources:**
- **GeM (Government e-Marketplace)** — bid documents are public and downloadable.
- **CPPP / eProcurement portals** — the Central Public Procurement Portal, plus state-level portals like Telangana eProcurement (eprocure.gov.in and state variants) — tender notices, corrigenda, and eligibility criteria documents are publicly downloadable as PDFs.

**Why manual, not scraped:** most of these portals restrict automated/bot access in their terms of service, and the project only needs a small curated set — a scraper is unnecessary risk for no real benefit.

**Task (1 person, ~1 day):**
1. Pick 2–3 sectors to keep format variance manageable: e.g. **IT services**, **civil works**, **supply/procurement contracts**.
2. Download **5–10 real notifications** total, spread across those sectors (aim for at least 2 per sector).
3. For each, also try to find a **published corrigendum/amendment** on the same portal, if one exists — you'll need at least 1–2 real corrigenda to test Section 5.6. If none exist for your chosen notifications, note this and plan to synthesize a corrigendum instead (see 9.2.4).
4. Save every file with a consistent naming convention: `NOTIF_<sector>_<serial>.pdf`, e.g. `NOTIF_ITservices_01.pdf`.
5. Log each one in a shared tracking sheet (template in 9.4) with: source portal, sector, download date, whether scanned/OCR'd or native text, whether a corrigendum was found.

### 9.2 Synthetic vendor submissions (the harder problem, needs the most care)

Real vendor bids are **not public** — they're confidential, submitted directly to the authority. So the vendor-submission side of your test set has to be generated, but generated in a way that still gives you a trustworthy ground truth.

#### 9.2.1 Why synthetic-with-known-ground-truth, and not just "AI-generated data"
The point isn't just to have documents to feed the pipeline — it's that **you decide the compliance outcome before generation**, so afterward you can check whether your extraction + elimination pipeline reached the same conclusion. That comparison *is* your evaluation chapter (Section 10). Generating vendor docs without first fixing the intended outcome gives you files but no answer key.

#### 9.2.2 Step-by-step generation process (assign per notification, so this parallelizes across teammates)

For **each** real notification collected in 9.1:

1. **Read the notification and extract its actual thresholds** (turnover minimum, required certs, experience years, mandatory documents, deadline). You need these numbers to write a real answer key, not vague labels.
2. **Design a compliance mix before generating anything.** For **15–20 synthetic vendors per notification**, plan the distribution up front, e.g.:
   - 5–6 fully compliant (should pass elimination)
   - 3–4 missing exactly one mandatory document (should be eliminated on that specific clause)
   - 3–4 below the turnover/experience threshold (should be eliminated on that specific clause)
   - 2–3 borderline (e.g. turnover exactly at threshold, or a document present but expired — good for stress-testing edge cases)
   - 1–2 with strong technical write-ups vs 1–2 with weak/vague ones (for testing the Level 3 qualitative agent and the fluency-bias guard in 5.4)
   - Optionally 1 flagged `is_blacklisted` (to test 5.8)
3. **Write ground truth first, generation prompt second.** Before generating vendor N's documents, write down in the tracking sheet: `vendor_id, intended_status (pass/eliminate), intended_reason (which clause, if eliminated), notes`. Only then generate the document to match that intent.
4. **Generate the vendor documents via the Claude API**, one prompt per vendor (or per vendor-document if the bid has multiple files — technical proposal, financial bid, certificates). Prompt Claude with: the relevant notification excerpt, the intended compliance outcome for this vendor, and instructions to write realistic tender-bid prose (not a bare data dump) so extraction is actually tested against real document style, not clean lists.
5. **Render the generated text into PDF/DOCX**, not plain text files — this matters because your extraction pipeline needs to be tested on the same file types real tenders arrive in (with page breaks, headers, tables), not clean JSON or .txt. Reuse the project's existing docx/pdf generation code for this step.
6. **File naming convention:** `VENDOR_<notification_id>_<vendor_serial>.pdf` (or `.docx`), matching the tracking sheet's `vendor_id`.

#### 9.2.3 Supplementing with sample/template RFP responses (optional, adds realism)
Publicly available vendor-proposal templates and sample technical bids (common on consulting/procurement training and government-training sites) can be mixed in to give the vector store more realistic, varied prose style for testing the qualitative RAG path — these don't need a "correct" pass/fail label, they're for retrieval-quality testing, not elimination-accuracy testing. Keep them in a clearly separate folder so they never get mixed into the labeled evaluation set by mistake.

#### 9.2.4 Synthetic corrigenda (if a real one wasn't found in 9.1)
For 1–2 notifications, generate a synthetic corrigendum via the same Claude-API approach: pick 2–3 fields to change (e.g. extend the deadline by 2 weeks, adjust a turnover threshold), write down the intended `changed_fields` diff first, then generate the corrigendum document to match it. This gives you a ground-truth diff to test Section 5.6 against.

### 9.3 Building the labeled query set (for Section 10's retrieval/router metrics)

This is a separate, smaller task — assign it to whoever is building the Level 3 agent, once at least a few vendor sets exist to query against.

Build a spreadsheet of **50 queries total**, labeled by intended route:
- **20 structured** (e.g. "Which vendors have turnover above ₹5Cr?") — label the expected answer as a direct field lookup, no vector search involved.
- **20 qualitative** (e.g. "Which vendor's technical approach best addresses the scalability requirement?") — label the expected source chunk(s) that should be retrieved.
- **10 hybrid** (e.g. "Compare the top 3 shortlisted vendors on experience and summarize their technical strengths") — label both the structured fields and the qualitative chunks expected.

For every query, also record the **expected correct answer** (or expected cited clause/chunk) — this is what lets you compute retrieval precision and citation faithfulness in Section 10, not just "did it respond."

### 9.4 Shared tracking sheet — template (one spreadsheet, shared across the team)

Two tabs, so everyone works off the same source of truth:

**Tab 1 — Notifications**
`notification_id | sector | portal_source | file_name | has_real_corrigendum | scanned_or_native | collected_by | date`

**Tab 2 — Vendors (the answer key)**
`vendor_id | notification_id | intended_status | intended_reason | intended_failed_clause | is_blacklisted | technical_writeup_quality (strong/weak) | file_name | generated_by | date`

This second tab **is** your ground truth for Section 10's elimination precision/recall metric — every number in your results chapter traces back to this sheet, so keep it accurate and don't let entries drift out of sync with the actual generated files.

### 9.5 Suggested division of labor (adjust to team size)

| Task | Who | Depends on |
|---|---|---|
| Collect real notifications (9.1) | 1 person | nothing — do first |
| Design compliance mix + write ground truth per notification (9.2.2 steps 1–3) | 1–2 people, per notification | 9.1 done for that notification |
| Generate vendor docs via API + render to PDF/DOCX (9.2.2 steps 4–5) | 1–2 people | ground truth written first (not the other way round) |
| Synthetic corrigenda (9.2.4) | 1 person | 9.1 (know which notifications lack a real one) |
| Labeled query set (9.3) | whoever builds the Level 3 agent | a few complete vendor sets exist to query |
| Maintain tracking sheet (9.4) | 1 owner, everyone contributes | ongoing |

### 9.6 Why this two-pronged approach is a strength, not a workaround
State this explicitly in your report: *"real notifications + a synthetic-but-controlled vendor pool with known ground truth"* shows you understood that live confidential procurement data isn't accessible for a student project, and designed a rigorous evaluation methodology anyway — that's a maturity signal, not a limitation to apologize for.

---

## 10. Evaluation Metrics (for measuring your own system, not the vendors)

- **Extraction accuracy:** % of schema fields correctly extracted vs manually-labeled ground truth (on your synthetic set, since you control the true values).
- **Elimination precision/recall:** does the rule engine correctly eliminate every synthetic vendor you deliberately made non-compliant, and correctly pass every compliant one? (Computed directly against Tab 2 of the tracking sheet, Section 9.4.)
- **Retrieval precision (RAG):** for the Q&A/query agent, does the top-retrieved chunk actually contain the answer (measure on the hand-built query set from 9.3)?
- **Citation faithfulness:** does every generated answer's citation actually support the claim (manual spot-check + optionally an LLM-as-judge pass)?
- **Router accuracy:** for the agent, % of queries correctly routed to structured lookup vs vector RAG vs hybrid (using the 20/20/10 labeled query set from 9.3).
- **Latency:** end-to-end time per vendor extraction, and per query response — relevant given the "3-4 months → same day" pitch.

---

## 11. Why This Is a Strong Major Project

- **Real, well-articulated problem** with a quantifiable pain point (3–4 months → automatable in hours), not a toy use case.
- **Non-trivial technical core:** schema-guided structured extraction + hybrid structured/vector retrieval + agentic query routing — not "just RAG," and not "just a form."
- **Deliberate, defensible design choices** (no forced ranking, no invented scores without stated weightage, deterministic rule-based elimination, full audit trail) — shows engineering maturity, not just capability.
- **Two-sided system** from one shared architecture — demonstrates you can generalize a data model across different user needs instead of building two disconnected tools.
- **Rigorous evaluation methodology** despite no access to real confidential vendor data — a designed synthetic-but-grounded test set with measurable precision/recall.
- **Directly reuses and extends your own prior work** (Corpusil's multi-agent extraction pattern) into a new domain — good narrative for a viva: "I identified a reusable architecture and applied it to a second, harder problem."

---

## 12. Build Roadmap (phase this for Claude Code)

**Phase 0 — Foundation**
- Define and finalize the shared extraction schema (Section 6) in code (Pydantic models).
- Set up PostgreSQL schema + Qdrant collection with metadata tagging.

**Phase 1 — Extraction pipeline**
- OCR + document parsing (PDF/DOCX ingestion).
- LangGraph extraction agent(s): notification extraction, vendor submission extraction — both targeting the shared schema.
- Test against 5-10 real tender notifications first (format robustness).

**Phase 2 — Part 1 (vendor tool)**
- Gap-report cross-check logic (rule-based diff between two schema instances).
- RAG Q&A over the two documents with citation.
- Frontend: upload flow + gap report UI + chat.

**Phase 3 — Part 2, Level 1 (elimination)**
- Rule engine over structured fields → eliminate/pass + reasons.
- Bulk upload UI, results table with filters.

**Phase 4 — Part 2, Level 2 (shortlist)**
- User-weighted factor selection UI.
- Qualified-pool summarization logic (grounded, non-ranked).

**Phase 5 — Part 2, Level 3 (agent)**
- Query router (structured/vector/hybrid classification).
- Structured query tool + vector RAG tool + merge/summarize logic.
- Chat UI over the vendor pool, with audit queries supported.

**Phase 6 — Synthetic data + evaluation**
- Execute the Section 9 data playbook (real notifications, synthetic vendor generation, tracking sheet, labeled query set).
- Run and document metrics from Section 10.

**Phase 7 — Polish**
- UI pass, demo script, report writeup with architecture diagrams and evaluation results.

### 12.1 Suggested Timeline

Rough sequencing, assuming a small team working in parallel where noted — adjust to your actual team size and deadline, but use this as a starting skeleton rather than estimating from zero:

| Phase | Suggested duration | Can run in parallel with |
|---|---|---|
| 0 — Foundation (schema, DB, vector store setup) | 3–4 days | Start of 9.1 (notification collection) |
| 1 — Extraction pipeline | 1–1.5 weeks | 9.1 continues; start 9.2 ground-truth design once a few notifications are extractable |
| 2 — Part 1 (vendor tool) | 1 week | Phase 3 can start once Phase 0/1 are stable |
| 3 — Part 2 Level 1 (elimination) | 1 week | 9.2 synthetic vendor generation |
| 4 — Part 2 Level 2 (shortlist) | 3–4 days | — |
| 5 — Part 2 Level 3 (agent + router) | 1–1.5 weeks | 9.3 labeled query set, built alongside once vendor sets exist |
| 6 — Synthetic data + evaluation | ongoing from ~Phase 1 onward, formal metrics run at the end | overlaps almost everything — this is why Section 9's task breakdown exists, so it isn't a bottleneck at the end |
| 7 — Polish (UI, demo, report) | 1–1.5 weeks | — |

**Total: roughly 7–9 weeks** for a team of 3–5 splitting Section 9's data tasks in parallel with the build phases. If your data collection (9.1–9.2) starts on day one alongside Phase 0, it should never be the critical-path bottleneck — that's the main risk to watch for, not effort.

---

## 13. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Tender document formats vary wildly (scanned, tables, multi-column) | Start with a narrow format set (pick 2-3 real portals), invest in OCR + layout-aware parsing early, don't aim for universal format support in v1 |
| No real vendor data to validate against | Synthetic-but-controlled generation with known ground truth (Section 9.2) — be explicit about this limitation in your report, don't hide it |
| Elimination rules could be gamed by LLM misreading a number | Keep elimination deterministic (extract number → rule-check in code, not LLM judgment at decision time) |
| Agent could hallucinate comparisons | Every comparative/numeric answer must trace to a structured field; qualitative answers must cite retrieved chunk source |
| Ground truth drifts out of sync with generated files (Section 9) | One shared tracking sheet, one owner, write intended outcome *before* generating each document, never after |
| Claude API cost/rate limits during bulk synthetic generation + repeated extraction test runs (Section 9 needs 100+ generated documents, plus every extraction re-test hits the API again) | Set a rough token/request budget before Phase 6 starts; generate vendor docs in batches and cache results so re-running the extraction pipeline doesn't regenerate source documents; use a cheaper/faster model for bulk generation and reserve the stronger model for extraction/agent reasoning (already the plan in Section 8) |
| Offline/free-tier LLMs (Section 8.1) extract less reliably than a frontier closed model, especially on messy real-world formatting | Use schema-constrained decoding (JSON/grammar mode, or `outlines`/`guidance`) so the model can't return malformed output; measure this directly as an extraction-accuracy metric (Section 10) rather than assuming it away — report it honestly if smaller models underperform on certain field types |
| Scope creep (you know this tendency) | Lock Phases 0-5 as the actual major-project scope; treat anything beyond as stretch, not core deliverable |

---

## 14. Stretch Features (only if core is done early)

- Multi-tender dashboard (track several open tenders at once).
- Vendor-facing portal showing their own compliance status directly (if company opts to share).
- Basic anomaly flagging (e.g. suspiciously similar submissions from different vendors — plagiarism-style check across bids).

---

*This document is written as a build specification. Hand this directly to Claude Code as the starting context, then proceed phase by phase from Section 12 rather than requesting the full system at once.*
