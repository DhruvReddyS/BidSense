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
        from app.compliance.requirements import Applicability, Verifiability
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
                # ENCLOSURE only. A bidder cannot enclose a Pass-Phrase, a
                # catch-all ("relevant documents ... etc.") or an eligibility
                # condition restated as paperwork, so putting those on a
                # compliant bid's checklist would make the fixture unrealistic
                # in exactly the direction that hides a real defect.
                return [
                    r.primary.doc_name
                    for r in requirements
                    if r.applicability is Applicability.ALWAYS
                    and r.verifiability is Verifiability.ENCLOSURE
                ]
    except Exception:
        return None
    return None

TRACKING_HEADER = [
    "vendor_id", "notification_id", "intended_status", "intended_reason",
    "intended_failed_clause",
    # Which KIND of mandatory failure the key asserts. Section 5.2 makes both
    # criteria and documents disqualifying, but a turnover shortfall cannot be
    # cured and a missing form usually can, so a single blended precision
    # conflates two decisions -- and reported 75% while the rule engine was
    # exact. Declared on the spec rather than inferred from the prose reason,
    # so a reworded note cannot silently change the answer key.
    "intended_ground",
    "is_blacklisted", "technical_writeup_quality",
    "file_name", "generated_by", "date", "notes",
]


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
        size = path.stat().st_size / 1024
        flag = "PASS     " if spec.intended_status == "pass" else "ELIMINATE"
        source = f"{len(required)} extracted" if required else "profile list"
        print(
            f"  {flag}  {spec.vendor_id:26} {size:6.0f}KB  {source:14} "
            f"{spec.intended_reason[:38]}"
        )

    tracking = Path(args.tracking)

    # MERGE, never overwrite. Rows for vendors this script does not own --
    # the SBI_AMCC progression, which make_sbi_vendor_versions.py maintains by
    # hand in this same file -- were silently deleted on every regeneration,
    # taking four of the nineteen answer-key entries with them.
    existing: dict[str, list[str]] = {}
    if tracking.exists():
        with tracking.open(newline="") as handle:
            rows = list(csv.reader(handle))
        if rows:
            old_header = rows[0]
            for row in rows[1:]:
                if not row:
                    continue
                record = dict(zip(old_header, row))
                existing[record.get("vendor_id", "")] = [
                    record.get(column, "") for column in TRACKING_HEADER
                ]

    owned = {spec.vendor_id for spec in ALL_VENDORS}
    foreign = [row for vid, row in existing.items() if vid and vid not in owned]

    with tracking.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(TRACKING_HEADER)
        for spec in ALL_VENDORS:      # always write the full key, not the subset
            writer.writerow([
                spec.vendor_id, spec.notification_id, spec.intended_status,
                spec.intended_reason, spec.intended_failed_clause,
                spec.intended_ground,
                str(spec.is_blacklisted).lower(), spec.writeup_quality,
                f"{spec.vendor_id}.pdf", "scripts.make_vendor_bids",
                date.today().isoformat(), spec.notes,
            ])
        for row in foreign:
            writer.writerow(row)

    passes = sum(1 for v in ALL_VENDORS if v.intended_status == "pass")
    print(f"\nAnswer key: {tracking} — {len(ALL_VENDORS)} generated "
          f"({passes} pass, {len(ALL_VENDORS) - passes} eliminate)"
          + (f" + {len(foreign)} preserved from other generators" if foreign else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
