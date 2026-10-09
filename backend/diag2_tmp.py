import csv
from sqlalchemy import select
from app.db.session import session_scope
from app.db.models import VendorSubmissionRow
for vid in ["VENDOR_civilworks_02_01","VENDOR_civilworks_01_01"]:
    with session_scope() as s:
        sub=s.scalar(select(VendorSubmissionRow).where(VendorSubmissionRow.vendor_id==vid))
        docs=sub.documents_submitted
        print(f"\n===== {vid}: {len(docs)} enclosures declared =====")
        for d in docs:
            print(f"   present={d.present}  {d.doc_name[:74]}")
