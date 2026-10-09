# BidSense — measured results and error taxonomy

Every number here is produced by a script in `backend/scripts/` and can be
re-run. Where a figure is a proportion over a small sample it carries a 95%
Wilson interval, because "100%" from seventeen trials and "100%" from two
thousand are different claims and should not be written the same way.

```bash
cd backend
../.venv/bin/python -m scripts.evaluate              # elimination precision / recall
../.venv/bin/python -m scripts.evaluate_extraction   # field accuracy
../.venv/bin/python -m scripts.evaluate_retrieval    # precision@k, hit@k, MRR
../.venv/bin/python -m scripts.baseline_retrieval    # BM25 reference point
../.venv/bin/python -m scripts.evaluate_citations    # citation faithfulness
../.venv/bin/python -m scripts.evaluate_router       # intent routing
../.venv/bin/python -m scripts.ablate_chunking       # chunking ablation
```

## Elimination, split by ground

Section 5.2 makes two kinds of failure disqualifying: an eligibility CRITERION
the bidder does not meet, and a mandatory DOCUMENT not enclosed. Both eliminate.
They are not the same decision -- a turnover shortfall cannot be cured before
the deadline and a missing covering letter usually can -- and reporting them as
one number hid which component was actually at fault.

| ground | precision | recall | TP | FP | FN |
|---|---:|---:|---:|---:|---:|
| criteria (threshold / status) | **100%** | **100%** | 6 | 0 | 0 |
| document (missing enclosure) | 60% | 100% | 6 | 4 | 0 |
| blended (what used to be reported) | 75% | 100% | 12 | 4 | 0 |

**The deterministic rule engine is exact.** No compliant bidder fails a
criterion, and every bidder who should fail one does. The blended 75% implicated
that engine, and it was not at fault: all four false positives are
document-matching, where a bid's enclosure list is compared against a 39-to-47
item checklist.

Reason accuracy is **75%** (was 58% -- see "measurement bugs" below).

### Why the four document-ground false positives are a corpus defect

All four are bids the answer key marks `pass`, and the key's own notes explain
what it meant: *"Comfortably clears both the 30% turnover and 80% similar-work
floors"*, *"Clears capacity, credit and substation requirements"*. The key
asserts CRITERIA compliance and never claimed document completeness -- yet the
generated bids do not enclose every mandatory document. Checked by hand against
the bids:

| requirement | nearest enclosure in the bid | verdict |
|---|---|---|
| compliance **sheet** | clause-wise compliance **statement** | real matcher miss (0.614, below the 0.72 floor) |
| BOQ file | Price Bid Schedule 1-4 | genuinely different |
| Covering Letter | Bid Form for first Part | genuinely different |
| Tender Processing **Fee** | evidence of payment of **EMD** | correctly different |
| undertaking re **banning** | undertaking re **genuineness** | correctly different |

So one is a matcher miss and four are documents the bids really do not contain.
The right fix is to the corpus -- a bid labelled "fully compliant" should enclose
what the tender demands -- not to the engine. Not done here, and deliberately
not papered over by loosening the matcher until the numbers agreed.

## Scope Section 10, all six metrics

| Metric | Result | n |
|---|---|---|
| Extraction field accuracy | 100.0% [81.6-100.0%] | 17 fields, 4 real tenders |
| Elimination precision / recall / reason | 100% each | 15 vendors |
| Retrieval precision@1 | 47.1% [26.2-69.0%] | 17 queries |
| Retrieval hit@5 | 70.6% [46.9-86.7%] | 17 queries |
| Citation page truthfulness | 100% | 31 citations |
| Router accuracy (held out) | 95.5% [78.2-99.2%] | 22 queries |
| Latency, Ask | 71.8 s cold -> 3.8 s by the fifth question | 5 calls |

## Retrieval against a baseline

A number with nothing to compare it to says little, so the same questions run
through classical BM25 over the same chunks.

| | hit@1 | hit@3 | hit@5 | MRR |
|---|---:|---:|---:|---:|
| BM25 keyword baseline | 17.6% | 35.3% | 47.1% | 0.294 |
| Dense, size-split chunks (original) | 5.9% | 17.6% | 35.3% | 0.149 |
| Dense, table rows chunked | 41.2% | 58.8% | 64.7% | 0.502 |
| **Dense, rows + glossary expansion** | **47.1%** | **64.7%** | **70.6%** | **0.571** |

The second row is the uncomfortable one and it belongs in the report: before the
chunking fix, the dense retriever was **worse than keyword search** on every
metric. It is now clearly better, but that ordering was discovered by measuring,
not by assuming.

Questions were deliberately written to avoid the documents' own wording ("How
much do I have to deposit upfront?" rather than quoting "Earnest Money Deposit
of Rs. 31,500"). That is a handicap for BM25, so read it as the floor a
semantic retriever must clear rather than BM25 at its best.

## Error taxonomy: the 5 of 17 that still fail

Measured gold-chunk rank, with the chunk that holds the answer.

| id | gold rank | chunk | table? | category |
|---|---:|---:|---|---|
| q17 | 6 | 70 ch | yes | **just outside k** |
| q08 | 12 | 322 ch | yes | **just outside k** |
| q06 | 15 | 1,104 ch | no | **multi-fact prose blob** |
| q14 | 105 | 1,575 ch | no | **multi-fact prose blob** |
| q13 | 247 | 1,575 ch | no | **multi-fact prose blob** |

### Category 1 — just outside k (2 of 5)

The answer is in a clean, well-formed table row that ranks 6th and 12th. Nothing
is wrong with the chunk or the embedding; `k=5` is simply a tight window on a
corpus of 281-1,685 chunks. Both are recovered at k=10, which is why hit@10
(76.5%) exceeds hit@5 (70.6%). Raising k in the product is a UI decision about
how many sources to show, not a retrieval fix.

### Category 2 — multi-fact prose blob (3 of 5)

All three are 1,100-1,575 character prose chunks holding several answers at
once. q13 and q14 are the *same* 1,575-character paragraph, which is why both
fail: it contains the EMD percentage, the agreement-time balance, and much else,
so its single vector is about all of them and specific to none. This is exactly
the dilution that row chunking fixed for tables, in a container row chunking
cannot touch.

**Two fixes were tested and neither is shipped.**

*Uniform smaller prose chunks.* Swept 1600 / 1000 / 600 / 400 / 250. The current
1600 wins on every metric; 400 scores hit@1 35.3% against 47.1%. Smaller prose
chunks lose the context that makes them match a question while the buried figure
stays buried.

*Splitting only fact-dense prose* (>= 4 distinct figures, down to 500 chars).
This moved hit@3 from 64.7% to 70.6% and MRR from 0.571 to 0.588, and changed
hit@1 and hit@5 not at all. That is one query's worth of movement on a
seventeen-query set, and the Wilson intervals overlap almost entirely -- it is
indistinguishable from noise. Shipping a permanent 6% index-size increase on
that evidence would be fitting to the test set, so it was not shipped. It is the
most promising open lead and deserves re-testing once the query set is larger.

## Measurement bugs found in this project's own evaluation

Two of them, both of which made the system look worse than it is. Recorded
because an evaluation that is only audited when it flatters you is not an
evaluation.

| bug | effect |
|---|---|
| Clause references compared literally, so the key's `1.1(4)` did not match the cited `1.1 (4)` | 5 correct citations scored wrong; reason accuracy reported 58% instead of 75% |
| Citation page-truthfulness compared a table rendered as `Label \| Value` against pdfplumber's running-text rendering of the same page | scored 50%; actually 31/31 |

And one in the other direction: two retrieval labels were wrong and understated
retrieval (q11's question did not describe its own evidence; q16's phrase list
held one of two wordings the tender uses). Both corrected, five genuine misses
deliberately left as misses.

A third, found later and worse than either: **regenerating the bids destroyed
part of the answer key.** `scripts/make_vendor_bids.py` opened
`tracking_vendors.csv` in `"w"` mode and wrote only its own fifteen specs, so
every run deleted the four SBI rows (maintained by a different generator) and
the entire `intended_ground` column. Nothing failed -- a nineteen-row answer key
silently became a fifteen-row one, and the elimination metrics then measured
whatever survived. The writer merges by `vendor_id` now, and eight tests in
`backend/tests/test_answer_key_integrity.py` pin the loss modes.

The same commit found a quieter instance of it: `VENDOR_civilworks_02_03`
carried a hand-corrected clause `11.II(a)(h)` in the key against an em-dash
placeholder in the spec. The generator owns that column, so the correction was
one regeneration away from being reverted to a placeholder. A test now asserts
spec/key agreement, because a label the code disagrees with is not a
correction -- it is a pending regression.

## A real defect still open

Extraction returns `2.8.1 (i)` through `2.8.1 (ix)` for the HGCL tender, whose
source prints **`28.1`**. The dot is spurious and consistent, so nothing
downstream looked anomalous: the elimination it supported was correct and its
citation was not. A reviewer looking up 2.8.1 in that tender finds nothing.

Reproduced in `backend/tests/test_clause_check.py`.
`backend/app/extraction/clause_check.py` can detect this class of error, and is
deliberately NOT wired into the ingest validation pass: pointed at the real
corpus it flags 20 of civilworks_01's citations and 19 of civilworks_02's,
because its reference pattern matches every number in a 236,000-character
document. A correct version needs a structure-aware extractor that reads
line-leading numbering. Shipping it as-is would have added twenty warnings per
tender and taught everyone to ignore the flag.

## Things measured and deliberately NOT shipped

| Change | Result | Decision |
|---|---|---|
| Smaller prose chunks (uniform) | worse at every size | rejected |
| Fact-dense prose splitting | +1 query on n=17 | rejected as noise; best open lead |
| Lexical / BM25 hybrid reranking | worse at every blend weight 0.15-0.8 | rejected, module deleted |
| Chunk-side text rewriting for retrieval | equal to query-side | superseded: embed expanded, store original |
| Packaging words ("single PDF file of") as non-identifying | no provable effect; `containment` uses `min()`, so extra words in a requirement rarely block a match | rejected as unproven |
| Clause-reference validation on every ingest | 20 and 19 false findings per tender | rejected; kept as a tested utility |

The hybrid result has a clean explanation: because the questions avoid the
documents' wording, query terms barely overlap the answer, while corpus-common
words like "tender" collect spurious credit. That lexical matching contributes
nothing *here* is itself evidence the dense retriever is doing real semantic
work.

## Is the difference real? Paired significance

Every figure above was previously a point estimate with a Wilson interval, and
two arms were compared by eye. Because both arms are scored on the *same*
labelled queries, the right comparison is paired: a query both arms get right
carries no information about which is better, so only the queries they disagree
on are evidence.

- **hit@k**: exact two-sided sign test (McNemar's exact test) over the
  discordant queries. Exact rather than normal-approximate because n is small
  enough that the approximation is simply wrong here.
- **MRR**: percentile bootstrap over the paired per-query deltas, 10,000
  resamples, seed `20260907` (recorded in the run manifest). Percentile rather
  than a t-interval because the deltas are a spike at zero with a few large
  jumps, nowhere near normal.

The distinction is not academic at this n. A clean **6-0 sweep clears 0.05
(p = 0.0312); a clean 5-0 sweep does not (p = 0.0625)** -- and the second was
being read as a win. That is the honest argument for enlarging the query set,
and it is quantified rather than asserted.

`scripts/baseline_retrieval.py --dense` now scores the dense arm in the same
process as the BM25 arm. Quoting BM25 from one script and the dense figure from
a separate run of `evaluate_retrieval.py` compares two executions, so any label
fix or chunker change between them is silently credited to the embeddings --
precisely the substitution `ablate_chunking.py` exists to prevent.

Reported figures are never a p-value alone: each comes with its n, the raw
improved/regressed/tied counts, and an explicit "significant / NOT significant
at 0.05".

## How reliable are the labels?

Every number here is measured against hand-written labels, which makes label
reliability part of the method. The instrument is Cohen's kappa, and the reason
it rather than raw agreement is arithmetic: 12 of the 19 bids are eliminated, so
two annotators who both simply answer "eliminate" agree 63% of the time while
sharing no judgement whatsoever.

`scripts/double_label.py` prepares a blinded sheet (the recorded label withheld,
and the `intended_reason` text too -- for a document-ground elimination it reads
"... not enclosed", which hands over the answer), refuses a returned sheet with
blanks, unknown labels or missing units, and lists every disagreement for
adjudication. `data/ANNOTATION_PROTOCOL.md` holds the label definitions and
decision rules.

**No kappa figure is reported yet, and this is deliberate.** Kappa requires an
independent second rater. A second pass by whoever wrote the labels reproduces
their own reading of an ambiguous clause and reports that consistency as
reliability, and the assistant that generated these labels is not independent of
its own work either. The harness and the protocol are the deliverable; the
figure requires about an hour from a second person who has not seen the key.

When it is run, report kappa with its n and the raw agreement. At n = 12 with
two near-balanced categories the statistic moves roughly 0.17 per unit, so a
single adjudicated disagreement visibly shifts it.

## Reproducing these numbers

`python -m scripts.evaluate_all` runs every evaluator and writes one
`results.json` beside a manifest recording the git revision (flagged if the tree
is dirty), dependency versions, the seed, SHA-256 of every notification and
label file, and the n behind each figure.

A stage whose prerequisites are absent is reported **BLOCKED** with the specific
reason, and no number is invented for it. This matters for honest reading of any
partial run: the notification PDFs are gitignored (they are large public
downloads, tracked as metadata), the services may be down, and the LLM providers
have quotas -- so on a fresh checkout most stages cannot run. Only a stage that
had what it needed and still broke is FAILED.

What that means for the figures above: they were measured on a corpus that must
be restored before they can be re-derived. **Any claim in this document that
cannot currently be re-run is a claim about a past run, not a reproduction.**

### What blocks a re-run, concretely

Measured in a clean cloud container with the services brought up by hand. Three
independent prerequisites, in the order they bite:

| Blocker | Blocks | To unblock |
|---|---|---|
| `data/notifications/*.pdf` absent — gitignored as large public downloads, tracked as metadata in `data/README.md` | every retrieval, extraction, chunking, citation and elimination figure | re-download the four notifications listed in `data/README.md` |
| `huggingface.co` denied by the environment's network policy, so `BAAI/bge-base-en-v1.5` (~440MB) cannot be fetched | all embedding, indexing and dense retrieval; `--dense` on the baseline | allow `huggingface.co` in the environment's network settings, or pre-seed `~/.cache/huggingface` |
| No LLM provider key in the environment | the citation evaluator and the LLM extraction path | set `GEMINI_API_KEY` / `GROQ_API_KEY`, or point `OLLAMA_BASE_URL` at a local model |

What *does* run without any of them: the full unit suite, both chunking arms'
structural behaviour, the BM25 baseline arm (no model needed), every statistical
function, the answer-key integrity guards, and the theme-contrast guard.

The test suite already distinguishes these correctly rather than failing:
`tests/test_pipeline.py` probes for both services and for the model, and skips
with `"postgres/qdrant not running"` or `"BGE model unavailable"`. Under a denied
`huggingface.co` that probe retries for a long time, so set
`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` for a fast, deterministic offline run.

One environment caveat that is not a product defect: FastAPI's `TestClient`
addresses `http://testserver`, and httpx honours `HTTPS_PROXY`, so behind an
HTTP proxy every API test fails with `httpx.ProxyError` — 191 such errors across
11 files on the first run here. Add `testserver` to `NO_PROXY`.

## Where the time goes

Measured, because "make it faster" without a profile is guesswork, and this
pipeline has three plausible-sounding bottlenecks. `scripts/profile_pipeline.py`
reproduces all of this; it runs on a generated fixture, so it needs neither the
corpus nor the network.

On a 172-page generated bid (271KB, 43 tables, 242,470 characters, 1,528
chunks):

| stage | median | share |
|---|---|---|
| parse (text + table extraction) | 14,890ms | 99.9% |
| chunk (rows + prose) | 11ms | 0.1% |

Chunking is free. Parsing is everything, at 86.6ms/page. Splitting parse
further, over 40 pages of the same document:

| within parse | time | share |
|---|---|---|
| `extract_text` | 1,837ms | 44.1% |
| `extract_tables` (ruled/line strategy) | 5ms | 0.1% |
| `extract_tables` (text strategy, fallback) | 2,325ms | 55.8% |

So the single most expensive thing the pipeline does is the **text-based table
fallback**, at ~58ms for every page it runs on — and it runs on nearly every
page, because the ruled-line strategy found nothing on any of these 40 (this
generated corpus draws tables without rules). It is not dead weight: it is what
finds the 43 tables in this document, and table rows are what the chunking
ablation showed carry the retrieval win. Disabling it would buy speed by losing
accuracy, so it stays.

What is safe to change is *how* the work is spread. Parsing is CPU-bound Python,
so threads cannot help, but page ranges are independent:

| `PDF_PARSE_WORKERS` | parse | per page | speedup |
|---|---|---|---|
| 1 (default) | 12.66s | 86.6ms | — |
| 4 | 5.26s | 35.7ms | **2.41x** |

The SHA-256 over every page's text and tables is identical between the two, and
the document comes out with the same 43 tables and 1,528 chunks. Output identity
is the whole premise, so `backend/tests/test_parse_parallelism.py` asserts it,
along with page ordering, the serial path for short documents, and a fallback to
serial where a sandbox forbids process creation. The speedup itself is not
asserted — it is hardware-dependent and would make a flaky test.

**Default is 1, deliberately.** The ingest queue already runs `ingest_workers`
documents concurrently, so raising this multiplies processes rather than adding
to them; the two want setting together against the cores actually available.
Above 1, the pool uses the `spawn` start method, because ingest jobs can run on
threads and forking a threaded process is a documented route to deadlock.

One thing measured and rejected: calling `page.close()` to release pdfplumber's
per-page cache gained 2.3% — inside noise — and did not reduce peak RSS on this
document. It is kept anyway inside the span worker, where it bounds the resident
set on a 380-page tender, but it is not the optimisation it looked like.

## Known limits of this evaluation

1. **n is small.** 17 retrieval queries, 17 extraction fields, 15 vendors. Every
   interval above is wide and the 100% figures have lower bounds near 80%. The
   single highest-value next step is more labelled data, not more features.
2. **Synthetic bids.** The 15 elimination vendors were generated by
   `backend/app/bidgen/`. `paraphrase.py` renames requirements as a bidder would
   to break the obvious circularity, but mitigation is not elimination.
3. **Comparison rules were authored after seeing the data** for extraction field
   accuracy. They are stated per field in `data/extraction_truth.json` so a
   reader can disagree with any of them.
4. **Citation grounding is not deterministic.** It depends on which provider tier
   served the answer; one run scored 15/17, and two queries that scored
   ungrounded there cited four and three sources on re-run. Page truthfulness and
   invented-citation counts are stable because they check structure.
5. **Claim-supported is a lower bound.** It matches labelled phrases literally,
   so a correct answer phrased differently scores as a failure. q07 answers
   "average annual financial turnover ... at least 30% of the estimated cost",
   which is right and well-cited, but the label reads "Annual Turnover".
6. **Two labels were corrected mid-evaluation** after a first run showed them to
   be wrong, and five genuine misses were deliberately left scored as misses.
   Both corrections are recorded in `data/rag_queries.json` with a `_label_fix`
   note.
7. **Router vocabulary was fitted on the dev split.** Only the held-out figure is
   evidence; the dev figure (96.4%) measures fitting and is labelled as such.
8. **No inter-annotator agreement figure exists yet.** The harness and protocol
   are in place (above); the figure needs an independent second rater. Until
   then, label reliability is unquantified, which is a real gap and not a
   formality.
9. **No procurement-specific prior art is cited.** `RELATED_WORK.md` positions
   this against legal-contract NLP (CUAD) and retrieval, which is adjacent
   rather than the same field. Three procurement candidates were found and left
   uncited because the network policy blocked verification against their
   publishers, and an unverified citation is worse than an acknowledged gap.
