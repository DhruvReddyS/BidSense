"""BM25 keyword baseline for retrieval (Scope Section 10).

Without a baseline, "hit@5 = 70.6%" is a number with nothing to compare it to:
it could be evidence that dense retrieval works, or evidence that the questions
are easy. This runs classical BM25 over exactly the same chunks and the same
labelled queries, so the dense figures have a reference point and the project
can say what the embeddings are actually buying.

BM25 is the right baseline rather than a strawman. It is what production search
used before dense retrieval, it is strong on the exact figures and clause
numbers this corpus is full of, and on a corpus where answers live in terse
table rows it is a genuine contender -- it does not need the semantic bridge
that "earnest money" -> "EMD" requires, because it never had one.

Everything is in memory and offline: parse, chunk, score. No Qdrant, no
embedding model, no LLM.

With `--dense` it additionally scores the dense arm over the *same* chunks and
the *same* queries in the same process, and reports the paired significance of
the difference. That is the only honest way to state the headline claim: quoting
BM25 from this script and the dense figure from a separate run of
evaluate_retrieval.py compares two different executions, and any label fix or
chunker change between them is silently credited to the embeddings. The flag is
opt-in so the default run keeps the offline property above -- `--dense` loads
the BGE model.

Run:  python -m scripts.baseline_retrieval [--k 5] [--dense]
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

from app.ingest.chunking import chunk_document
from app.ingest.loader import parse_document
from app.rag.stats import fmt_delta_ci, fmt_pct_ci, fmt_sign_test, paired_counts
from app.schemas.common import DocumentKind

QUERY_PATH = Path(__file__).parents[2] / "data" / "rag_queries.json"
NOTIF_DIR = Path(__file__).parents[2] / "data" / "notifications"

_TOKEN = re.compile(r"[a-z0-9][a-z0-9.,/%&-]*")
#: Kept deliberately small. BM25's IDF already discounts corpus-common words;
#: removing only syntactic filler avoids hand-tuning the baseline into either a
#: strawman or an unfairly polished competitor.
_STOP = frozenset(
    "a an and are as at be by do does for from has have how i if in into is it "
    "its me must my of on or shall should that the this to under was what when "
    "which who will with would you your".split()
)


def tokenize(text: str) -> list[str]:
    """Same tokenizer for queries and documents, keeping figures intact.

    "2,98,720.00" must survive as one token: in this corpus the figure is
    usually the most discriminating thing in the question.
    """
    return [
        t.strip(".,")
        for t in _TOKEN.findall((text or "").casefold())
        if t.strip(".,") and t.strip(".,") not in _STOP
    ]


class BM25:
    """Okapi BM25 with the standard parameters."""

    def __init__(self, documents: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs = documents
        self.k1, self.b = k1, b
        self.n = len(documents)
        self.lengths = [len(d) for d in documents]
        self.avg_len = (sum(self.lengths) / self.n) if self.n else 0.0
        self.tf = [Counter(d) for d in documents]
        df: Counter[str] = Counter()
        for doc in documents:
            df.update(set(doc))
        # Floored at a small positive value: the textbook IDF goes negative for
        # a term in more than half the documents, which would let a common word
        # actively penalise a chunk that contains it.
        self.idf = {
            term: max(1e-9, math.log(1 + (self.n - count + 0.5) / (count + 0.5)))
            for term, count in df.items()
        }

    def scores(self, query: list[str]) -> list[float]:
        out = [0.0] * self.n
        for term in query:
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                freq = tf.get(term)
                if not freq:
                    continue
                norm = 1 - self.b + self.b * (self.lengths[i] / (self.avg_len or 1))
                out[i] += idf * (freq * (self.k1 + 1)) / (freq + self.k1 * norm)
        return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").casefold()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--dense", action="store_true",
        help="also score the dense arm and report paired significance "
             "(loads the embedding model)",
    )
    args = parser.parse_args()
    k = args.k

    queries = json.loads(QUERY_PATH.read_text())["queries"]
    tally = {"h1": 0, "h3": 0, f"h{k}": 0, "rr": 0.0, "n": 0}
    per_kind: dict[str, list[bool]] = {}
    rows = []
    #: query id -> per-arm scores, so the arms can be paired by query rather
    #: than compared as two independently-run aggregates.
    paired: dict[str, dict[str, dict[str, float]]] = {}

    if args.dense:
        from app.vector.embeddings import embed_passages, embed_query

    def record(arm: str, query: dict, hits: list[bool]) -> int | None:
        first = next((i + 1 for i, h in enumerate(hits) if h), None)
        paired.setdefault(query["id"], {})[arm] = {
            "hit_at_1": float(bool(hits[:1] and hits[0])),
            "hit_at_3": float(any(hits[:3])),
            f"hit_at_{k}": float(any(hits[:k])),
            "rr": 1.0 / first if first else 0.0,
        }
        return first

    for stem in sorted({q["tender"] for q in queries}):
        document = parse_document(NOTIF_DIR / f"{stem}.pdf", DocumentKind.NOTIFICATION)
        chunks = chunk_document(document)
        texts = [c.text for c in chunks]
        index = BM25([tokenize(t) for t in texts])
        subset = [q for q in queries if q["tender"] == stem]

        vectors = None
        if args.dense:
            import numpy as np
            vectors = np.array(embed_passages(texts))

        for query in subset:
            scored = index.scores(tokenize(query["question"]))
            order = sorted(range(len(scored)), key=lambda i: -scored[i])[:k]
            phrases = [_norm(p) for p in query["answer_contains"]]
            hits = [any(p in _norm(texts[i]) for p in phrases) for i in order]
            first = record("bm25", query, hits)

            if vectors is not None:
                import numpy as np
                qv = np.array(embed_query(query["question"]))
                dense_order = np.argsort(-(vectors @ qv))[:k]
                dense_hits = [
                    any(p in _norm(texts[i]) for p in phrases) for i in dense_order
                ]
                record("dense", query, dense_hits)

            tally["n"] += 1
            tally["h1"] += bool(hits[:1] and hits[0])
            tally["h3"] += any(hits[:3])
            tally[f"h{k}"] += any(hits[:k])
            tally["rr"] += 1.0 / first if first else 0.0
            per_kind.setdefault(query["kind"], []).append(any(hits[:k]))
            rows.append((query["id"], query["kind"], first, query["question"]))

    print(f"{'id':5} {'kind':12} {'rank':>5}  question")
    print("-" * 86)
    for qid, kind, first, question in rows:
        print(f"{qid:5} {kind:12} {str(first or '-'):>5}  {question[:56]}")

    n = tally["n"]
    print("\n" + "=" * 86)
    print("BM25 KEYWORD BASELINE")
    print(f"  hit@1   : {fmt_pct_ci(tally['h1'], n)}")
    print(f"  hit@3   : {fmt_pct_ci(tally['h3'], n)}")
    print(f"  hit@{k}   : {fmt_pct_ci(tally[f'h{k}'], n)}")
    print(f"  MRR     : {tally['rr'] / n:.3f}")
    print(f"\n  by question kind (hit@{k}):")
    for kind in sorted(per_kind):
        got = per_kind[kind]
        print(f"    {kind:12} {sum(got)}/{len(got)}")
    if args.dense:
        shared = [q["id"] for q in queries
                  if {"bm25", "dense"} <= set(paired.get(q["id"], {}))]
        dense_tally = {
            key: sum(paired[i]["dense"][key] for i in shared)
            for key in ("hit_at_1", "hit_at_3", f"hit_at_{k}")
        }
        print("\n" + "=" * 86)
        print("DENSE ARM (same chunks, same queries, same process)")
        print(f"  hit@1   : {fmt_pct_ci(int(dense_tally['hit_at_1']), len(shared))}")
        print(f"  hit@3   : {fmt_pct_ci(int(dense_tally['hit_at_3']), len(shared))}")
        print(f"  hit@{k}   : {fmt_pct_ci(int(dense_tally[f'hit_at_{k}']), len(shared))}")
        print(f"  MRR     : "
              f"{sum(paired[i]['dense']['rr'] for i in shared) / max(1, len(shared)):.3f}")

        print("\n" + "=" * 86)
        print(f"DENSE vs BM25 -- paired over the same {len(shared)} queries")
        for key, label in (("hit_at_1", "hit@1"), ("hit_at_3", "hit@3"),
                           (f"hit_at_{k}", f"hit@{k}")):
            improved, regressed, tied = paired_counts(
                [paired[i]["bm25"][key] for i in shared],
                [paired[i]["dense"][key] for i in shared],
            )
            print(f"  {label:7} {fmt_sign_test(improved, regressed, tied)}")
        deltas = [paired[i]["dense"]["rr"] - paired[i]["bm25"]["rr"] for i in shared]
        print(f"  {'MRR':7} {fmt_delta_ci(deltas)}")

    print(
        "\nCompare against scripts/evaluate_retrieval.py. The questions were"
        "\nwritten to AVOID the document's own wording, which is a deliberate"
        "\nhandicap for a keyword method -- so read this as the floor a semantic"
        "\nretriever has to clear, not as BM25's best possible showing."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
