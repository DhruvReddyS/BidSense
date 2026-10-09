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

Run:  python -m scripts.baseline_retrieval [--k 5]
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
from app.rag.stats import fmt_pct_ci
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
    args = parser.parse_args()
    k = args.k

    queries = json.loads(QUERY_PATH.read_text())["queries"]
    tally = {"h1": 0, "h3": 0, f"h{k}": 0, "rr": 0.0, "n": 0}
    per_kind: dict[str, list[bool]] = {}
    rows = []

    for stem in sorted({q["tender"] for q in queries}):
        document = parse_document(NOTIF_DIR / f"{stem}.pdf", DocumentKind.NOTIFICATION)
        chunks = chunk_document(document)
        texts = [c.text for c in chunks]
        index = BM25([tokenize(t) for t in texts])

        for query in [q for q in queries if q["tender"] == stem]:
            scored = index.scores(tokenize(query["question"]))
            order = sorted(range(len(scored)), key=lambda i: -scored[i])[:k]
            phrases = [_norm(p) for p in query["answer_contains"]]
            hits = [any(p in _norm(texts[i]) for p in phrases) for i in order]
            first = next((i + 1 for i, h in enumerate(hits) if h), None)

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
    print(
        "\nCompare against scripts/evaluate_retrieval.py. The questions were"
        "\nwritten to AVOID the document's own wording, which is a deliberate"
        "\nhandicap for a keyword method -- so read this as the floor a semantic"
        "\nretriever has to clear, not as BM25's best possible showing."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
