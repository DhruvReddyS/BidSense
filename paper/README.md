# Paper

`bidsense.tex` — IEEE conference format (IEEEtran), self-contained: the
bibliography is inline (`thebibliography`) and the architecture figure is TikZ,
so there are no external `.bib` or image dependencies.

## Compiling

Easiest is Overleaf: upload `bidsense.tex`, select **pdfLaTeX**. `IEEEtran.cls`
ships with Overleaf, so nothing else is needed.

Locally, with a TeX Live install:

```bash
pdflatex bidsense && pdflatex bidsense   # twice, to settle cross-references
```

(The second pass is what resolves `\ref` to table and figure numbers.)

## Before submitting

Three things need a human:

1. **`[PENDING]` markers.** Three figures are marked pending in
   Section V and Table III: the LLM-only elimination baseline, and
   inter-annotator κ. The instruments exist
   (`backend/scripts/baseline_elimination.py`,
   `backend/scripts/double_label.py`) — they need a provider with quota and an
   independent second rater respectively. **Do not fill these from memory of an
   earlier run.** An earlier informal run of the baseline used four bids, which
   Section V-C explains cannot reach significance whatever it showed.
2. **Author block.** Institution and city are `[Institution]` / `[City]`.
3. **Procurement prior art.** Section II states plainly that no verified
   peer-reviewed procurement anchor is cited, and why. If you verify one against
   its publisher, add it there; if not, leave the gap stated — an unverified
   citation is worse than an acknowledged absence.

## What the paper claims, and what it does not

The contribution is the **boundary between reading and deciding**: an LLM may
locate and cite evidence, only deterministic code may eliminate a bidder. The
query router is presented as a supporting component, not as the novelty — a
vocabulary classifier fitted on a dev split and scoring 95.5% on 22 held-out
queries will not survive being called novel, and leading with it would invite
exactly that.

Section VI states the threats without hedging, the synthetic bid corpus first.
That section is an asset rather than a liability: an examiner who finds the
circularity objection already stated, quantified and bounded has nothing left
to catch you with.
