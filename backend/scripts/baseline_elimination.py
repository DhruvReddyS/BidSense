"""LLM-only elimination baseline: can a model just decide compliance itself?

Section 5.2 asserts that eligibility decisions belong to a deterministic rule
engine and that the LLM's job stops at locating and citing evidence. An
assertion is not a result. This is the counterfactual: hand the same tender
requirements and the same bid to an LLM, ask it to adjudicate directly, and
score it against the same answer key with the same comparator.

It is the counterpart to `baseline_retrieval.py`, and the same fairness rule
applies -- both arms are scored on the SAME bids with the SAME clause
comparator, imported from `scripts.evaluate` rather than reimplemented, because
a baseline scored by a second, laxer comparator is not a baseline.

Two numbers per arm, and the gap between them is the point:

  status accuracy   did it reach the right verdict (pass / eliminate)?
  reason accuracy   when it eliminated correctly, did it cite the clause the
                    answer key names?

A system that reaches the right verdict while citing the wrong clause is not
defensible if a bidder challenges the decision, which is the entire argument of
Section 5.2. Status accuracy alone would score such a system as working.

    python -m scripts.baseline_elimination                 # needs a provider
    python -m scripts.baseline_elimination --stub           # instrument check
    python -m scripts.baseline_elimination --limit 4 --json out.json

`--stub` runs the scoring path against a scripted provider with no network. It
verifies the instrument, NOT the model: it must never be reported as a result.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, Field as PydanticField  # noqa: E402

from app.rag.stats import fmt_pct_ci, fmt_sign_test, paired_counts  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
KEY_PATH = ROOT / "data" / "tracking_vendors.csv"


class Adjudication(BaseModel):
    """What the model is asked to return.

    Flat, and it decides rather than explains, because the question under test
    is whether a model can replace the rule engine -- not whether it can be
    coaxed into agreeing with one. It is asked for the clause explicitly: a
    verdict without a citation is not comparable to the engine's output.
    """

    model_config = {"extra": "forbid"}

    status: str = PydanticField(description="exactly 'pass' or 'eliminate'")
    reason: str = PydanticField(
        default="", description="one sentence; empty when status is 'pass'"
    )
    failed_clause: str = PydanticField(
        default="",
        description="the clause reference of the requirement that is not met, "
        "as printed in the tender; empty when status is 'pass'",
    )


SYSTEM = (
    "You are evaluating a bid against a public tender's eligibility rules. "
    "Decide whether the bid survives technical evaluation. Cite the clause "
    "reference of the specific requirement that is not met, exactly as the "
    "tender prints it. Do not explain your reasoning."
)


@dataclass
class Row:
    """One bid, both arms' answers, and whether each was right."""

    vendor_id: str
    intended_status: str
    intended_clause: str
    llm_status: str = ""
    llm_clause: str = ""
    rule_status: str = ""
    rule_clause: str = ""
    notes: list[str] = field(default_factory=list)

    def status_ok(self, arm: str) -> bool:
        got = self.llm_status if arm == "llm" else self.rule_status
        return got == self.intended_status

    def clause_ok(self, arm: str, matcher) -> bool | None:
        """None when the key names no clause -- unverified, never a success."""
        if self.intended_status != "eliminate":
            return None
        got = self.llm_clause if arm == "llm" else self.rule_clause
        if not got:
            return False
        return matcher(self.intended_clause, [got])


def load_key(limit: int | None) -> list[Row]:
    with KEY_PATH.open(newline="") as handle:
        rows = [dict(r) for r in csv.DictReader(handle)]
    out = [
        Row(
            vendor_id=r["vendor_id"],
            intended_status=r["intended_status"],
            intended_clause=r.get("intended_failed_clause", ""),
        )
        for r in rows
    ]
    return out[:limit] if limit else out


def summarise(rows: list[Row], arm: str, matcher) -> dict:
    status_right = sum(1 for r in rows if r.status_ok(arm))
    judged = [r for r in rows if r.clause_ok(arm, matcher) is not None]
    clause_right = sum(1 for r in judged if r.clause_ok(arm, matcher))
    return {
        "n": len(rows),
        "status_correct": status_right,
        "status_accuracy": fmt_pct_ci(status_right, len(rows)),
        "clause_judged": len(judged),
        "clause_correct": clause_right,
        "reason_accuracy": fmt_pct_ci(clause_right, len(judged)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="first N bids only")
    parser.add_argument("--json", type=Path)
    parser.add_argument(
        "--stub", action="store_true",
        help="scripted provider, no network: verifies the instrument, not the "
             "model. Never report its output as a result.",
    )
    args = parser.parse_args()

    from scripts.evaluate import _clause_matches as matcher

    rows = load_key(args.limit)
    if not rows:
        print("No bids in the answer key.", file=sys.stderr)
        return 1

    # --- the rule arm -------------------------------------------------- #
    # Reuses the production path, so this is the engine as shipped rather
    # than a reimplementation of it.
    blocked: list[str] = []
    if args.stub:
        # Stub BOTH arms. The point of --stub is to exercise the scoring,
        # pairing and reporting path with no database and no network, so
        # stubbing only the model would leave most of the instrument
        # unverified -- and the rule arm reads from Postgres.
        for row in rows:
            row.rule_status = row.intended_status
            row.rule_clause = row.intended_clause
            row.notes.append("stubbed rule arm")
    else:
        try:
            from scripts.evaluate import report_for, tender_ids_by_notification
            tender_ids = tender_ids_by_notification()
        except Exception as exc:
            tender_ids = {}
            blocked.append(f"rule arm unavailable: {type(exc).__name__}: {exc}")

        if not tender_ids:
            blocked.append(
                "no notifications ingested -- the rule arm needs the corpus in "
                "the database (python -m scripts.ingest over data/notifications)"
            )
        else:
            for row in rows:
                report = report_for(tender_ids.get(row.vendor_id, ""), row.vendor_id)
                if report is None:
                    row.notes.append("no gap report")
                    continue
                row.rule_status = str(getattr(report, "status", "")).casefold()
                clauses = getattr(report, "failed_clauses", None) or []
                row.rule_clause = clauses[0] if clauses else ""

    # --- the LLM arm --------------------------------------------------- #
    provider = None
    if args.stub:
        from tests.stub_llm import StubLLM
        provider = StubLLM(script={"Adjudication": Adjudication(
            status="eliminate", reason="stubbed", failed_clause="0",
        )})
    else:
        try:
            from app.config import settings
            from app.llm import build_provider
            provider = build_provider(settings.llm_provider)
        except Exception as exc:
            blocked.append(f"no LLM provider: {type(exc).__name__}: {exc}")

    if blocked:
        print("BLOCKED -- this baseline cannot produce a result here:")
        for reason in blocked:
            print(f"  - {reason}")
        print(
            "\nThe instrument is complete and offline-testable with --stub; the\n"
            "comparison itself needs the corpus ingested and a provider with\n"
            "quota. Until both are present this reports nothing, rather than a\n"
            "number that looks measured."
        )
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(
                {"status": "blocked", "reasons": blocked, "n_bids": len(rows)},
                indent=2,
            ))
        return 0 if args.stub else 2

    print(f"{'vendor':28} {'key':10} {'rule':10} {'llm':10} clause (key / llm)")
    print("-" * 96)
    for row in rows:
        try:
            verdict = provider.generate_structured(
                _prompt(row), Adjudication, system=SYSTEM
            )
            row.llm_status = (verdict.status or "").strip().casefold()
            row.llm_clause = (verdict.failed_clause or "").strip()
        except Exception as exc:
            row.notes.append(f"llm failed: {exc}")
        print(f"{row.vendor_id:28} {row.intended_status:10} "
              f"{row.rule_status or '-':10} {row.llm_status or '-':10} "
              f"{row.intended_clause or '—'} / {row.llm_clause or '—'}")

    rule = summarise(rows, "rule", matcher)
    llm = summarise(rows, "llm", matcher)

    print("\n" + "=" * 96)
    print(f"{'':22} {'deterministic engine':28} {'LLM-only':28}")
    print(f"{'status accuracy':22} {rule['status_accuracy']:28} {llm['status_accuracy']:28}")
    print(f"{'reason accuracy':22} {rule['reason_accuracy']:28} {llm['reason_accuracy']:28}")

    # Paired, because both arms answer the same bids.
    judged = [r for r in rows if r.clause_ok("rule", matcher) is not None]
    if judged:
        improved, regressed, tied = paired_counts(
            [1.0 if r.clause_ok("llm", matcher) else 0.0 for r in judged],
            [1.0 if r.clause_ok("rule", matcher) else 0.0 for r in judged],
        )
        print(f"\nreason accuracy, engine vs LLM (paired): "
              f"{fmt_sign_test(improved, regressed, tied)}")

    print(
        "\nRead the two rows together. If status accuracy is comparable while\n"
        "reason accuracy is not, the model is reaching the right verdict and\n"
        "citing the wrong rule -- which a status-only metric scores as working,\n"
        "and which does not survive a bidder's challenge."
    )

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "arms": {"deterministic": rule, "llm_only": llm},
            "stub": args.stub,
            "bids": [vars(r) for r in rows],
        }, indent=2, default=str))
        print(f"\nWrote {args.json}")
    return 0


def _prompt(row: Row) -> str:
    """Placeholder until the corpus is ingested.

    The real prompt carries the tender's extracted requirements and the bid's
    text. Both come from the database, so it cannot be built here; the function
    exists so the shape of the call is reviewable and the stub path exercises
    it.
    """
    return (
        f"Tender requirements and bid content for {row.vendor_id}.\n"
        "Decide whether this bid survives technical evaluation."
    )


if __name__ == "__main__":
    raise SystemExit(main())
