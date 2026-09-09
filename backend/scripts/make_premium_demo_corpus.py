"""Generate a large, deterministic demo corpus without altering the certified benchmark.

Creates 45 detailed bids (15 per major tender) in three realistic procurement
cohorts. Every document inherits a pre-declared compliance archetype, so the
manifest is an answer key rather than a label inferred after generation.
"""
from __future__ import annotations
import csv,hashlib,json,sys
from dataclasses import asdict,replace
from datetime import date
from pathlib import Path
from pypdf import PdfReader
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.bidgen.render import render_pdf
from app.bidgen.tenders import PROFILES
from app.bidgen.vendors import GHMC_VENDORS,IITISM_VENDORS,HGCL_VENDORS

POOLS={"NOTIF_supply_01":GHMC_VENDORS,"NOTIF_civilworks_01":IITISM_VENDORS,"NOTIF_civilworks_02":HGCL_VENDORS}
NAMES={
"NOTIF_supply_01":["Astra Urban Lighting","VedaGrid Electricals","Kakatiya Luminaire Works","Navajyothi Infrastructure","CivicRay Systems"],
"NOTIF_civilworks_01":["Parasnath Civil Projects","Damodar Buildcraft","Chotanagpur Engineering","Barakar Infrastructure","Shikhar Boundary Systems"],
"NOTIF_civilworks_02":["Arka Solar EPC","Suryanet Renewables","Deccan Grid Projects","HelioSpan Infrastructure","Pragati Energy Works"]}
COHORTS=[("A","Established regional contractor","Private Limited"),("B","Growth-stage specialist bidder","LLP"),("C","Multi-state procurement participant","Projects India Limited")]

def main()->int:
    root=Path(__file__).parents[2]/"data/premium_demo";out=root/"vendors";out.mkdir(parents=True,exist_ok=True)
    records=[]
    for notification_id,bases in POOLS.items():
        tender=PROFILES[notification_id]
        for cohort_index,(cohort,persona,suffix) in enumerate(COHORTS):
            for index,base in enumerate(bases):
                serial=cohort_index*5+index+1
                name=f"{NAMES[notification_id][index]} {suffix}"
                spec=replace(base,vendor_id=f"DEMO_{notification_id}_{serial:02d}",vendor_name=name,notes=f"{persona}. {base.notes}")
                path=render_pdf(spec,tender,out)
                records.append({"vendor_id":spec.vendor_id,"vendor_name":name,"notification_id":notification_id,"cohort":cohort,"persona":persona,"scenario":index+1,"intended_status":spec.intended_status,"intended_reason":spec.intended_reason,"intended_failed_clause":spec.intended_failed_clause,"blacklisted":spec.is_blacklisted,"borderline":spec.is_borderline,"writeup_quality":spec.writeup_quality,"pages":len(PdfReader(path).pages),"bytes":path.stat().st_size,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"file":path.name,"generated":date.today().isoformat()})
    with (root/"manifest.json").open("w") as handle:json.dump(records,handle,indent=2)
    with (root/"answer_key.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=records[0].keys());writer.writeheader();writer.writerows(records)
    summary={"documents":len(records),"pages":sum(r["pages"] for r in records),"bytes":sum(r["bytes"] for r in records),"tenders":len(POOLS),"pass":sum(r["intended_status"]=="pass" for r in records),"eliminate":sum(r["intended_status"]=="eliminate" for r in records),"borderline":sum(r["borderline"] for r in records),"blacklisted":sum(r["blacklisted"] for r in records),"strong_writeups":sum(r["writeup_quality"]=="strong" for r in records)}
    (root/"README.md").write_text("# Premium demo corpus\n\nThis corpus is isolated from the certified benchmark. Outcomes were fixed before rendering.\n\n```json\n"+json.dumps(summary,indent=2)+"\n```\n\nEach tender has three five-bid cohorts covering compliant, numeric failure, single-document failure, debarment, exact-threshold, strong-prose, and weak-prose cases. PDFs contain cover letters, profiles, financial schedules, project credentials, certification schedules, technical methodology, declarations, pricing, and enclosure registers.\n")
    print(json.dumps(summary,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
