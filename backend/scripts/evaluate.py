"""Measure the pipeline against the answer key (Section 10).

Compares what the system concluded about each vendor with what
`data/tracking_vendors.csv` says should have happened, and reports:

  * elimination precision / recall -- did we eliminate exactly the vendors we
    deliberately made non-compliant?
  * reason accuracy -- when we eliminated correctly, did we cite the right
    clause, or the right clause among several failures?
  * latency -- per-document extraction time.

The distinction between "eliminated for the right reason" and "eliminated" is
the one that matters. A rule engine that rejects everybody scores perfect recall
and is useless; one that rejects the right vendor for the wrong clause is not
defensible if challenged, which is the whole point of Section 5.2.

    python -m scripts.evaluate
    python -m scripts.evaluate --tender NOTIF_supply_01 --json out.json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.compliance.gap import build_gap_report  # noqa: E402
from app.compliance.models import GapReport  # noqa: E402
from app.db.repository import (  # noqa: E402
    get_notification_row,
    get_submission_row,
    list_notifications,
    to_notification_schema,
    to_submission_schema,
)
from app.db.session import session_scope  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")


@dataclass
class VendorResult:
    vendor_id: str
    notification_id: str
    intended_status: str
    intended_clause: str
    predicted_verdict: str
    predicted_eliminated: bool
    blocking_clauses: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)
    outcome: str = ""          # TP | TN | FP | FN
    clause_matched: bool | None = None
    note: str = ""


def load_ground_truth(path: Path) -> dict[str, dict]:
    with path.open() as handle:
        return {row["vendor_id"]: row for row in csv.DictReader(handle)}


def report_for(tender_id: str, vendor_id: str) -> GapReport | None:
    with session_scope() as session:
        notification_row = get_notification_row(session, tender_id)
        submission_row = get_submission_row(session, tender_id, vendor_id)
        if notification_row is None or submission_row is None:
            return None
        return build_gap_report(
            to_notification_schema(notification_row),
            to_submission_schema(submission_row),
        )


def tender_ids_by_notification() -> dict[str, str]:
    """Map the notification_id used in the answer key to the extracted tender_id."""
    mapping: dict[str, str] = {}
    with session_scope() as session:
        for row in list_notifications(session, limit=200):
            if not row.source_file:
                continue
            mapping[Path(row.source_file).stem] = row.tender_id
    return mapping


def _clause_matches(expected: str, actual: list[str]) -> bool:
    """Loose match: extracted clause labels carry the surrounding heading text."""
    if not expected or expected == "—":
        return True                     # no specific clause was asserted
    expected = expected.strip().lower()
    return any(expected in (a or "").strip().lower() for a in actual)


def evaluate(truth: dict[str, dict], only: str | None) -> list[VendorResult]:
    tender_map = tender_ids_by_notification()
    results: list[VendorResult] = []

    for vendor_id, row in truth.items():
        notification_id = row["notification_id"]
        if only and notification_id != only:
            continue

        tender_id = tender_map.get(notification_id)
        if tender_id is None:
            results.append(
                VendorResult(
                    vendor_id=vendor_id,
                    notification_id=notification_id,
                    intended_status=row["intended_status"],
                    intended_clause=row["intended_failed_clause"],
                    predicted_verdict="—",
                    predicted_eliminated=False,
                    outcome="SKIP",
                    note="notification not ingested",
                )
            )
            continue

        report = report_for(tender_id, vendor_id)
        if report is None:
            results.append(
                VendorResult(
                    vendor_id=vendor_id,
                    notification_id=notification_id,
                    intended_status=row["intended_status"],
                    intended_clause=row["intended_failed_clause"],
                    predicted_verdict="—",
                    predicted_eliminated=False,
                    outcome="SKIP",
                    note="bid not ingested",
                )
            )
            continue

        blocking = report.blocking_items
        eliminated = bool(blocking)
        should_eliminate = row["intended_status"] == "eliminate"

        outcome = (
            "TP" if eliminated and should_eliminate
            else "TN" if not eliminated and not should_eliminate
            else "FP" if eliminated and not should_eliminate
            else "FN"
        )

        clauses = [
            (item.notification_provenance.clause_ref if item.notification_provenance else "")
            for item in blocking
        ]
        results.append(
            VendorResult(
                vendor_id=vendor_id,
                notification_id=notification_id,
                intended_status=row["intended_status"],
                intended_clause=row["intended_failed_clause"],
                predicted_verdict=report.verdict,
                predicted_eliminated=eliminated,
                blocking_clauses=[c for c in clauses if c][:6],
                blocking_reasons=[i.requirement[:60] for i in blocking][:4],
                outcome=outcome,
                clause_matched=(
                    _clause_matches(row["intended_failed_clause"], clauses)
                    if outcome == "TP"
                    else None
                ),
            )
        )
    return results


def summarise(results: list[VendorResult]) -> dict:
    scored = [r for r in results if r.outcome != "SKIP"]
    tp = sum(1 for r in scored if r.outcome == "TP")
    tn = sum(1 for r in scored if r.outcome == "TN")
    fp = sum(1 for r in scored if r.outcome == "FP")
    fn = sum(1 for r in scored if r.outcome == "FN")

    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision and recall
        else None
    )
    correct_clause = [r for r in scored if r.outcome == "TP" and r.clause_matched]
    return {
        "evaluated": len(scored),
        "skipped": len(results) - len(scored),
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": (tp + tn) / len(scored) if scored else None,
        # The number that actually matters for defensibility: eliminated, AND
        # for the clause the answer key says.
        "reason_accuracy": (len(correct_clause) / tp) if tp else None,
    }


def _pct(value) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate against the answer key")
    parser.add_argument("--truth", default="../data/tracking_vendors.csv")
    parser.add_argument("--tender", help="limit to one notification_id")
    parser.add_argument("--json", help="write the full result set here")
    args = parser.parse_args()

    truth = load_ground_truth(Path(args.truth))
    results = evaluate(truth, args.tender)
    summary = summarise(results)

    print(f"{'vendor':28} {'intended':10} {'predicted':15} {'outcome':8} clause")
    print("-" * 96)
    for r in sorted(results, key=lambda x: (x.notification_id, x.vendor_id)):
        mark = {"TP": "OK", "TN": "OK", "FP": "WRONG", "FN": "MISS", "SKIP": "-"}[r.outcome]
        clause = (
            ("cited " + ", ".join(r.blocking_clauses[:2])) if r.blocking_clauses else ""
        )
        if r.outcome == "TP":
            clause = ("right clause" if r.clause_matched else "WRONG CLAUSE") + " — " + clause
        print(
            f"{r.vendor_id:28} {r.intended_status:10} {r.predicted_verdict:15} "
            f"{mark:8} {clause[:44]}"
        )
        if r.note:
            print(f"{'':28} ({r.note})")

    print("\n" + "=" * 96)
    print(f"Evaluated {summary['evaluated']} vendors ({summary['skipped']} skipped)")
    print(f"  TP {summary['tp']}   TN {summary['tn']}   FP {summary['fp']}   FN {summary['fn']}")
    print(f"  Elimination precision : {_pct(summary['precision'])}"
          "   (of those we eliminated, how many should have been)")
    print(f"  Elimination recall    : {_pct(summary['recall'])}"
          "   (of those that should be eliminated, how many were)")
    print(f"  F1                    : {_pct(summary['f1'])}")
    print(f"  Accuracy              : {_pct(summary['accuracy'])}")
    print(f"  Reason accuracy       : {_pct(summary['reason_accuracy'])}"
          "   (eliminated for the clause the key names)")

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {"summary": summary, "results": [asdict(r) for r in results]}, indent=2
            )
        )
        print(f"\nFull results written to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
