"""Source-guarded correction of a stored reference; default is read-only.
Run from backend with PYTHONPATH=. and --apply to commit the verified repair.
Preserves the source page, snippet, requirement, and original extraction audit.
"""
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import pdfplumber
from sqlalchemy import select
from app.db.session import session_scope
from app.db.models.notification import TenderNotificationRow
from app.ingest.pdf import _extract_tables

args=argparse.ArgumentParser()
args.add_argument('--apply',action='store_true')
apply=args.parse_args().apply
source=Path('../data/notifications/NOTIF_supply_01.pdf')
expected_hash='56eab438adfec7d241bf156b4516d4aed414ff71d567b97567d9393df90a550c'
assert hashlib.sha256(source.read_bytes()).hexdigest()==expected_hash
with pdfplumber.open(source) as pdf:
    heading=pdf.pages[14].extract_text()
    assert '22. The Technical Bid shall comprise of the following:' in heading
    rows=[r for t in _extract_tables(pdf.pages[15]) for r in t
          if len(r)>1 and ' '.join((r[1] or '').split())=='Manufacturers authorization form']
    assert len(rows)==1 and rows[0][0]=='7'
with session_scope() as s:
    n=s.scalars(select(TenderNotificationRow).where(TenderNotificationRow.tender_id=='TENDER No.01/SE(Electrical)/GHMC/2024-25').with_for_update()).one()
    assert n.content_hash==expected_hash
    targets=[r for r in n.mandatory_documents if r.doc_name=='Manufacturers authorization form']
    assert len(targets)==1
    r=targets[0]
    assert r.source_page==16 and r.clause_ref in ('22','22, item 7')
    audit=dict(time=datetime.now(timezone.utc).isoformat(),document_sha256=expected_hash,
               requirement_id=str(r.id),requirement=r.doc_name,source_page=r.source_page,
               before=r.clause_ref,after='22, item 7',table_row=rows[0],
               source_heading_page=15,reason='Retain parent clause 22 and add the exact table item 7.',
               applied=apply)
    if apply:
        Path('../output/hardening-2026-09-06/ghmc-citation-repair.json').write_text(json.dumps(audit,indent=2))
        r.clause_ref='22, item 7'
        s.flush()
    print(json.dumps(audit,indent=2))
