"""The double-labelling harness must not leak the answer it is checking.

A second annotation pass is worthless if the sheet shows the label, or the
reason text that implies it -- `intended_reason` for a document-ground
elimination reads "... not enclosed". These tests pin the blinding, the
guards that reject an unusable returned sheet, and the fact that kappa is
computed against the committed labels rather than recomputed from them.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.double_label import (
    DIMENSIONS, allowed_labels, committed_labels, emit, score, vendor_units,
)

ROOT = Path(__file__).resolve().parents[2]


def write_sheet(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_the_sheet_never_carries_the_label_or_the_reason(tmp_path, capsys):
    out = tmp_path / "sheet.csv"
    emit("ground", out)
    capsys.readouterr()

    text = out.read_text()
    assert "not enclosed" not in text, "the reason text gives the ground away"
    for row in csv.DictReader(out.open()):
        assert row["label"] == "", "the label column must arrive blank"
        assert "intended_ground" not in row
        assert "intended_reason" not in row


def test_ground_is_only_asked_about_eliminated_bids():
    """A passing bid has no ground, so labelling one is a meaningless task."""
    ids = {u["id"] for u in vendor_units("ground")}
    key = {
        r["vendor_id"]: r["intended_status"]
        for r in csv.DictReader((ROOT / "data" / "tracking_vendors.csv").open())
    }
    assert ids, "there should be eliminated bids to label"
    assert all(key[i] == "eliminate" for i in ids)


def test_kind_labels_are_read_from_the_query_set_not_hardcoded():
    """A stale literal here would reject a valid label as the taxonomy grows."""
    assert DIMENSIONS["kind"][0] == (), "kind must be derived, not literal"
    labels = allowed_labels("kind")
    assert labels and set(labels) == set(committed_labels("kind").values())


def test_a_perfect_return_scores_as_perfect(tmp_path, capsys):
    truth = committed_labels("ground")
    sheet = write_sheet(
        tmp_path / "returned.csv",
        [{"id": k, "label": v} for k, v in truth.items()],
    )
    assert score("ground", sheet) == 0
    out = capsys.readouterr().out
    assert "kappa=1.00" in out
    assert "No disagreements" in out


def test_disagreements_are_listed_for_adjudication(tmp_path, capsys):
    truth = committed_labels("ground")
    flip = {"criteria": "document", "document": "criteria"}
    rows = [{"id": k, "label": v} for k, v in truth.items()]
    rows[0]["label"] = flip[rows[0]["label"]]
    sheet = write_sheet(tmp_path / "returned.csv", rows)

    assert score("ground", sheet) == 0
    out = capsys.readouterr().out
    assert "1 disagreement" in out
    assert rows[0]["id"] in out


def test_an_unlabelled_row_is_refused_rather_than_scored(tmp_path):
    truth = committed_labels("ground")
    rows = [{"id": k, "label": v} for k, v in truth.items()]
    rows[0]["label"] = ""
    sheet = write_sheet(tmp_path / "returned.csv", rows)
    assert score("ground", sheet) == 1, "a blank must not count as agreement"


def test_a_label_outside_the_taxonomy_is_refused(tmp_path):
    truth = committed_labels("ground")
    rows = [{"id": k, "label": v} for k, v in truth.items()]
    rows[0]["label"] = "maybe"
    sheet = write_sheet(tmp_path / "returned.csv", rows)
    assert score("ground", sheet) == 1


def test_a_short_sheet_is_refused(tmp_path):
    """Scoring a subset would quietly report kappa on whatever came back."""
    truth = list(committed_labels("ground").items())
    sheet = write_sheet(
        tmp_path / "returned.csv",
        [{"id": k, "label": v} for k, v in truth[:3]],
    )
    assert score("ground", sheet) == 1


def test_the_protocol_the_harness_points_at_exists():
    assert (ROOT / "data" / "ANNOTATION_PROTOCOL.md").is_file()
