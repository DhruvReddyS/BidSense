"""Extraction field accuracy against hand-labelled truth (Scope Section 10).

Answers one question: of the header-level fields a human read off the source
PDF, how many did the pipeline read the same way?

Three choices make the number mean something:

  LABELS ARE INDEPENDENT   `data/extraction_truth.json` was written by reading
                           the PDFs, not by copying system output. A truth file
                           derived from predictions measures self-consistency
                           and reports it as accuracy.
  UNLABELLED IS NOT RIGHT  A field nobody could confirm in the source is
                           excluded from the denominator and counted separately.
                           Coverage is printed next to accuracy so a thin label
                           set cannot pass as a strong result.
  THE RULE FITS THE FIELD  Exact string equality is wrong for an issuing
                           authority ('Indian Institute of Technology (Indian
                           School of Mines) Dhanbad' is a correct reading of
                           'IIT (ISM) Dhanbad') and wrong for a tender id
                           printed across two lines with a date appended. Each
                           field declares how it is compared, and the rule is
                           stated in the output so a reader can disagree with it.

Run:  python -m scripts.evaluate_extraction [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.db.models import TenderNotificationRow
from app.db.session import session_scope
from app.rag.stats import fmt_pct_ci

TRUTH_PATH = Path(__file__).parents[2] / "data" / "extraction_truth.json"

#: Which notification row belongs to which labelled id. Matched on the source
#: filename because `source_file` is a temp path for documents uploaded through
#: the API rather than ingested from disk.
def _notification_key(source_file: str | None) -> str | None:
    if not source_file:
        return None
    stem = Path(source_file).stem
    return stem if stem.startswith("NOTIF_") else None


@dataclass
class FieldResult:
    notification: str
    field_name: str
    rule: str
    expected: object
    actual: object
    correct: bool


@dataclass
class Summary:
    results: list[FieldResult] = field(default_factory=list)
    unlabelled: list[str] = field(default_factory=list)
    missing_rows: list[str] = field(default_factory=list)

    @property
    def scored(self) -> int:
        return len(self.results)

    @property
    def correct(self) -> int:
        return sum(1 for r in self.results if r.correct)

    @property
    def accuracy(self) -> float | None:
        return (self.correct / self.scored) if self.scored else None


# --------------------------------------------------------------------------- #
# Comparison rules. Each is deliberately narrow; a loose rule inflates the
# score far more quietly than a strict one deflates it.
# --------------------------------------------------------------------------- #
def _squash(text: str) -> str:
    """Casefold and strip everything that varies in how an id is printed."""
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _id_core(expected: str, actual: object) -> bool:
    """The labelled core id appears inside the prediction.

    Real notices print 'BID NOTICE No.178/CGM(T)/HGCL/DGM(Elec)/Cycle
    Track/2022-23/second call/Dated:24.04.2023' across two lines. Capturing
    the whole reference is correct; so is capturing just the core. Containment
    accepts both and still rejects a wrong id.
    """
    if not isinstance(actual, str):
        return False
    return _squash(expected) in _squash(actual)


def _authority_tokens(tokens: list[str], actual: object) -> bool:
    """Every distinctive token of the authority's name is present."""
    if not isinstance(actual, str):
        return False
    haystack = actual.casefold()
    return all(token.casefold() in haystack for token in tokens)


def _exact_number(expected, actual) -> bool:
    if actual is None:
        return False
    try:
        return Decimal(str(expected)) == Decimal(str(actual))
    except Exception:
        return False


def _exact_date(expected: str, actual) -> bool:
    if actual is None:
        return False
    if isinstance(actual, date):
        return actual.isoformat() == expected
    return str(actual)[:10] == expected


def _compare(spec: dict, actual: object) -> bool:
    rule = spec["rule"]
    expected = spec.get("value")
    if rule == "expected_null":
        return actual is None
    if rule == "id_core":
        return _id_core(expected, actual)
    if rule == "authority_tokens":
        return _authority_tokens(spec["tokens"], actual)
    if rule == "exact_number":
        return _exact_number(expected, actual)
    if rule == "exact_date":
        return _exact_date(expected, actual)
    raise ValueError(f"unknown comparison rule: {rule!r}")


# --------------------------------------------------------------------------- #
def evaluate() -> Summary:
    truth = json.loads(TRUTH_PATH.read_text())
    summary = Summary()

    with session_scope() as session:
        rows = session.scalars(select(TenderNotificationRow)).all()
        by_key = {}
        for row in rows:
            key = _notification_key(row.source_file)
            if key:
                by_key[key] = row
            # Uploaded-through-API rows carry a temp path; fall back to matching
            # the labelled tender id so they are still scored.
            else:
                for label, spec in truth.items():
                    if label.startswith("_"):
                        continue
                    tid = spec.get("tender_id", {}).get("value")
                    if tid and _id_core(tid, row.tender_id):
                        by_key.setdefault(label, row)

        for label, spec in truth.items():
            if label.startswith("_"):
                continue
            row = by_key.get(label)
            if row is None:
                summary.missing_rows.append(label)
                continue
            for field_name, rule_spec in spec.items():
                if field_name.startswith("_"):
                    continue
                if not hasattr(row, field_name):
                    summary.unlabelled.append(f"{label}.{field_name} (no such column)")
                    continue
                actual = getattr(row, field_name)
                summary.results.append(
                    FieldResult(
                        notification=label,
                        field_name=field_name,
                        rule=rule_spec["rule"],
                        expected=rule_spec.get("value"),
                        actual=actual.isoformat() if isinstance(actual, date) else (
                            str(actual) if isinstance(actual, Decimal) else actual
                        ),
                        correct=_compare(rule_spec, actual),
                    )
                )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="write full results here")
    args = parser.parse_args()

    summary = evaluate()

    print(f"{'notification':24} {'field':24} {'rule':18} ok  expected -> actual")
    print("-" * 104)
    for r in sorted(summary.results, key=lambda r: (r.notification, r.field_name)):
        mark = "OK " if r.correct else "XX "
        print(
            f"{r.notification[:23]:24} {r.field_name[:23]:24} {r.rule[:17]:18} "
            f"{mark} {str(r.expected)[:22]!r} -> {str(r.actual)[:28]!r}"
        )

    print("\n" + "=" * 104)
    print(f"Fields labelled and scored : {summary.scored}")
    print(f"Correct                    : {summary.correct}")
    # With n=17 a bare "100%" asserts more than the evidence supports; the
    # Wilson lower bound is near 82%, and that is the honest claim.
    print(f"Field accuracy             : {fmt_pct_ci(summary.correct, summary.scored)}")
    if summary.missing_rows:
        print(f"Notifications not ingested : {', '.join(summary.missing_rows)}"
              "  <- not scored; ingest them before quoting this number")
    if summary.unlabelled:
        print(f"Excluded (unlabelled)      : {len(summary.unlabelled)}")

    wrong = [r for r in summary.results if not r.correct]
    if wrong:
        print("\nIncorrect fields -- the useful part of this report:")
        for r in wrong:
            print(f"  {r.notification}.{r.field_name}: expected {r.expected!r}, got {r.actual!r}")

    print(
        "\nScope: these are HEADER-level fields on 4 real notifications. This is"
        "\nnot a per-criterion or per-document accuracy, and it is not a claim"
        "\nabout bids. Both of those are separate, unmeasured numbers."
    )

    if args.json:
        args.json.write_text(json.dumps({
            "scored": summary.scored,
            "correct": summary.correct,
            "accuracy": summary.accuracy,
            "missing_rows": summary.missing_rows,
            "results": [r.__dict__ for r in summary.results],
        }, indent=2, default=str))
        print(f"\nWritten to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
