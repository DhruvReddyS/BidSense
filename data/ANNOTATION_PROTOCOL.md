# Annotation protocol

Every accuracy figure in Section 10 is measured against the labels in
`tracking_vendors.csv` and `rag_queries.json`. That makes the labels part of the
method, and a method needs a reliability figure — so a second annotator relabels
a sample independently and the two passes are compared with Cohen's κ.

**The second annotator must be a different person from whoever wrote the
labels.** A second pass by the original annotator reproduces their own reading
of an ambiguous clause and reports that consistency as reliability. The same
applies to an assistant re-reading its own labels: it is not an independent
rater on its own work. κ between a rater and themselves measures nothing.

Budget about an hour per dimension.

```bash
cd backend
python -m scripts.double_label --emit ground --out /tmp/sheet_ground.csv
# ... fill the `label` column ...
python -m scripts.double_label --score ground --sheet /tmp/sheet_ground.csv
```

## Before you start

Do **not** open `tracking_vendors.csv` or `rag_queries.json` first. The sheet
omits the recorded label and the `intended_reason` text deliberately — the
reason for a document-ground elimination reads "… not enclosed", which hands
over the answer. Work from the bid PDF and the tender it answers.

If a unit is genuinely undecidable from the documents, label your best reading
and note it; a disagreement is more useful than a guess recorded as confident.

---

## Dimension: `ground` — why a bid is eliminated

12 units (the eliminated bids only; a passing bid has no ground).

| label | means |
|---|---|
| `criteria` | The bid **fails a qualification condition**. The information is present and disqualifying: a turnover below the floor, a similar-work value under the threshold, an expired certificate, a debarment or liquidation declaration. |
| `document` | The bid **never provided a mandatory enclosure**. The requirement is unanswered rather than answered badly. |

### Decision rules

1. **Ask what is missing: a value, or a document?** If the bidder supplied the
   document and its contents disqualify them, that is `criteria`. If the
   document is absent from the enclosure list, that is `document`.
2. **A condition is not a missing document.** Debarment, blacklisting and
   liquidation are `criteria` even though they are often declared *in* a
   document — the bid is rejected for the declared fact, not for a gap.
3. **An enclosed-but-expired certificate is `criteria`.** The document is there;
   it fails on its date.
4. **If both are true, label the one the tender would reject on first.** A
   mandatory-enclosure check normally precedes financial evaluation, so a bid
   missing a required form *and* short on turnover is `document`. Note it.

## Dimension: `status` — whether a bid survives

19 units.

| label | means |
|---|---|
| `pass` | Clears every mandatory enclosure and every qualification threshold. |
| `eliminate` | Fails at least one. |

### Decision rules

1. **"Not less than" includes the boundary.** A bid sitting exactly on a
   threshold passes. Several bids are built to sit exactly there; reading `>`
   where the tender says "not less than" flips precisely those.
2. **Price is never a trade-off against a mandatory requirement.** The lowest
   quote still fails if a required form is absent.
3. **Write-up quality is not a criterion.** A fluent bid that misses a threshold
   is eliminated; a terse one that clears everything passes.

## Dimension: `kind` — what a query asks for

One unit per labelled query. Allowed labels are read from the query set itself
(currently `condition`, `deadline`, `eligibility`, `emd`, `scope`, `value`), so
the taxonomy can grow without editing this file.

| label | means |
|---|---|
| `emd` | The earnest money deposit: amount, form, validity or exemption. |
| `value` | A monetary figure that is not the EMD — estimated cost, fee, security deposit. |
| `deadline` | A date or time: submission, opening, validity, completion period. |
| `eligibility` | Who may bid: turnover, experience, registration, constitution. |
| `condition` | A contractual or procedural obligation — penalties, warranty, payment terms. |
| `scope` | What the work physically is. |

### Decision rules

1. **Label what the question asks for, not where the answer happens to live.**
   A turnover floor printed inside an eligibility table is `eligibility` whether
   or not the answer sits in a table row.
2. **`emd` beats `value`.** Earnest money is the one amount with its own label;
   use `value` only for other figures.
3. **A date attached to a condition is still `deadline`** when the date is the
   thing asked for ("by when must the work be completed").

---

## Reporting the result

Report κ **with its n and the raw agreement**, never κ alone. On 12 units,
10 agreements chance-correct to κ = 0.67, and with a two-category label and a
near-even split the figure moves roughly 0.17 per unit — so a single
adjudicated disagreement visibly shifts it. State that, rather than presenting
the number as stable.

`--score` lists every disagreement. Adjudicate each one:

- The annotator is right → fix the label in the repository and say so in the
  commit. The corrected label is the contribution; κ is the instrument that
  found it.
- The repository is right → the protocol above was ambiguous. Tighten the
  decision rule that failed, because the next annotator will read it the same
  way.

A disagreement left unexplained is a label the paper cannot defend.
