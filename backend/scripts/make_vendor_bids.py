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

    current = ""
    for spec in selected:
        tender = PROFILES[spec.notification_id]
        if spec.notification_id != current:
            current = spec.notification_id
            print(f"\n{current}  ({tender.authority})")
        path = render_pdf(spec, tender, out_dir)
        size = path.stat().st_size / 1024
        flag = "PASS     " if spec.intended_status == "pass" else "ELIMINATE"
        print(f"  {flag}  {spec.vendor_id:26} {size:6.0f}KB  {spec.intended_reason[:44]}")

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
