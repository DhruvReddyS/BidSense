"""Generate the synthetic vendor bid set with its answer key (Section 9.2).

    python -m scripts.make_vendor_bids                 # all tenders
    python -m scripts.make_vendor_bids --tender NOTIF_supply_01

Ground truth is written to data/tracking_vendors.csv (Section 9.4, Tab 2) in the
same run, so the answer key can never drift out of sync with the files -- the
risk Section 9 calls out explicitly.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bidgen.render import render_pdf  # noqa: E402
from app.bidgen.tenders import PROFILES  # noqa: E402
from app.bidgen.vendors import ALL_VENDORS  # noqa: E402


def extracted_requirements(notification_id: str) -> list[str] | None:
    """The deduplicated document list the pipeline read from this notification.

    Generating a bid's enclosure checklist from what the system actually
    extracted keeps the two in step. Otherwise a "compliant" vendor is compliant
    only against a hand-written list, and the evaluation measures the fixture
    rather than the pipeline.
    """
    try:
        from app.compliance.gap import _collect_requirements
        from app.db.repository import list_notifications, to_notification_schema
        from app.db.session import session_scope
        from app.compliance.requirements import Applicability
    except Exception:
        return None

    try:
        with session_scope() as session:
            for row in list_notifications(session, limit=200):
                if not row.source_file or Path(row.source_file).stem != notification_id:
                    continue
                requirements = _collect_requirements(to_notification_schema(row))
                # Only the unconditional ones: a sole bidder does not enclose a
                # JV agreement, and a bid that did would be unrealistic.
                return [
                    r.primary.doc_name
                    for r in requirements
                    if r.applicability is Applicability.ALWAYS
                ]
    except Exception:
        return None
    return None

TRACKING_HEADER = [
    "vendor_id", "notification_id", "intended_status", "intended_reason",
    "intended_failed_clause", "intended_ground", "is_blacklisted",
    "technical_writeup_quality", "file_name", "generated_by", "date", "notes",
]

#: What this generator is allowed to rewrite. The answer key is shared: the four
#: SBI bids come from scripts.make_sbi_vendor_versions, and columns get added to
#: the sheet by hand as the evaluation grows. Anything outside this set is
#: somebody else's row or somebody else's column.
OWNED_BY = "scripts.make_vendor_bids"


def merge_tracking(
    path: Path, rows: list[dict[str, str]], rendered: set[str] | None = None
) -> tuple[int, int]:
    """Write `rows` into the answer key without disturbing anyone else's.

    The obvious implementation -- open "w", write the header, write the fifteen
    specs -- silently destroys data, and did: it drops every row produced by
    another generator and every column this script does not know about. Since
    the sheet *is* the ground truth, that is not a cosmetic loss; the evaluation
    then measures whatever survived.

    So: read what is there, replace only the rows this generator owns, keep the
    rest where they were, and union the columns so a hand-added one survives a
    regeneration. Returns (updated, preserved).

    `rendered` names the vendors whose PDF this run actually wrote. The `date`
    column records when a bid was generated, so for anything outside that set --
    every other tender under `--tender` -- the stored date is kept rather than
    stamped with today's, which would claim a regeneration that never happened.
    """
    rendered = rendered if rendered is not None else {row["vendor_id"] for row in rows}
    incoming = {row["vendor_id"]: row for row in rows}

    existing: list[dict[str, str]] = []
    fieldnames: list[str] = []
    if path.exists():
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            existing = [dict(row) for row in reader]

    # Existing column order wins, so a regeneration produces a minimal diff;
    # genuinely new columns are appended rather than silently dropped.
    for column in TRACKING_HEADER:
        if column not in fieldnames:
            fieldnames.append(column)

    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    preserved = 0
    for row in existing:
        vendor_id = row.get("vendor_id", "")
        replacement = incoming.get(vendor_id)
        if replacement is None:
            merged.append(row)          # another generator's row, or a stray
            preserved += 1
        else:
            # Keep any extra columns this script does not manage.
            fresh = dict(replacement)
            if vendor_id not in rendered and row.get("date"):
                fresh["date"] = row["date"]
            merged.append({**row, **fresh})
        seen.add(vendor_id)

    for row in rows:                    # specs not yet in the sheet
        if row["vendor_id"] not in seen:
            merged.append(row)

    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in merged:
            writer.writerow({column: row.get(column, "") for column in fieldnames})

    return len(rows), preserved


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic vendor bids")
    parser.add_argument("--out", default="../data/vendors")
    parser.add_argument("--tracking", default="../data/tracking_vendors.csv")
    parser.add_argument("--tender", help="limit to one notification_id")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    selected = [
        v for v in ALL_VENDORS
        if args.tender is None or v.notification_id == args.tender
    ]
    if not selected:
        print(f"No vendors defined for {args.tender!r}")
        return 1

    requirement_cache: dict[str, list[str] | None] = {}
    rendered: set[str] = set()
    current = ""
    for spec in selected:
        tender = PROFILES[spec.notification_id]
        if spec.notification_id != current:
            current = spec.notification_id
            print(f"\n{current}  ({tender.authority})")
        required = requirement_cache.setdefault(
            spec.notification_id, extracted_requirements(spec.notification_id)
        )
        path = render_pdf(spec, tender, out_dir, required_documents=required)
        rendered.add(spec.vendor_id)
        size = path.stat().st_size / 1024
        flag = "PASS     " if spec.intended_status == "pass" else "ELIMINATE"
        source = f"{len(required)} extracted" if required else "profile list"
        print(
            f"  {flag}  {spec.vendor_id:26} {size:6.0f}KB  {source:14} "
            f"{spec.intended_reason[:38]}"
        )

    tracking = Path(args.tracking)
    today = date.today().isoformat()
    rows = [                          # always the full key, not the subset
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
    updated, preserved = merge_tracking(tracking, rows, rendered)

    passes = sum(1 for v in ALL_VENDORS if v.intended_status == "pass")
    print(f"\nAnswer key: {tracking} — {updated} vendors "
          f"({passes} pass, {updated - passes} eliminate)"
          + (f", {preserved} row(s) from other generators preserved"
             if preserved else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
