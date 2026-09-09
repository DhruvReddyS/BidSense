"""Unicode output must preserve source text, not merely draw recognizable glyphs."""
import io
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from docx import Document
import pytest
from app.compliance.export import export_pdf, export_docx
from app.compliance.pdf_fonts import UnsupportedPDFText, fetch_font
from tests.test_export import _report


def recovered_pdf(payload, path):
 path.write_bytes(payload)
 return ' '.join(subprocess.check_output(['pdftotext','-layout',str(path),'-'],text=True).split())


def test_indic_and_currency_text_survive_copy_and_both_formats(tmp_path):
 report=_report();report.vendor_name='निर्माण कंपनी — తెలుగు ₹5,00,000 Ω'
 pdf=recovered_pdf(export_pdf(report),tmp_path/'unicode.pdf')
 doc=Document(io.BytesIO(export_docx(report)))
 docx=' '.join(c.text for table in doc.tables for row in table.rows for c in row.cells)
 assert report.vendor_name in pdf
 assert report.vendor_name in docx
 assert '?' not in pdf


def test_unsupported_script_is_rejected_instead_of_corrupted():
 report=_report();report.vendor_name='中文承包商'
 with pytest.raises(UnsupportedPDFText,match='Export DOCX'):
  export_pdf(report)


def test_renderer_cannot_fetch_external_resources():
 with pytest.raises(ValueError):fetch_font('https://example.com/private')
 with pytest.raises(ValueError):fetch_font('file:///etc/passwd')


def test_concurrent_font_subsets_keep_each_vendor_separate(tmp_path):
 names=['निर्माण कंपनी','తెలుగు సంస్థ','Müller & Söhne','Κύπρος Кирилл']
 def run(index):
  report=_report();report.vendor_name=f'{names[index]} VENDOR-{index}'
  text=recovered_pdf(export_pdf(report),tmp_path/f'{index}.pdf')
  assert report.vendor_name in text
  assert all(f'VENDOR-{other}' not in text for other in range(4) if other!=index)
 with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(run,range(4)))
