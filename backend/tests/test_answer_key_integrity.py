"""The answer key is the ground truth, so losing part of it corrupts every number.

`tracking_vendors.csv` is shared: fifteen rows come from
`scripts.make_vendor_bids`, four from `scripts.make_sbi_vendor_versions`, and
columns get added by hand as the evaluation grows. Regenerating used to open the
file in "w" mode and write only its own fifteen specs, which silently deleted
the four SBI rows and the whole `intended_ground` column -- the kind of loss
that does not fail, it just makes Section 10 measure whatever survived.

These tests pin the three ways that can happen: a dropped row, a dropped
column, and a spec that has drifted from a hand-corrected key value.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from app.bidgen.vendors import ALL_VENDORS
from scripts.make_vendor_bids import OWNED_BY, TRACKING_HEADER, merge_tracking

KEY_PATH = Path(__file__).resolve().parents[2] / "data" / "tracking_vendors.csv"


def read_key(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def generator_rows(today: str = "2099-01-01") -> list[dict[str, str]]:
    """Exactly what main() hands to merge_tracking."""
    return [
        {
            "vendor_id": spec.vendor_id,
            "notification_id": spec.notification_id,
            "intended_status": spec.intended_status,
            "intended_reason": spec.intended_reason,
            "intended_failed_clause": spec.intended_failed_clause,
            "intended_ground": spec.intended_ground,
            "is_blacklisted": str(spec.is_blacklisted).lower(),
            "technical_writeup_quality": spec.writeup_quality,
            "file_name": f"{spec.vendor_id}.pdf",
            "generated_by": OWNED_BY,
            "date": today,
            "notes": spec.notes,
        }
        for spec in ALL_VENDORS
    ]


@pytest.fixture()
def key_copy(tmp_path: Path) -> Path:
    """A throwaway copy, so a failing test can never damage the real key."""
    target = tmp_path / "tracking_vendors.csv"
    target.write_bytes(KEY_PATH.read_bytes())
    return target


def test_regeneration_keeps_another_generators_rows(key_copy: Path):
    """The four SBI bids are not this generator's to delete."""
    before = {r["vendor_id"] for r in read_key(key_copy)}
    foreign = {
        r["vendor_id"] for r in read_key(key_copy)
        if r["generated_by"] != OWNED_BY
    }
    assert foreign, "fixture should contain rows from another generator"

    merge_tracking(key_copy, generator_rows())

    after = {r["vendor_id"] for r in read_key(key_copy)}
    assert foreign <= after, f"lost foreign rows: {foreign - after}"
    assert before == after, f"row set changed: {before ^ after}"


def test_regeneration_keeps_every_column(key_copy: Path):
    """A column the generator does not know about still survives."""
    original = read_key(key_copy)
    columns = list(original[0].keys())

    merge_tracking(key_copy, generator_rows())

    assert list(read_key(key_copy)[0].keys()) == columns


def test_regeneration_preserves_hand_curated_labels(key_copy: Path):
    """Foreign rows keep their labels verbatim, not just their ids."""
    label_columns = (
        "intended_status", "intended_reason",
        "intended_failed_clause", "intended_ground",
    )
    before = {
        r["vendor_id"]: {c: r[c] for c in label_columns}
        for r in read_key(key_copy) if r["generated_by"] != OWNED_BY
    }

    merge_tracking(key_copy, generator_rows())

    after = {
        r["vendor_id"]: {c: r[c] for c in label_columns}
        for r in read_key(key_copy) if r["generated_by"] != OWNED_BY
    }
    assert before == after


def test_specs_agree_with_the_committed_key():
    """A hand-correction in the sheet must be mirrored back into the spec.

    The generator owns these columns, so a key value the spec disagrees with is
    not a correction -- it is a value one regeneration away from being lost. The
    em-dash placeholder for VENDOR_civilworks_02_03 against the key's real
    clause 11.II(a)(h) was exactly that.
    """
    key = {r["vendor_id"]: r for r in read_key(KEY_PATH)}
    drift = []
    for spec in ALL_VENDORS:
        row = key.get(spec.vendor_id)
        assert row is not None, f"{spec.vendor_id} missing from the answer key"
        for column, value in (
            ("intended_status", spec.intended_status),
            ("intended_reason", spec.intended_reason),
            ("intended_failed_clause", spec.intended_failed_clause),
            ("intended_ground", spec.intended_ground),
            ("is_blacklisted", str(spec.is_blacklisted).lower()),
            ("technical_writeup_quality", spec.writeup_quality),
        ):
            if row[column] != value:
                drift.append(f"{spec.vendor_id}.{column}: key={row[column]!r} spec={value!r}")
    assert not drift, "spec/key drift:\n" + "\n".join(drift)


def test_partial_run_does_not_restamp_untouched_bids(key_copy: Path):
    """`--tender X` regenerates one tender; the others keep their own dates."""
    stored = {r["vendor_id"]: r["date"] for r in read_key(key_copy)}
    one = ALL_VENDORS[0].vendor_id

    merge_tracking(key_copy, generator_rows(today="2099-01-01"), rendered={one})

    after = {r["vendor_id"]: r["date"] for r in read_key(key_copy)}
    assert after[one] == "2099-01-01", "the regenerated bid should be restamped"
    for vendor_id, was in stored.items():
        if vendor_id != one:
            assert after[vendor_id] == was, f"{vendor_id} date changed to {after[vendor_id]}"


def test_a_new_spec_is_appended_rather_than_dropped(key_copy: Path):
    rows = generator_rows()
    rows.append({**rows[0], "vendor_id": "VENDOR_newtender_01_01"})

    merge_tracking(key_copy, rows)

    assert "VENDOR_newtender_01_01" in {r["vendor_id"] for r in read_key(key_copy)}


def test_header_covers_every_column_the_generator_writes():
    assert set(generator_rows()[0]) == set(TRACKING_HEADER)


def test_every_eliminated_bid_declares_a_ground_and_every_pass_does_not():
    """Section 10 splits elimination by ground, so the label must be total."""
    for spec in ALL_VENDORS:
        if spec.intended_status == "eliminate":
            assert spec.intended_ground in ("criteria", "document"), spec.vendor_id
        else:
            assert spec.intended_ground == "", spec.vendor_id
