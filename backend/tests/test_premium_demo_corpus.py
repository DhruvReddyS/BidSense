import csv,hashlib,json
from pathlib import Path
from pypdf import PdfReader

ROOT=Path(__file__).parents[2]/"data/premium_demo"

def test_premium_manifest_has_rigorous_balanced_coverage():
    rows=json.loads((ROOT/"manifest.json").read_text())
    assert len(rows)==45
    assert {row["notification_id"] for row in rows}=={"NOTIF_supply_01","NOTIF_civilworks_01","NOTIF_civilworks_02"}
    for tender in {row["notification_id"] for row in rows}:
        subset=[row for row in rows if row["notification_id"]==tender]
        assert len(subset)==15
        assert {row["cohort"] for row in subset}=={"A","B","C"}
        assert {row["intended_status"] for row in subset}=={"pass","eliminate"}
        assert any(row["borderline"] for row in subset)
        assert {row["writeup_quality"] for row in subset}=={"strong","weak"}
    assert sum(row["blacklisted"] for row in rows)>=6

def test_every_manifest_row_has_a_large_readable_pdf_and_answer_key():
    rows=json.loads((ROOT/"manifest.json").read_text())
    keyed=list(csv.DictReader((ROOT/"answer_key.csv").open()))
    assert {row["vendor_id"] for row in rows}=={row["vendor_id"] for row in keyed}
    for row in rows:
        path=ROOT/"vendors"/row["file"]
        assert path.stat().st_size>50_000
        assert hashlib.sha256(path.read_bytes()).hexdigest()==row["sha256"]
        reader=PdfReader(path)
        assert len(reader.pages)==row["pages"] and row["pages"]>=50
        opening=" ".join((page.extract_text() or "") for page in reader.pages[:3])
        assert row["vendor_name"] in opening
        assert row["vendor_id"] in opening
