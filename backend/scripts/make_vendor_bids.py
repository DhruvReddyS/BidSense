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
    "intended_failed_clause", "is_blacklisted", "technical_writeup_quality",
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
    with tracking.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(TRACKING_HEADER)
        for spec in ALL_VENDORS:      # always write the full key, not the subset
            writer.writerow([
                spec.vendor_id, spec.notification_id, spec.intended_status,
                spec.intended_reason, spec.intended_failed_clause,
                str(spec.is_blacklisted).lower(), spec.writeup_quality,
                f"{spec.vendor_id}.pdf", "scripts.make_vendor_bids",
                date.today().isoformat(), spec.notes,
            ])

    passes = sum(1 for v in ALL_VENDORS if v.intended_status == "pass")
    print(f"\nAnswer key: {tracking} — {len(ALL_VENDORS)} vendors "
          f"({passes} pass, {len(ALL_VENDORS) - passes} eliminate)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
