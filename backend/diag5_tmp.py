import csv
from scripts.evaluate import report_for, tender_ids_by_notification
from app.compliance.elimination import decide
truth={r["vendor_id"]:r for r in csv.DictReader(open("../data/tracking_vendors.csv"))}
tmap=tender_ids_by_notification()
for vid,row in truth.items():
    if row["intended_status"]!="eliminate": continue
    rep=report_for(tmap.get(row["notification_id"]), vid)
    if rep is None: continue
    b=rep.blocking_items
    d=decide(rep)
    cited=[(i.notification_provenance.clause_ref if i.notification_provenance else None, i.kind.value) for i in b]
    print(f"\n{vid}  ground={row['intended_ground']}")
    print(f"   key clause   : {row['intended_failed_clause']!r}")
    print(f"   engine primary: {d.clause_ref!r} (ground {d.ground.value if d.ground else None})")
    print(f"   all cited    : {cited[:6]}")
