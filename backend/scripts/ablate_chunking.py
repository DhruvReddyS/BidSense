"""Like-for-like ablation: table-row chunking vs the old size-only pass.

Why this exists. Row chunking was introduced after a measured retrieval
failure, and two labels in the query set were corrected in the same sitting.
Quoting the before-number from the first run and the after-number from the
second would credit the code change with an improvement that is partly a
harness fix -- the exact sleight of hand this project's evaluation is supposed
to make impossible.

So both arms are measured here against the SAME corrected labels, in memory,
without touching the live index: parse each document once, chunk it twice, embed
both sets, and score the labelled queries against each.

Arms
  legacy  tables appended to page prose via combined_text(), split by size.
  rows    prose and tables chunked separately, one chunk per table row.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from app.ingest.chunking import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP,
    Chunk,
    _detect_clause_ref,
    _split_to_size,
    chunk_document,
)
from app.ingest.loader import parse_document
from app.schemas.common import ChunkSection, DocumentKind
from app.rag.stats import fmt_delta_ci, fmt_sign_test, paired_counts
from app.vector.embeddings import embed_passages, embed_query

QUERY_PATH = Path(__file__).parents[2] / "data" / "rag_queries.json"
NOTIF_DIR = Path(__file__).parents[2] / "data" / "notifications"


def legacy_chunks(document) -> list[Chunk]:
    """The pre-fix behaviour: one size-split stream over prose PLUS tables."""
    chunks: list[Chunk] = []
    index = 0
    for page in document.pages:
        body = page.combined_text()
        if not body.strip():
            continue
        for piece in _split_to_size(body, DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP):
            chunks.append(Chunk(
                text=piece, page_number=page.page_number, chunk_index=index,
                section=ChunkSection.GENERAL, clause_ref=_detect_clause_ref(piece),
            ))
            index += 1
    return chunks


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").casefold()


def score(chunks: list[Chunk], queries: list[dict], k: int) -> dict:
    vectors = np.array(embed_passages([c.text for c in chunks]))
    out = {"p1": [], "hit1": [], "hit3": [], f"hit{k}": [], "rr": []}
    per_query = []
    for q in queries:
        qv = np.array(embed_query(q["question"]))
        order = np.argsort(-(vectors @ qv))[:k]
        phrases = [_norm(p) for p in q["answer_contains"]]
        hits = [any(p in _norm(chunks[i].text) for p in phrases) for i in order]
        first = next((i + 1 for i, h in enumerate(hits) if h), None)
        out["p1"].append(1.0 if hits[:1] and hits[0] else 0.0)
        out["hit1"].append(bool(hits[:1] and hits[0]))
        out["hit3"].append(any(hits[:3]))
        out[f"hit{k}"].append(any(hits[:k]))
        out["rr"].append(1.0 / first if first else 0.0)
        per_query.append({
            "id": q["id"], "kind": q["kind"], "first_hit": first,
            # Per-query scores, so the two arms can be paired by query id. The
            # aggregate means below cannot be paired after the fact.
            "hit_at_1": float(bool(hits[:1] and hits[0])),
            "hit_at_3": float(any(hits[:3])),
            f"hit_at_{k}": float(any(hits[:k])),
            "rr": 1.0 / first if first else 0.0,
        })
    return {
        "chunks": len(chunks),
        "precision_at_1": float(np.mean(out["p1"])),
        "hit_at_1": float(np.mean(out["hit1"])),
        "hit_at_3": float(np.mean(out["hit3"])),
        f"hit_at_{k}": float(np.mean(out[f"hit{k}"])),
        "mrr": float(np.mean(out["rr"])),
        "per_query": per_query,
    }


def main() -> int:
    k = 5
    spec = json.loads(QUERY_PATH.read_text())
    queries = spec["queries"]

    arms = {"legacy": {"chunks": 0, "acc": []}, "rows": {"chunks": 0, "acc": []}}
    results: dict[str, list] = {"legacy": [], "rows": []}

    for stem in sorted({q["tender"] for q in queries}):
        path = NOTIF_DIR / f"{stem}.pdf"
        document = parse_document(path, DocumentKind.NOTIFICATION)
        subset = [q for q in queries if q["tender"] == stem]
        for arm, builder in (("legacy", legacy_chunks), ("rows", chunk_document)):
            chunks = builder(document)
            arms[arm]["chunks"] += len(chunks)
            r = score(chunks, subset, k)
            results[arm].append((stem, r))
            print(f"  {stem:24} {arm:7} {len(chunks):5} chunks  "
                  f"hit@1={r['hit_at_1']*100:5.1f}%  hit@{k}={r[f'hit_at_{k}']*100:5.1f}%  "
                  f"MRR={r['mrr']:.3f}")

    print("\n" + "=" * 86)
    print(f"{'arm':8} {'chunks':>7} {'P@1':>7} {'hit@1':>7} {'hit@3':>7} {'hit@'+str(k):>7} {'MRR':>7}")
    print("-" * 86)
    summary = {}
    n = len(queries)
    for arm in ("legacy", "rows"):
        agg = {key: 0.0 for key in ("precision_at_1", "hit_at_1", "hit_at_3", f"hit_at_{k}", "mrr")}
        for stem, r in results[arm]:
            weight = len([q for q in queries if q["tender"] == stem])
            for key in agg:
                agg[key] += r[key] * weight
        for key in agg:
            agg[key] /= n
        summary[arm] = {**agg, "chunks": arms[arm]["chunks"]}
        print(f"{arm:8} {arms[arm]['chunks']:7} "
              f"{agg['precision_at_1']*100:6.1f}% {agg['hit_at_1']*100:6.1f}% "
              f"{agg['hit_at_3']*100:6.1f}% {agg[f'hit_at_{k}']*100:6.1f}% {agg['mrr']:7.3f}")

    print("\nDelta attributable to table-row chunking alone (same labels, same model):")
    for key, label in (("hit_at_1", "hit@1"), ("hit_at_3", "hit@3"),
                       (f"hit_at_{k}", f"hit@{k}"), ("mrr", "MRR")):
        a, b = summary["legacy"][key], summary["rows"][key]
        scale = 1 if key == "mrr" else 100
        print(f"  {label:7} {a*scale:6.3f} -> {b*scale:6.3f}   ({'+' if b>=a else ''}{(b-a)*scale:.3f})")

    # ----------------------------------------------------------------- #
    # Significance. The deltas above are point estimates on n = 17..39
    # queries, where a 6-0 sweep clears 0.05 and a 5-0 sweep does not. Both
    # arms are scored on the SAME queries, so the comparison is paired: only
    # the queries the arms disagree on carry information.
    # ----------------------------------------------------------------- #
    paired = {
        arm: {row["id"]: row for stem, r in results[arm] for row in r["per_query"]}
        for arm in ("legacy", "rows")
    }
    shared = [q["id"] for q in queries if q["id"] in paired["legacy"]
              and q["id"] in paired["rows"]]
    if len(shared) != n:
        print(f"\n!! paired on {len(shared)} of {n} queries; "
              f"significance covers only those")

    print("\nSignificance of the same comparison (paired, exact):")
    for key, label in (("hit_at_1", "hit@1"), ("hit_at_3", "hit@3"),
                       (f"hit_at_{k}", f"hit@{k}")):
        before = [paired["legacy"][i][key] for i in shared]
        after = [paired["rows"][i][key] for i in shared]
        improved, regressed, tied = paired_counts(before, after)
        print(f"  {label:7} {fmt_sign_test(improved, regressed, tied)}")

    rr_deltas = [paired["rows"][i]["rr"] - paired["legacy"][i]["rr"] for i in shared]
    print(f"  {'MRR':7} {fmt_delta_ci(rr_deltas)}")

    summary["significance"] = {
        "n_paired": len(shared),
        "method": "exact two-sided sign test (hit@k); "
                  "percentile bootstrap, 10000 resamples, seed 20260907 (MRR)",
        "hit_at_1": paired_counts([paired["legacy"][i]["hit_at_1"] for i in shared],
                                  [paired["rows"][i]["hit_at_1"] for i in shared]),
        f"hit_at_{k}": paired_counts([paired["legacy"][i][f"hit_at_{k}"] for i in shared],
                                     [paired["rows"][i][f"hit_at_{k}"] for i in shared]),
        "mrr_delta": fmt_delta_ci(rr_deltas),
    }

    print(f"\nIndex cost: {summary['legacy']['chunks']} -> {summary['rows']['chunks']} chunks "
          f"({summary['rows']['chunks']/max(1,summary['legacy']['chunks']):.2f}x)")
    print(f"n = {n} labelled queries over 4 real notifications. Small; the "
          f"paired\ntests above say which differences survive that.")
    Path("/tmp/ablation_chunking.json").write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
