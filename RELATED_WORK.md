# Related work

Positioning for the evaluation chapter. Every entry below was checked against
its publisher of record — ACL Anthology, the NeurIPS proceedings, a journal DOI
— and the bibliographic details (authors, venue, volume, pages) come from those
records rather than from recall. **Nothing here is cited from memory.** Where a
claim could not be confirmed it is marked rather than smoothed over, and the
open gaps are listed at the end instead of being filled with a plausible-looking
reference.

## 1. Retrieval-augmented generation

**Lewis et al., "Retrieval-Augmented Generation for Knowledge-Intensive NLP
Tasks," NeurIPS 33 (2020).** arXiv:2005.11401. Pairs a seq2seq generator
(parametric memory) with a dense vector index queried by a neural retriever
(non-parametric memory), in two variants: one conditioning on the same retrieved
passages for the whole output, one able to switch passages per token.

*Relation to this work.* This is the architecture BidSense adopts for the
question-answering path, and the paper's framing is also where this project
departs from it. RAG is evaluated there on open-domain QA, where a fluent answer
supported by *some* retrieved passage is a good answer. In tender evaluation the
clause that was cited is the deliverable: an answer that states the right EMD
figure while citing the wrong clause is not a partially correct answer, it is an
audit failure. That is why §5.2 measures citation faithfulness separately from
answer correctness rather than reporting a single score.

## 2. Dense vs. sparse retrieval

**Karpukhin et al., "Dense Passage Retrieval for Open-Domain Question
Answering," EMNLP 2020, pp. 6769–6781** (ACL Anthology 2020.emnlp-main.550).
Shows a dual-encoder trained on a small number of question–passage pairs beating
Lucene-BM25 by 9–19 points of top-20 retrieval accuracy.

**Robertson and Zaragoza, "The Probabilistic Relevance Framework: BM25 and
Beyond," Foundations and Trends in Information Retrieval 3(4):333–389 (2009).**
DOI 10.1561/1500000019. The survey of the probabilistic relevance framework and
the ranking functions derived from it, BM25 and BM25F included.

*Relation to this work.* These two justify the baseline design. BM25 is the
reference point in `scripts/baseline_retrieval.py`, chosen because it is a
genuine contender on this corpus rather than a strawman: tender documents are
dense with exact figures and clause numbers, which is lexical matching's
strongest ground. DPR's result is also a reminder that the dense advantage is
corpus-dependent — the same paper's SQuAD numbers are the usual counterexample,
where high lexical overlap between question and passage favours BM25. A
third-party summary quotes 68.8% vs 63.2% top-20 there; **that figure was not
confirmed against the paper and is not relied on.** This project measures its
own arms on its own corpus for exactly that reason, and the comparison is paired
in a single process so a label fix between runs cannot be credited to the
embeddings.

## 3. Embedding model

**Xiao, Liu, Zhang, Muennighoff, Lian and Nie, "C-Pack: Packed Resources For
General Chinese Embeddings," arXiv:2309.07597 (2023); published at SIGIR 2024.**
Releases the C-MTP training corpus, the C-MTEB benchmark (6 tasks, 35 datasets)
and the BGE family of embedding models, with English data and models reaching
state-of-the-art MTEB results at release.

*Relation to this work.* BGE (`BAAI/bge-base-en-v1.5`) is the retriever here.
It runs locally, which matters for §8: a tender under evaluation is commercially
confidential, and a hosted embedding API would mean transmitting bid contents to
a third party. The earlier arXiv title ("… Packaged Resources To Advance General
Chinese Embedding") differs from the published one; the retitled version is
cited.

## 4. Clause-level understanding of contractual documents

**Hendrycks, Burns, Chen and Ball, "CUAD: An Expert-Annotated NLP Dataset for
Legal Contract Review," NeurIPS 2021 Datasets and Benchmarks track.**
arXiv:2103.06268. 13,000+ expert annotations over 510 commercial contracts
across 41 clause categories, framed as flagging the passages a human reviewer
should read rather than summarising them.

*Relation to this work.* The nearest well-established neighbour, and the closest
analogue to this project's labelling effort. Two differences shape the method
here. CUAD identifies clause *categories* within one document; tender evaluation
requires checking a bid against the requirements of a *different* document, so
the unit of judgement is a (requirement, response) pair rather than a span.
And CUAD's design goal — surface what a reviewer should read — is the posture
this project takes deliberately: §5.2's deterministic engine decides
eliminations and the model's role is to locate and cite evidence, not to
adjudicate.

## 5. Whether a citation actually supports its claim

**Rashkin et al., "Measuring Attribution in Natural Language Generation
Models," Computational Linguistics 49(4):777–840 (2023).** DOI
10.1162/coli_a_00486; ACL Anthology 2023.cl-4.2. Defines AIS (Attributable to
Identified Sources) and a two-stage human annotation pipeline, with attribution
judged by whether a statement can be justified as "According to P, s."

*Relation to this work.* This is the standard `scripts/evaluate_citations.py`
is built against. The AIS question — can this statement be justified from the
cited source alone — is exactly the citation-faithfulness check in §5.2, and it
is what separates the two numbers reported there: on the LLM-only elimination
baseline the model reached the right verdict while citing the wrong clause, so
a correctness-only metric would have scored it as working.

## 6. Agreement between annotators

**Cohen, "A Coefficient of Agreement for Nominal Scales," Educational and
Psychological Measurement 20(1):37–46 (1960).** DOI 10.1177/001316446002000104.
Introduces κ, correcting raw agreement for the agreement two raters would reach
by chance.

**Landis and Koch, "The Measurement of Observer Agreement for Categorical
Data," Biometrics 33:159–174 (1977).** Source of the interpretation bands
(<0.00 poor, 0.00–0.20 slight, 0.21–0.40 fair, 0.41–0.60 moderate, 0.61–0.80
substantial, 0.81–1.00 almost perfect).

*Relation to this work.* κ is the instrument in `scripts/double_label.py`, and
Cohen's chance correction is the whole point of using it: 12 of 19 bids in this
set are eliminated, so two annotators who both simply answer "eliminate" agree
63% of the time while sharing no judgement at all. The Landis–Koch bands are
quoted in `app/rag/stats.py` so a number is not left to the reader's taste —
but they are a heuristic, not a principled cutoff, and the literature treats
them as such. They are reported as a band alongside κ, its n and the raw
agreement, never as a pass mark.

---

## Gaps, stated rather than filled

**No procurement-specific peer-reviewed anchor is cited yet.** A search surfaced
several candidates — a sentence-transformer pipeline scoring German Swiss
call-for-tender sentences against sustainability criteria catalogues
(CEUR-WS), a retrieval-augmented procurement-validation dataset for Latvian
(Springer), an in-context retrieval framework for construction-code compliance
(CTRAG) — and the search itself reported none as a clear match. The
environment's network policy denied `arxiv.org`, `ceur-ws.org` and
`link.springer.com`, so none could be checked against its publisher of record.
**They are therefore listed here as leads and deliberately not cited.** Several
are dated 2026 and may be very recent; that makes verification more necessary,
not less.

To close this gap, either widen network access for those hosts and re-run the
verification, or check the three leads by hand. Until one is confirmed, §2
should claim adjacency to legal-contract NLP (CUAD) and not to a procurement
literature this project has not read.

**Also not yet surveyed:** table-structure-aware retrieval, which is the
closest literature to the table-row chunking ablation and the one place a
reviewer is most likely to ask for prior art, since that ablation is a
contribution of this work.

## Verification note

Each cited entry above was corroborated across at least two independent
authoritative records (publisher page, proceedings entry, DOI resolver). Direct
PDF retrieval was unavailable — the proxy returns 403 for the publisher hosts —
so quoted *contents* rest on publisher abstracts rather than full text. Before
submission, confirm page numbers and author initials against the publisher's
own BibTeX, and read each paper in full before describing its method in the
prose.
