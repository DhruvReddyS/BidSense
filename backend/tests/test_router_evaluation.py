"""Deterministic intent-router accuracy against the labelled set (Sections 9.3, 10)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.review.workflow import classify_query

ROWS = json.loads(
    (Path(__file__).parents[2] / "data" / "router_queries.json").read_text()
)

#: Floor, not a target. The router's vocabulary was fitted on the dev split, so
#: this is the only figure that evidences anything -- and it is deliberately
#: below the measured 95.5% so that a genuine regression fails here while
#: ordinary ambiguity does not.
HELD_OUT_FLOOR = 0.85


def _accuracy(rows: list[dict]) -> tuple[int, int, list[str]]:
    misses = [
        f"want {r['route']} got {classify_query(r['question'])}: {r['question']!r}"
        for r in rows
        if classify_query(r["question"]) != r["route"]
    ]
    return len(rows) - len(misses), len(rows), misses


def test_the_labelled_set_is_the_size_the_scope_asks_for():
    """Section 9.3 specifies 50 labelled queries; the first version had 12.

    Size is asserted because the earlier set's perfect score was an artefact of
    being small AND built around the router's own keywords. Shrinking it back
    must fail rather than quietly restore a flattering number.
    """
    assert len(ROWS) >= 50
    assert all(r.get("split") in {"dev", "test"} for r in ROWS), (
        "every query must declare which split it belongs to"
    )
    per_route = Counter(r["route"] for r in ROWS)
    assert set(per_route) == {"audit", "structured", "qualitative", "comparative", "hybrid"}
    # Every route must appear in the held-out half, or the held-out figure says
    # nothing about the routes missing from it.
    held_routes = Counter(r["route"] for r in ROWS if r["split"] == "test")
    assert set(held_routes) == set(per_route)


def test_router_accuracy_on_the_held_out_split():
    """The number that counts: queries the vocabulary was NOT fitted against."""
    held = [r for r in ROWS if r["split"] == "test"]
    correct, total, misses = _accuracy(held)
    assert correct / total >= HELD_OUT_FLOOR, (
        f"held-out router accuracy {correct}/{total} fell below "
        f"{HELD_OUT_FLOOR:.0%}:\n  " + "\n  ".join(misses)
    )


def test_audit_questions_never_route_to_live_facts():
    """A "why was X eliminated" question must reach the RECORDED reason.

    Answering it from current facts would reconstruct a decision rather than
    report the one actually taken, and the recorded reason is the only answer
    defensible on challenge. This holds regardless of how the question is
    phrased, so it is asserted separately from the aggregate.
    """
    for question in (
        "Why was Vendor A eliminated?",
        "On what grounds was bidder 4 rejected?",
        "Explain the disqualification of the third bidder",
        "Which clause did Vendor C fail?",
        "Justify the exclusion of Vendor E",
    ):
        assert classify_query(question) == "audit", question
