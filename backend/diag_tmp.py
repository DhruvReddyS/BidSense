import csv
from scripts.evaluate import report_for, tender_ids_by_notification
from app.compliance.requirements import classify_verifiability
truth={}
with open("../data/tracking_vendors.csv") as f:
    for row in csv.DictReader(f): truth[row["vendor_id"]]=row
tmap=tender_ids_by_notification()
for vid in ["VENDOR_civilworks_01_01","VENDOR_civilworks_01_05",
            "VENDOR_civilworks_02_01","VENDOR_civilworks_02_05"]:
    rep=report_for(tmap[truth[vid]["notification_id"]], vid)
    blockers=[i for i in rep.items if i.severity.value=="disqualifying"]
    print(f"\n== {vid}: {len(blockers)} blocking")
    for b in blockers:
        rv=b.required_value or ""
        print(f"   [{classify_verifiability(rv).value:12}] {rv[:72]}")
