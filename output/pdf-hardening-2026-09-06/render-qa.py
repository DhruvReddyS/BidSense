import sys
sys.path.insert(0,'backend')
from pathlib import Path
from app.compliance.export import export_pdf, export_docx, ExportContext
from tests.test_export import _report
from concurrent.futures import ThreadPoolExecutor
from docx import Document
from pypdf import PdfReader
import io, subprocess,json
root=Path('output/pdf'); report=_report()
report.vendor_name='निर्माण कंपनी — తెలుగు ₹5,00,000 Ω'
context=ExportContext(tender_title='Unicode proof <original & literal>')
(root/'unicode-export.pdf').write_bytes(export_pdf(report,context))
(root/'unicode-export.docx').write_bytes(export_docx(report,context))
dense=report.model_copy(deep=True)
dense.items=[report.items[i%len(report.items)].model_copy(update={'requirement':f'UNSEEN-{i:03d} Evidence requirement with a long identifier ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 / निर्माण कंपनी / తెలుగు', 'required_value':f'₹{i+1},00,000', 'found_value':f'FOUND-{i:03d} <source & literal>'},deep=True) for i in range(96)]
def render(fmt):
 payload=(export_pdf if fmt=='pdf' else export_docx)(dense,context)
 (root/f'dense-unseen-export.{fmt}').write_bytes(payload)
 return payload
with ThreadPoolExecutor(max_workers=2) as pool: pdf,docx=pool.map(render,['pdf','docx'])
text=subprocess.check_output(['pdftotext','-layout',str(root/'dense-unseen-export.pdf'),'-'],text=True)
doc=Document(io.BytesIO(docx));doctext=' '.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
for i in range(96):
 for marker in [f'UNSEEN-{i:03d}',f'FOUND-{i:03d}']:
  assert marker in text and marker in doctext,marker
raw=' '.join(subprocess.check_output(['pdftotext','-raw',str(root/'dense-unseen-export.pdf'),'-'],text=True).split())
assert '<source & literal>' in raw and '<source & literal>' in doctext
result={'rows':96,'pages':len(PdfReader(io.BytesIO(pdf)).pages),'all_unique_requirement_and_value_markers_in_both_formats':True,'parallel_formats':True}
Path('output/pdf-hardening-2026-09-06/dense-parity.json').write_text(json.dumps(result,indent=2))
print(result)
