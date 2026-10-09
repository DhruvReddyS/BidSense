import csv
from scripts.evaluate import report_for, tender_ids_by_notification
truth={r["vendor_id"]:r for r in csv.DictReader(open("../data/tracking_vendors.csv"))}
tmap=tender_ids_by_notification()
print("vendor                        intended  criteria-blockers  document-blockers")
for vid,row in truth.items():
    tid=tmap.get(row["notification_id"])
    rep=report_for(tid,vid)
    if rep is None: continue
    b=[i for i in rep.items if i.severity.value=="disqualifying"]
    crit=[i for i in b if i.kind.value!="document"]
    docs=[i for i in b if i.kind.value=="document"]
    print(f"{vid:29} {row['intended_status']:9} {len(crit):17} {len(docs):17}")
