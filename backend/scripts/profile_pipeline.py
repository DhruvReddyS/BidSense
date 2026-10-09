"""Time each ingestion stage, so optimisation targets what is actually slow.

Written because "make it faster" without a profile is guesswork, and this
pipeline has three plausible-sounding bottlenecks that measurement separates:
PDF text extraction, table extraction, and chunking. Only one of them dominates,
and it is not the one the code spends the most lines on.

Runs on a generated fixture by default, so it needs no corpus and no network.
Point it at a real notification with --pdf to profile the document that matters.

  python -m scripts.profile_pipeline                      # generated fixture
  python -m scripts.profile_pipeline --pdf ../data/notifications/NOTIF_supply_01.pdf
  python -m scripts.profile_pipeline --repeat 5 --json /tmp/profile.json

Embedding is profiled only when the BGE weights are already loadable; it is
otherwise reported as skipped rather than silently omitted.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingest.chunking import chunk_document            # noqa: E402
from app.ingest.loader import parse_document              # noqa: E402
from app.schemas.common import DocumentKind               # noqa: E402


def timed(label: str, fn, repeat: int) -> dict:
    """Run `fn` `repeat` times and report the spread, not just one number."""
    samples = []
    result = None
    for _ in range(repeat):
        start = time.perf_counter()
        result = fn()
        samples.append((time.perf_counter() - start) * 1000)
    return {
        "stage": label,
        "ms_median": round(statistics.median(samples), 1),
        "ms_min": round(min(samples), 1),
        "ms_max": round(max(samples), 1),
        "runs": repeat,
        "_result": result,
    }


def fixture_pdf(into: Path) -> Path:
    """A generated notification, so the profile runs with no corpus present."""
    from tests.doc_factory import make_notification_pdf

    return make_notification_pdf(into)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, help="profile this document instead")
    parser.add_argument("--repeat", type=int, default=3,
                        help="runs per stage (default 3; the median is reported)")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    import tempfile
    temporary = Path(tempfile.mkdtemp(prefix="bidsense-profile-"))
    path = args.pdf or fixture_pdf(temporary)
    if not path.exists():
        print(f"No such document: {path}", file=sys.stderr)
        return 1

    size_kb = path.stat().st_size / 1024
    print(f"Profiling {path.name}  ({size_kb:.0f}KB, {args.repeat} run(s) per stage)\n")

    rows = []

    parse = timed("parse (text + tables)",
                  lambda: parse_document(path, DocumentKind.NOTIFICATION),
                  args.repeat)
    document = parse.pop("_result")
    rows.append(parse)

    pages = len(getattr(document, "pages", []) or [])
    tables = sum(len(getattr(p, "tables", []) or []) for p in (document.pages or []))
    characters = sum(len(getattr(p, "text", "") or "") for p in (document.pages or []))

    chunks_row = timed("chunk (rows + prose)",
                       lambda: chunk_document(document), args.repeat)
    chunks = chunks_row.pop("_result")
    rows.append(chunks_row)

    embed_row = None
    try:
        from app.vector.embeddings import embed_passages, get_model

        get_model()
        texts = [c.text for c in chunks]
        embed_row = timed(f"embed ({len(texts)} chunks)",
                          lambda: embed_passages(texts), 1)
        embed_row.pop("_result")
        rows.append(embed_row)
    except Exception as error:
        print(f"  (embedding not profiled: {type(error).__name__} -- "
              f"weights unavailable offline)\n")

    print(f"{'stage':26} {'median':>9} {'min':>9} {'max':>9}")
    print("-" * 56)
    for row in rows:
        print(f"{row['stage']:26} {row['ms_median']:8.1f}ms "
              f"{row['ms_min']:8.1f}ms {row['ms_max']:8.1f}ms")

    total = sum(r["ms_median"] for r in rows)
    print("-" * 56)
    print(f"{'total':26} {total:8.1f}ms")

    print(f"\nDocument: {pages} page(s), {tables} table(s), "
          f"{characters:,} characters -> {len(chunks)} chunk(s)")
    if pages:
        print(f"Parse cost: {parse['ms_median'] / pages:.1f}ms/page "
              f"({parse['ms_median'] / max(1, total) * 100:.0f}% of the total)")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "document": {
                "name": path.name, "kb": round(size_kb, 1), "pages": pages,
                "tables": tables, "characters": characters,
                "chunks": len(chunks),
            },
            "stages": rows,
            "total_ms": round(total, 1),
        }, indent=2))
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
