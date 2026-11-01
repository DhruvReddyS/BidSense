"""LLM-only elimination, as the baseline the rule engine must beat.

Section 5.2 forbids LLM judgement at elimination time and gives the reason:
determinism, explainability, defensibility on challenge. That is an argument,
not a measurement. This supplies the measurement by doing the thing the scope
rules out -- handing a model the tender's criteria and the bid's extracted facts
and asking it to decide -- and scoring it against the same answer key, on the
same bids, with the same metrics.

WHAT THIS IS AND IS NOT. It is not a strawman: the model is given exactly the
structured facts the rule engine uses, so the comparison isolates the DECISION
rather than the extraction. It does not re-read the PDFs, because then a loss
would be attributable to retrieval rather than to judgement.

WHY REASON ACCURACY IS THE INTERESTING COLUMN. Both arms can plausibly get
`eliminated` right. The defensible-on-challenge claim is about WHY: the rule
engine cites the clause whose threshold the bid misses, by construction. A model
asked for a clause can produce a plausible one it did not use. Section 5.2's
argument stands or falls there, not on accuracy.

Run:  python -m scripts.baseline_llm_elimination [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from pydantic import BaseModel, Field

from app.llm import get_llm
from app.rag.stats import fmt_pct_ci, fmt_test, mcnemar
from scripts.evaluate import (
    _evidence_matches,
    report_for,
    tender_ids_by_notification,
)

TRACKING = Path(__file__).parents[2] / "data" / "tracking_vendors.csv"

SYSTEM = (
    "You are evaluating a bid against a public tender's mandatory eligibility "
    "criteria. Decide only from the facts given. Do not infer, do not assume "
    "industry norms, and do not be generous: a mandatory requirement that the "
    "facts do not satisfy is a failure."
)


class LLMVerdict(BaseModel):
    eliminated: bool = Field(description="True if the bid fails a mandatory requirement.")
    clause_ref: str = Field(description="The clause reference that fails, or '' if none.")
    reason: str = Field(description="One sentence naming the failing requirement and value.")


def _facts(report) -> str:
    """The same structured facts the rule engine sees, as prose for the model."""
    lines = []
    for item in report.items:
        lines.append(
            f"- clause {item.notification_provenance.clause_ref if item.notification_provenance else '?'}"
            f" | {item.kind.value} | required: {item.required_value or '-'}"
            f" | found in bid: {item.found_value or 'not found'}"
        )
    return "\n".join(lines[:120])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    rows = list(csv.DictReader(TRACKING.open()))
    if args.limit:
        rows = rows[: args.limit]
    tenders = tender_ids_by_notification()
    llm = get_llm()

    records = []
    for row in rows:
        vendor_id = row["vendor_id"]
        report = report_for(tenders.get(row["notification_id"]), vendor_id)
        if report is None:
            continue
        should = row["intended_status"] == "eliminate"

        # Rule engine, as shipped.
        rule_eliminated = bool(report.blocking_items)
        rule_clauses = [
            (i.notification_provenance.clause_ref if i.notification_provenance else "")
            for i in report.blocking_items
        ]
        rule_reason_ok = (
            _evidence_matches(
                row["intended_failed_clause"], rule_clauses,
                [i.requirement for i in report.blocking_items],
            ) is True
            if rule_eliminated and should else None
        )

        # LLM, given the same facts.
        prompt = (
            f"Tender: {report.tender_id}\nBidder: {vendor_id}\n\n"
            f"Requirement-by-requirement facts:\n{_facts(report)}\n\n"
            "Decide whether this bid must be eliminated."
        )
        try:
            verdict = llm.generate_structured(prompt, LLMVerdict, system=SYSTEM)
            llm_eliminated, llm_clause, llm_reason = (
                verdict.eliminated, verdict.clause_ref, verdict.reason
            )
            error = ""
        except Exception as exc:
            llm_eliminated, llm_clause, llm_reason = None, "", ""
            error = f"{type(exc).__name__}: {exc}"[:140]

        llm_reason_ok = (
            _evidence_matches(row["intended_failed_clause"], [llm_clause], [llm_reason]) is True
            if llm_eliminated and should else None
        )

        records.append({
            "vendor_id": vendor_id, "should_eliminate": should,
            "rule_eliminated": rule_eliminated, "rule_reason_ok": rule_reason_ok,
            "llm_eliminated": llm_eliminated, "llm_clause": llm_clause,
            "llm_reason": llm_reason, "llm_reason_ok": llm_reason_ok,
            "error": error,
        })
        mark = "ERR" if error else ("OK " if llm_eliminated == should else "XX ")
        print(f"  {mark} {vendor_id:26} should={str(should):5} "
              f"rule={str(rule_eliminated):5} llm={str(llm_eliminated):5} "
              f"{(error or llm_clause)[:30]}")

    usable = [r for r in records if r["llm_eliminated"] is not None]
    if not usable:
        print("\nNo LLM verdicts were obtained; nothing to compare.")
        for r in records[:3]:
            print("  ", r["error"])
        return 1

    def correct(arm: str) -> list[bool]:
        return [r[f"{arm}_eliminated"] == r["should_eliminate"] for r in usable]

    print("\n" + "=" * 78)
    print(f"Comparable vendors: {len(usable)} of {len(records)}"
          + (f"  ({len(records) - len(usable)} LLM errors)" if len(usable) != len(records) else ""))
    for arm, label in (("rule", "rule engine"), ("llm", "LLM-only")):
        hits = correct(arm)
        print(f"  {label:12} status accuracy : {fmt_pct_ci(sum(hits), len(hits))}")

    for arm, label in (("rule", "rule engine"), ("llm", "LLM-only")):
        judged = [r for r in usable if r[f"{arm}_reason_ok"] is not None]
        if judged:
            ok = sum(1 for r in judged if r[f"{arm}_reason_ok"])
            print(f"  {label:12} reason accuracy : {fmt_pct_ci(ok, len(judged))}"
                  "   <- cites the clause the key names")

    print("\nPaired on the same bids:")
    print("  " + fmt_test("status accuracy (exact McNemar)",
                          mcnemar(correct("llm"), correct("rule"))))

    print(
        "\nThe model received the SAME structured facts the rule engine uses, so"
        "\nthis isolates the decision rather than the extraction. Section 5.2's"
        "\nargument for determinism is about WHY a bid was eliminated, which is"
        "\nthe reason-accuracy row, not the status row."
    )
    if args.json:
        args.json.write_text(json.dumps(records, indent=2, default=str))
        print(f"\nWritten to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
