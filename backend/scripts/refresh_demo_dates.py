"""Refresh the complete demo corpus with future tender schedule dates.

The three notification PDFs are source documents, so their schedule text is
updated in place with a white-backed overlay. The synthetic vendor bids are
then regenerated from the matching tender profiles and copied into the
presenter-friendly quick/extended folder layout with fresh answer-key hashes.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pymupdf as fitz

from scripts.make_premium_demo_corpus import main as generate_premium_corpus


ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "data" / "demo"

NOTIFICATION_REPLACEMENTS = {
    DEMO / "01_campus_maintenance_civil_works/01_notification/NOTIF_civilworks_01.pdf": {
        "17 August 2026": "1 December 2027",
        "19 August 2026": "5 December 2027",
        "22 August 2026": "15 December 2027",
        "24 August 2026": "17 December 2027",
    },
    DEMO / "02_ghmc_led_street_lights/01_notification/NOTIF_supply_01.pdf": {
        "13-09-2024": "01-12-2027",
        "13.09.2024": "01.12.2027",
        "16-09-2024": "01-12-2027",
        "25-09-2024": "15-12-2027",
    },
    DEMO / "03_hgcl_rooftop_solar/01_notification/NOTIF_civilworks_02.pdf": {
        "24.04.2023": "01.12.2027",
        "24/04/2023": "01/12/2027",
        "25.04.2023": "01.12.2027",
        "03.05.2023": "15.12.2027",
    },
}

SOURCE_NOTIFICATIONS = {
    path: ROOT / "data" / "notifications" / path.name
    for path in NOTIFICATION_REPLACEMENTS
}

DEMO_FOLDERS = {
    "NOTIF_civilworks_01": DEMO / "01_campus_maintenance_civil_works",
    "NOTIF_supply_01": DEMO / "02_ghmc_led_street_lights",
    "NOTIF_civilworks_02": DEMO / "03_hgcl_rooftop_solar",
}


def _replace_schedule_text(path: Path, replacements: dict[str, str]) -> None:
    document = fitz.open(path)
    found = {old: 0 for old in replacements}
    for page in document:
        pending: list[tuple[fitz.Rect, str]] = []
        for old, new in replacements.items():
            for rect in page.search_for(old):
                found[old] += 1
                pending.append((rect, new))
                page.add_redact_annot(rect, fill=(1, 1, 1))
        if pending:
            page.apply_redactions()
            for rect, new in pending:
                font_size = max(5.5, min(9.0, rect.height * 0.72))
                while fitz.get_text_length(new, fontname="helv", fontsize=font_size) > rect.width and font_size > 5.5:
                    font_size -= 0.25
                page.insert_text(
                    fitz.Point(rect.x0, rect.y1 - 1.5),
                    new,
                    fontname="helv",
                    fontsize=font_size,
                    color=(0, 0, 0),
                )
    missing = [old for old, count in found.items() if not count]
    if missing:
        document.close()
        raise RuntimeError(f"Schedule text not found in {path}: {missing}")
    temporary = path.with_suffix(".future-dates.pdf")
    document.save(temporary, garbage=4, deflate=True)
    document.close()
    temporary.replace(path)


def _refresh_presenter_folders() -> None:
    premium = ROOT / "data" / "premium_demo"
    with (premium / "answer_key.csv").open(newline="") as handle:
        records = list(csv.DictReader(handle))

    for notification_id, folder in DEMO_FOLDERS.items():
        selected = [record for record in records if record["notification_id"] == notification_id]
        quick = folder / "02_quick_demo_bids"
        extended = folder / "03_extended_test_bids"
        for index, record in enumerate(selected):
            destination = quick if index < 5 else extended
            shutil.copy2(premium / "vendors" / record["file"], destination / record["file"])
        with (folder / "answer_key.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=records[0].keys())
            writer.writeheader()
            writer.writerows(selected)


def main() -> int:
    for path, replacements in NOTIFICATION_REPLACEMENTS.items():
        shutil.copy2(SOURCE_NOTIFICATIONS[path], path)
        _replace_schedule_text(path, replacements)
    generate_premium_corpus()
    _refresh_presenter_folders()
    print("Refreshed 3 notification PDFs and 45 presenter bid PDFs for December 2027.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
