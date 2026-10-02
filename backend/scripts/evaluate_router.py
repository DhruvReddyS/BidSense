"""Deterministic intent-router accuracy (Scope Sections 9.3 and 10).

Reports DEV and HELD-OUT separately. The router's vocabulary was widened
against the dev split, so the dev figure is a fitting score and only the
held-out figure is evidence of anything. A single blended number would hide
that distinction, which is the whole reason the earlier twelve-query set
reported 100%: every query in it contained a trigger word it had been built
around.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.review.workflow import classify_query


def main() -> int:
    rows = json.loads((Path(__file__).parents[2] / "data" / "router_queries.json").read_text())
    for row in rows:
        row["predicted"] = classify_query(row["question"])
        row["ok"] = row["predicted"] == row["route"]

    for split in ("dev", "test"):
        subset = [r for r in rows if r.get("split", "dev") == split]
        if not subset:
            continue
        correct = sum(r["ok"] for r in subset)
        label = "DEV (fitted -- not evidence)" if split == "dev" else "HELD OUT"
        print(f"\n{label}: {correct}/{len(subset)} = {correct / len(subset) * 100:.1f}%")
        per_route = Counter(r["route"] for r in subset)
        per_ok = Counter(r["route"] for r in subset if r["ok"])
        for route in sorted(per_route):
            print(f"    {route:12} {per_ok[route]}/{per_route[route]}")
        for r in subset:
            if not r["ok"]:
                print(f"    MISS want {r['route']:12} got {r['predicted']:12} {r['question']!r}")

    overall = sum(r["ok"] for r in rows)
    print(f"\nAll {len(rows)} queries: {overall}/{len(rows)} = {overall / len(rows) * 100:.1f}%")
    print("Quote the HELD-OUT figure. The dev figure measures fitting, not accuracy.")
    held = [r for r in rows if r.get("split") == "test"]
    return 0 if not held or sum(r["ok"] for r in held) / len(held) >= 0.7 else 1


if __name__ == "__main__":
    raise SystemExit(main())
