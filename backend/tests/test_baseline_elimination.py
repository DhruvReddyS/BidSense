"""The LLM-only elimination baseline must be scored exactly like the engine.

This baseline carries the paper's central claim -- that a model reaches the
right verdict while citing the wrong rule -- so the comparison has to be fair in
the one way that matters: both arms judged on the same bids by the same clause
comparator. A baseline scored by a second, laxer comparator is not a baseline,
and these tests pin that.

They also pin the honesty properties: an unavailable provider or an empty
database reports BLOCKED rather than a zero, and `--stub` can never be mistaken
for a measurement.
"""

from __future__ import annotations

import pytest

from scripts.baseline_elimination import Row, load_key, summarise
from scripts.evaluate import _clause_matches


def test_both_arms_use_the_shared_clause_comparator():
    """Imported, not reimplemented -- the typography tolerance must apply to
    the LLM arm too, or the engine wins on formatting rather than substance."""
    import scripts.baseline_elimination as module
    import inspect

    source = inspect.getsource(module)
    assert "from scripts.evaluate import _clause_matches as matcher" in source
    # And it must not define a rival matcher.
    assert "def _clause_matches" not in source


def test_the_comparator_is_tolerant_of_typography_for_either_arm():
    """'1.1 (4)' and '1.1(4)' are the same clause whoever cited it."""
    assert _clause_matches("1.1(4)", ["1.1 (4)"]) is True
    assert _clause_matches("1.1(4)", ["1.1(4)"]) is True


def test_a_passing_bid_has_no_clause_to_judge():
    """Reason accuracy is only defined where the key names a clause."""
    row = Row("V1", "pass", "")
    assert row.clause_ok("llm", _clause_matches) is None
    assert row.clause_ok("rule", _clause_matches) is None


def test_a_missing_citation_is_wrong_not_unverified():
    """A verdict with no clause must score as a failure, not be skipped --
    otherwise an arm that never cites anything reports perfect accuracy."""
    row = Row("V1", "eliminate", "5", llm_status="eliminate", llm_clause="")
    assert row.clause_ok("llm", _clause_matches) is False


def test_the_right_verdict_with_the_wrong_clause_scores_as_wrong():
    """The whole point of the baseline."""
    row = Row("V1", "eliminate", "5", llm_status="eliminate", llm_clause="7")
    assert row.status_ok("llm") is True
    assert row.clause_ok("llm", _clause_matches) is False


def test_the_right_verdict_with_the_right_clause_scores_as_right():
    row = Row("V1", "eliminate", "5", llm_status="eliminate", llm_clause="5")
    assert row.status_ok("llm") and row.clause_ok("llm", _clause_matches)


def test_summary_counts_only_judgeable_bids_in_reason_accuracy():
    rows = [
        Row("A", "eliminate", "5", llm_status="eliminate", llm_clause="5"),
        Row("B", "eliminate", "7", llm_status="eliminate", llm_clause="9"),
        Row("C", "pass", "", llm_status="pass"),
    ]
    summary = summarise(rows, "llm", _clause_matches)
    assert summary["n"] == 3
    assert summary["status_correct"] == 3
    assert summary["clause_judged"] == 2, "the passing bid is not judgeable"
    assert summary["clause_correct"] == 1
    assert "n=2" in summary["reason_accuracy"]


def test_every_figure_carries_its_interval():
    """A bare percentage from four bids is the thing this project refuses."""
    rows = [Row("A", "eliminate", "5", llm_status="eliminate", llm_clause="5")]
    summary = summarise(rows, "llm", _clause_matches)
    assert "[" in summary["status_accuracy"] and "n=1" in summary["status_accuracy"]


def test_the_answer_key_loads_and_is_limitable():
    rows = load_key(limit=4)
    assert len(rows) == 4
    assert all(r.vendor_id for r in rows)
    assert all(r.intended_status in ("pass", "eliminate") for r in rows)


def test_the_full_key_has_enough_eliminated_bids_to_ever_reach_significance():
    """A documented limit, asserted so it cannot be forgotten.

    Reason accuracy is only judgeable on eliminated bids whose key names a
    clause. An exact paired sign test needs six discordant pairs before even a
    clean sweep clears 0.05 (p=0.0312); at three it cannot (p=0.2500). If this
    ever fails, the claim is unprovable at that n regardless of the result.
    """
    judgeable = [
        r for r in load_key(None)
        if r.intended_status == "eliminate"
        and _clause_matches(r.intended_clause, ["x"]) is not None
    ]
    assert len(judgeable) >= 6, (
        f"only {len(judgeable)} bids can be judged on reason; a clean sweep "
        f"would still not reach p<0.05"
    )
