"""Prepare and score an independent second annotation pass (Section 10).

Why this is a script and not a result. Every accuracy figure in this project is
measured against hand-written labels, so "how reliable are the labels?" is part
of the method, and the answer is Cohen's kappa between two annotators. Kappa
needs the second annotator to be a *different person*: a second pass by whoever
wrote the labels reproduces their own reading of an ambiguous clause and reports
that consistency as reliability. The assistant that generated these labels
cannot be the second rater on its own work either, for exactly the same reason.

So this script does the part that can be automated -- pull the units, strip the
tells, hand over a sheet, and score it when it comes back -- and leaves the
judgement to a human who has not seen the answer key.

  # 1. produce a blinded sheet (about an hour of work for either dimension)
  python -m scripts.double_label --emit ground  --out /tmp/sheet_ground.csv
  python -m scripts.double_label --emit kind    --out /tmp/sheet_kind.csv

  # 2. the annotator fills the `label` column, following ANNOTATION_PROTOCOL.md

  # 3. score it
  python -m scripts.double_label --score ground --sheet /tmp/sheet_ground.csv

Blinding matters here. `intended_reason` for a document-ground elimination
literally reads "... not enclosed", which hands over the answer, so the sheet
carries only what a genuine annotator would work from: the ids, the file to
open, and for queries the question text.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from app.rag.stats import cohen_kappa, fmt_kappa, kappa_band

ROOT = Path(__file__).resolve().parents[2]
KEY_PATH = ROOT / "data" / "tracking_vendors.csv"
QUERY_PATH = ROOT / "data" / "rag_queries.json"
PROTOCOL = ROOT / "data" / "ANNOTATION_PROTOCOL.md"

#: dimension -> (allowed labels, what the annotator is deciding)
DIMENSIONS = {
    "ground": (
        ("criteria", "document"),
        "Why this bid is eliminated: a qualification condition it fails on the "
        "numbers, or a mandatory enclosure it never provided.",
    ),
    "status": (
        ("pass", "eliminate"),
        "Whether this bid should survive technical evaluation at all.",
    ),
    # Derived from the query set rather than hardcoded: the taxonomy grows as
    # the query set does, and a stale literal here would reject a valid label.
    "kind": (
        (),
        "What the question is asking for, which decides what retrieval has to "
        "do to answer it.",
    ),
}


def allowed_labels(dimension: str) -> tuple[str, ...]:
    literal, _ = DIMENSIONS[dimension]
    if literal:
        return literal
    spec = json.loads(QUERY_PATH.read_text())
    return tuple(sorted({q["kind"] for q in spec["queries"]}))


def vendor_units(dimension: str) -> list[dict[str, str]]:
    """Blinded units from the answer key."""
    with KEY_PATH.open(newline="") as handle:
        rows = [dict(r) for r in csv.DictReader(handle)]
    units = []
    for row in rows:
        # The ground of an elimination only exists for eliminated bids, so
        # labelling a passing bid's ground is a meaningless task.
        if dimension == "ground" and row["intended_status"] != "eliminate":
            continue
        units.append({
            "id": row["vendor_id"],
            "notification_id": row["notification_id"],
            "open_this": row["file_name"],
            "label": "",
        })
    return units


def query_units(dimension: str) -> list[dict[str, str]]:
    del dimension
    spec = json.loads(QUERY_PATH.read_text())
    return [
        {
            "id": str(q["id"]),
            "notification_id": q["tender"],
            "open_this": f"{q['tender']}.pdf",
            "question": q["question"],
            "label": "",
        }
        for q in spec["queries"]
    ]


def committed_labels(dimension: str) -> dict[str, str]:
    """The labels already in the repository -- rater A."""
    if dimension in ("ground", "status"):
        column = f"intended_{dimension}"
        with KEY_PATH.open(newline="") as handle:
            return {
                r["vendor_id"]: r[column]
                for r in csv.DictReader(handle)
                if not (dimension == "ground" and r["intended_status"] != "eliminate")
            }
    spec = json.loads(QUERY_PATH.read_text())
    return {str(q["id"]): q["kind"] for q in spec["queries"]}


def emit(dimension: str, out: Path) -> int:
    labels, question = allowed_labels(dimension), DIMENSIONS[dimension][1]
    units = (
        query_units(dimension) if dimension == "kind" else vendor_units(dimension)
    )
    fieldnames = list(units[0].keys())
    with out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(units)

    print(f"{out}  —  {len(units)} units, `label` left blank")
    print(f"\nDecide, for each row: {question}")
    print(f"Allowed labels: {', '.join(labels)}")
    print(f"\nProtocol: {PROTOCOL.relative_to(ROOT)}")
    print(
        "\nThe sheet deliberately omits the recorded label and the reason text,"
        "\nso work from the document itself. Do not open tracking_vendors.csv"
        "\nor rag_queries.json first -- seeing the existing label is what makes"
        "\nthe second pass worthless."
    )
    return 0


def score(dimension: str, sheet: Path) -> int:
    allowed = allowed_labels(dimension)
    with sheet.open(newline="") as handle:
        returned = {r["id"]: (r.get("label") or "").strip() for r in csv.DictReader(handle)}

    mine = committed_labels(dimension)
    blank = [uid for uid, label in returned.items() if not label]
    bad = sorted({label for label in returned.values() if label and label not in allowed})
    missing = sorted(set(mine) - set(returned))

    if bad:
        print(f"!! labels outside {allowed}: {bad}", file=sys.stderr)
        return 1
    if blank:
        print(f"!! {len(blank)} row(s) unlabelled: {blank[:8]}"
              f"{' ...' if len(blank) > 8 else ''}", file=sys.stderr)
        return 1
    if missing:
        print(f"!! {len(missing)} unit(s) absent from the sheet: {missing[:8]}",
              file=sys.stderr)
        return 1

    shared = [uid for uid in mine if uid in returned]
    rater_a = [mine[uid] for uid in shared]
    rater_b = [returned[uid] for uid in shared]

    print(f"Inter-annotator agreement on `{dimension}`")
    print("=" * 70)
    print(f"  {fmt_kappa(rater_a, rater_b)}")
    print(f"  band: {kappa_band(cohen_kappa(rater_a, rater_b))}")

    disagreements = [
        (uid, mine[uid], returned[uid]) for uid in shared if mine[uid] != returned[uid]
    ]
    if disagreements:
        print(f"\n  {len(disagreements)} disagreement(s) to adjudicate:")
        print(f"  {'unit':30} {'repository':12} {'annotator':12}")
        for uid, a, b in disagreements:
            print(f"  {uid:30} {a:12} {b:12}")
        print("\n  Adjudicate each one and, where the annotator is right, fix the"
              "\n  label in the repository. A disagreement left unexplained is a"
              "\n  label the paper cannot defend.")
    else:
        print("\n  No disagreements. With a small n that is a weak result rather"
              "\n  than a strong one -- report kappa with its n, not on its own.")

    print(f"\n  Per-category counts (repository / annotator):")
    for label in allowed:
        print(f"    {label:12} {rater_a.count(label):3} / {rater_b.count(label):3}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", choices=sorted(DIMENSIONS))
    parser.add_argument("--score", choices=sorted(DIMENSIONS))
    parser.add_argument("--out", type=Path, help="where to write the sheet")
    parser.add_argument("--sheet", type=Path, help="the completed sheet to score")
    args = parser.parse_args()

    if args.emit:
        if not args.out:
            parser.error("--emit needs --out")
        return emit(args.emit, args.out)
    if args.score:
        if not args.sheet:
            parser.error("--score needs --sheet")
        if not args.sheet.exists():
            parser.error(f"no such sheet: {args.sheet}")
        return score(args.score, args.sheet)
    parser.error("one of --emit or --score is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
