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
