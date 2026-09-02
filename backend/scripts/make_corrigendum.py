"""Generate the synthetic corrigendum set with its answer key (Section 5.6).

    python -m scripts.make_corrigendum

The amendments are fixed here, before the prose, for the same reason Section
9.2.1 fixes a bid's compliance outcome first: a corrigendum written and then
read back tells you the extractor can read its own output, which is not a test
of anything. Each spec's `amendments` map IS the answer key, and
`tests/test_corrigendum.py` asserts the diff against it.

The old values are the ones actually extracted from the parent notifications, so
the diff has something real to be right or wrong about.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bidgen.corrigenda import CorrigendumSpec, render_pdf  # noqa: E402

# Keyed by the parent tender_id as extracted. The old values below are what the
# pipeline read from those notifications -- see `data/tracking_notifications.csv`
# and the ingest report -- so a diff that disagrees is the diff being wrong.
SPECS: dict[str, CorrigendumSpec] = {
    "CMU-12011/17/2026-CMU": CorrigendumSpec(
        corrigendum_id="CORRIGENDUM No. 1",
        parent_tender_ref="CMU-12011/17/2026-CMU",
        authority="Indian Institute of Technology (Indian School of Mines) Dhanbad",
        authority_address="Construction and Maintenance Unit, IIT (ISM) Dhanbad, "
        "Jharkhand — 826 004",
        work_title="Construction of boundary wall at the Institute campus",
        issued_date="12.08.2026",
        issued_date_iso="2026-08-12",
        amendments={
            # The parent extracted these exact strings.
            "submission_deadline": ("22.08.2026", "05.09.2026"),
            "pre_bid_query_deadline": ("19.08.2026", "29.08.2026"),
            "emd_amount": ("Rs. 31,500/-", "Rs. 25,200/-"),
        },
        unmapped_notes=(
            "Bidders are advised that the pre-bid meeting shall now be held in "
            "hybrid mode. The video-conference link shall be published on the "
            "Institute website two days prior to the meeting.",
        ),
        reason="requests received from prospective bidders for extension of time",
    ),
    "TENDER No.01/SE(Electrical)/GHMC/2024-25": CorrigendumSpec(
        corrigendum_id="Corrigendum-II",
        parent_tender_ref="TENDER No.01/SE(Electrical)/GHMC/2024-25",
        authority="Greater Hyderabad Municipal Corporation",
        authority_address="Office of the Superintending Engineer (Electrical), "
        "GHMC, Tank Bund Road, Hyderabad — 500 063",
        work_title="Supply, installation and commissioning of LED street light "
        "fittings in GHMC limits",
        issued_date="03.09.2024",
        issued_date_iso="2024-09-03",
        amendments={
            "submission_deadline": ("25.09.2024", "10.10.2024"),
            "contract_value_estimate": ("Rs. 298.72 Lakhs", "Rs. 312.45 Lakhs"),
        },
        reason="revision of the schedule of rates notified by the Government",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic corrigenda")
    parser.add_argument("--out", default="../data/corrigenda")
    parser.add_argument("--key", default="../data/tracking_corrigenda.json")
    parser.add_argument("--tender", help="limit to one parent tender_id")
    args = parser.parse_args()

    out_dir = Path(args.out)
    selected = {
        k: v for k, v in SPECS.items() if args.tender is None or k == args.tender
    }
    if not selected:
        print(f"No corrigendum defined for {args.tender!r}")
        return 1

    key = {}
    for tender_id, spec in selected.items():
        path = render_pdf(spec, out_dir)
        print(f"  {spec.corrigendum_id:22} -> {path.name:34} "
              f"{len(spec.amendments)} amendment(s), {path.stat().st_size / 1024:.0f}KB")
        key[tender_id] = {
            "file": str(path),
            "corrigendum_id": spec.corrigendum_id,
            "issued_date": spec.issued_date_iso,
            "amendments": {
                field: {"old": old, "new": new}
                for field, (old, new) in spec.amendments.items()
            },
            "unmapped_notes": list(spec.unmapped_notes),
        }

    key_path = Path(args.key)
    key_path.write_text(json.dumps(key, indent=2) + "\n")
    print(f"\nAnswer key: {key_path} — {len(key)} corrigendum(a)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
