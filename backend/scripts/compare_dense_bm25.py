"""Dense retrieval against the BM25 baseline, paired and significance-tested.

This is the comparison the project's central claim rests on: Section 2.1 argues
that RAG is doing real semantic work here rather than dressing up keyword
search. Two sets of percentages side by side do not establish that. The arms
run on IDENTICAL queries, so the test must be paired -- and on a corpus this
size the pairing is most of the available statistical power.

Reported, with their verdicts, so a reader does not have to eyeball intervals:
exact McNemar on hit@1 and hit@k, paired bootstrap on MRR.

Run:  python -m scripts.compare_dense_bm25 [--k 5]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from sqlalchemy import select

from app.db.models import TenderNotificationRow
from app.db.session import session_scope
from app.ingest.chunking import chunk_document
from app.ingest.loader import parse_document
from app.rag.retrieve import retrieve
from app.rag.stats import bootstrap_diff, fmt_pct_ci, fmt_test, mcnemar
from app.schemas.common import DocumentKind
from scripts.baseline_retrieval import BM25, tokenize

QUERY_PATH = Path(__file__).parents[2] / "data" / "rag_queries.json"
NOTIF_DIR = Path(__file__).parents[2] / "data" / "notifications"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").casefold()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    k = args.k

    queries = json.loads(QUERY_PATH.read_text())["queries"]
    with session_scope() as session:
        tenders = {
            Path(row.source_file or "").stem: row.tender_id
            for row in session.scalars(select(TenderNotificationRow)).all()
            if Path(row.source_file or "").stem.startswith("NOTIF_")
        }

    arms = {
        "dense": {"h1": [], "hk": [], "rr": []},
        "bm25": {"h1": [], "hk": [], "rr": []},
    }
    rows = []

    for stem in sorted({q["tender"] for q in queries}):
        document = parse_document(NOTIF_DIR / f"{stem}.pdf", DocumentKind.NOTIFICATION)
        chunks = chunk_document(document)
        texts = [c.text for c in chunks]
        index = BM25([tokenize(t) for t in texts])

        for query in [q for q in queries if q["tender"] == stem]:
            phrases = [_norm(p) for p in query["answer_contains"]]

            def record(arm: str, ordered_texts: list[str]) -> int | None:
                hits = [
                    any(p in _norm(t) for p in phrases) for t in ordered_texts[:k]
                ]
                first = next((i + 1 for i, h in enumerate(hits) if h), None)
                arms[arm]["h1"].append(bool(hits[:1] and hits[0]))
                arms[arm]["hk"].append(any(hits))
                arms[arm]["rr"].append(1.0 / first if first else 0.0)
                return first

            dense_chunks = retrieve(
                query["question"], tender_id=tenders[stem],
                doc_kind=DocumentKind.NOTIFICATION, top_k=k,
            )
            d_first = record("dense", [c.text for c in dense_chunks])

            scores = index.scores(tokenize(query["question"]))
            order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
            b_first = record("bm25", [texts[i] for i in order])

            rows.append((query["id"], query["kind"], d_first, b_first))

    print(f"{'id':5} {'kind':12} {'dense':>6} {'bm25':>6}   question")
    print("-" * 78)
    for qid, kind, d, b in rows:
        print(f"{qid:5} {kind:12} {str(d or '-'):>6} {str(b or '-'):>6}")

    n = len(rows)
    print("\n" + "=" * 78)
    print(f"{'metric':10} {'dense':>28} {'bm25':>28}")
    for label, key in (("hit@1", "h1"), (f"hit@{k}", "hk")):
        print(f"{label:10} {fmt_pct_ci(sum(arms['dense'][key]), n):>28} "
              f"{fmt_pct_ci(sum(arms['bm25'][key]), n):>28}")
    print(f"{'MRR':10} {sum(arms['dense']['rr']) / n:>28.3f} "
          f"{sum(arms['bm25']['rr']) / n:>28.3f}")

    print("\nPaired tests, dense vs BM25 on the same queries:")
    print("  " + fmt_test("hit@1  (exact McNemar)",
                          mcnemar(arms["bm25"]["h1"], arms["dense"]["h1"])))
    print("  " + fmt_test(f"hit@{k}  (exact McNemar)",
                          mcnemar(arms["bm25"]["hk"], arms["dense"]["hk"])))
    print("  " + fmt_test("MRR    (paired bootstrap)",
                          bootstrap_diff(arms["bm25"]["rr"], arms["dense"]["rr"])))

    print(
        "\nThe questions are deliberately written in wording the documents do"
        "\nnot use, which handicaps a keyword method. Read BM25 as the floor a"
        "\nsemantic retriever must clear, not as BM25 at its best."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
