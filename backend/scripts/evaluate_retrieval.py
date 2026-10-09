"""Retrieval precision@k and MRR (Scope Sections 10 and 2.1.4).

Section 2.1.4 asks for this explicitly, in its own words: don't let RAG
"quietly become 'we called an embedding API and it worked.'" This is the
script that makes that impossible to do accidentally.

WHAT IS MEASURED
  precision@k  of the top k chunks retrieved, the fraction that actually
               contain the answer. Averaged over queries.
  hit@k        did ANY of the top k contain it -- "would the vendor have got
               their answer", which is the question a user cares about.
  MRR          1/rank of the first chunk containing the answer, so a system
               that puts the answer 5th scores worse than one that puts it 1st
               even though both "hit".
  page hit     did the retrieved chunk come from a page the answer is on.
               Reported separately because chunk boundaries can split a phrase
               across two chunks, which would understate the text measure.

WHY A PHRASE AND NOT A JUDGEMENT
  Relevance here means "the answer is readable in this chunk", checked by
  normalised substring match against a phrase located in the source PDF. No
  LLM judges its own retrieval, and the test is reproducible by anyone with
  the corpus. The cost is strictness: a chunk about EMD that omits the figure
  scores zero. That is the right direction to be wrong in.

Run:  python -m scripts.evaluate_retrieval [--k 5] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from app.db.models import TenderNotificationRow
from app.db.session import session_scope
from app.rag.retrieve import retrieve
from app.rag.stats import fmt_pct_ci
from app.schemas.common import DocumentKind

QUERY_PATH = Path(__file__).parents[2] / "data" / "rag_queries.json"


def _norm(text: str) -> str:
    """Collapse whitespace so a phrase split across a line break still matches."""
    return re.sub(r"\s+", " ", text or "").casefold()


@dataclass
class QueryResult:
    qid: str
    question: str
    kind: str
    ranks: list[bool]          # per retrieved chunk, in order: contains answer?
    page_ranks: list[bool]     # per retrieved chunk: from a gold page?
    pages_returned: list[int | None]
    first_hit: int | None      # 1-indexed rank of first text hit

    def precision_at(self, k: int) -> float:
        window = self.ranks[:k]
        return (sum(window) / len(window)) if window else 0.0

    def hit_at(self, k: int) -> bool:
        return any(self.ranks[:k])

    def page_hit_at(self, k: int) -> bool:
        return any(self.page_ranks[:k])

    @property
    def rr(self) -> float:
        return (1.0 / self.first_hit) if self.first_hit else 0.0


def _tender_ids() -> dict[str, str]:
    """Map labelled notification ids to the tender_id actually indexed."""
    mapping: dict[str, str] = {}
    with session_scope() as session:
        for row in session.scalars(select(TenderNotificationRow)).all():
            stem = Path(row.source_file or "").stem
            if stem.startswith("NOTIF_"):
                mapping[stem] = row.tender_id
    return mapping


def evaluate(k: int) -> tuple[list[QueryResult], list[str]]:
    spec = json.loads(QUERY_PATH.read_text())
    by_stem = _tender_ids()
    results: list[QueryResult] = []
    skipped: list[str] = []

    # Fall back to tender_id matching for rows uploaded through the API, whose
    # source_file is a temp path.
    with session_scope() as session:
        all_rows = session.scalars(select(TenderNotificationRow)).all()
        loose = {r.tender_id: r for r in all_rows}

    for query in spec["queries"]:
        stem = query["tender"]
        tender_id = by_stem.get(stem)
        if tender_id is None:
            # Try matching on a distinctive fragment of the labelled stem.
            hint = stem.replace("NOTIF_", "").split("_")[0]
            candidates = [t for t in loose if hint.casefold() in t.casefold()]
            tender_id = candidates[0] if len(candidates) == 1 else None
        if tender_id is None:
            skipped.append(f"{query['id']} ({stem} not ingested)")
            continue

        chunks = retrieve(
            query["question"],
            tender_id=tender_id,
            doc_kind=DocumentKind.NOTIFICATION,
            top_k=k,
        )
        phrases = [_norm(p) for p in query["answer_contains"]]
        gold = set(query.get("gold_pages") or [])

        ranks, page_ranks, pages = [], [], []
        for chunk in chunks:
            body = _norm(chunk.text)
            ranks.append(any(p in body for p in phrases))
            page_ranks.append(chunk.source_page in gold if chunk.source_page else False)
            pages.append(chunk.source_page)

        first = next((i + 1 for i, hit in enumerate(ranks) if hit), None)
        results.append(QueryResult(
            qid=query["id"], question=query["question"], kind=query["kind"],
            ranks=ranks, page_ranks=page_ranks, pages_returned=pages, first_hit=first,
        ))
    return results, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    results, skipped = evaluate(args.k)
    if not results:
        print("No queries could be evaluated. Is the corpus ingested?")
        for s in skipped:
            print("  skipped:", s)
        return 1

    print(f"{'id':5} {'kind':12} {'P@1':>5} {'P@3':>5} {'hit@1':>6} {'hit@3':>6} "
          f"{'hit@'+str(args.k):>6} {'1/rank':>7}  pages returned")
    print("-" * 100)
    for r in results:
        print(f"{r.qid:5} {r.kind:12} {r.precision_at(1):5.2f} {r.precision_at(3):5.2f} "
              f"{str(r.hit_at(1)):>6} {str(r.hit_at(3)):>6} {str(r.hit_at(args.k)):>6} "
              f"{r.rr:7.3f}  {r.pages_returned}")

    n = len(results)
    def mean(fn):
        return sum(fn(r) for r in results) / n

    print("\n" + "=" * 100)
    print(f"Queries evaluated : {n}" + (f"   (skipped {len(skipped)})" if skipped else ""))
    print(f"  precision@1     : {mean(lambda r: r.precision_at(1)) * 100:5.1f}%")
    print(f"  precision@3     : {mean(lambda r: r.precision_at(3)) * 100:5.1f}%")
    print(f"  precision@{args.k}     : {mean(lambda r: r.precision_at(args.k)) * 100:5.1f}%")
    # Hit rates are proportions over a small n, so each carries its interval.
    # "64.7%" and "64.7% [41.3-82.7%, n=17]" are different claims.
    h1 = sum(1 for r in results if r.hit_at(1))
    h3 = sum(1 for r in results if r.hit_at(3))
    hk = sum(1 for r in results if r.hit_at(args.k))
    print(f"  hit@1           : {fmt_pct_ci(h1, n)}   <- answer was the TOP chunk")
    print(f"  hit@3           : {fmt_pct_ci(h3, n)}")
    print(f"  hit@{args.k}           : {fmt_pct_ci(hk, n)}   <- answer was retrieved at all")
    print(f"  MRR             : {mean(lambda r: r.rr):5.3f}")
    ph = sum(1 for r in results if r.page_hit_at(args.k))
    print(f"  page hit@{args.k}      : {fmt_pct_ci(ph, n)}   <- right page, phrase possibly split across chunks")
    print("\n  BM25 keyword baseline for the same questions: "
          "python -m scripts.baseline_retrieval")

    misses = [r for r in results if not r.hit_at(args.k)]
    if misses:
        print(f"\nMISSES ({len(misses)}/{n}) -- the part worth reading:")
        for r in misses:
            print(f"  {r.qid} [{r.kind}] {r.question}")
            print(f"      returned pages {r.pages_returned}; answer is not in any retrieved chunk")

    if skipped:
        print("\nSkipped:")
        for s in skipped:
            print("  ", s)

    if args.json:
        args.json.write_text(json.dumps({
            "k": args.k, "n": n,
            "precision_at_1": mean(lambda r: r.precision_at(1)),
            "precision_at_3": mean(lambda r: r.precision_at(3)),
            f"precision_at_{args.k}": mean(lambda r: r.precision_at(args.k)),
            "hit_at_1": mean(lambda r: r.hit_at(1)),
            "hit_at_3": mean(lambda r: r.hit_at(3)),
            f"hit_at_{args.k}": mean(lambda r: r.hit_at(args.k)),
            "mrr": mean(lambda r: r.rr),
            "skipped": skipped,
            "queries": [r.__dict__ for r in results],
        }, indent=2, default=str))
        print(f"\nWritten to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
