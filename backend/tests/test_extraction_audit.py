"""Quality warnings survive persistence and are shared by report/export callers."""
from types import SimpleNamespace
from app.api.quality import quality_for, provider_label
from app.schemas.notification import TenderNotification
from app.schemas.submission import VendorSubmission
from app.api.schemas import GapReportRequest


def documents():
    return TenderNotification(tender_id='T', title='Tender'), VendorSubmission(vendor_id='V', vendor_name='Vendor')


def test_original_failures_survive_revalidation():
    n, s = documents()
    nr = SimpleNamespace(extraction_metadata={'provider':'groq:test', 'extraction_errors':['technical: timed out'], 'parse_warnings':['page 9 unreadable']})
    sr = SimpleNamespace(extraction_metadata={'provider':'ollama:test', 'findings':[]})
    quality = quality_for(nr, n, sr, s)
    assert not quality.ok
    assert 'technical: timed out' in quality.banner
    assert 'page 9 unreadable' in quality.banner
    assert quality.providers == {'notification':'groq:test','bid':'ollama:test'}
    assert 'groq:test' in provider_label(quality) and 'ollama:test' in provider_label(quality)


def test_legacy_data_is_unknown_not_a_clean_extraction():
    n, _ = documents()
    quality = quality_for(SimpleNamespace(extraction_metadata={}), n)
    assert 'not recorded' in quality.banner
    assert quality.providers['notification'] is None


def test_identical_findings_are_not_duplicated():
    n, _ = documents()
    warning = dict(field='x', severity='warning', message='check x', value=None, affects_confidence=True)
    quality = quality_for(SimpleNamespace(extraction_metadata={'provider':'groq', 'findings':[warning,warning]}), n)
    assert sum(f.field == 'x' for f in quality.findings) == 1


def test_export_receives_the_same_audit_warning_and_provider(monkeypatch):
    from app.api import routes
    from app.compliance import export
    n, s = documents()
    nr = SimpleNamespace(id='n', extraction_metadata={'provider':'groq:test','extraction_errors':['technical: timed out']})
    sr = SimpleNamespace(extraction_metadata={'provider':'ollama:test'})
    monkeypatch.setattr(routes, 'require_notification', lambda *_:nr)
    monkeypatch.setattr(routes, 'require_submission', lambda *_:sr)
    monkeypatch.setattr(routes, 'to_notification_schema', lambda _:n)
    monkeypatch.setattr(routes, 'to_submission_schema', lambda _:s)
    monkeypatch.setattr(routes, 'staleness_for', lambda *_:SimpleNamespace(banner=None))
    captured=[]
    monkeypatch.setattr(export, 'export_pdf', lambda report,context:captured.append(context) or b'pdf')
    routes.export_gap_report(GapReportRequest(tender_id='T',vendor_id='V'),fmt='pdf',session=object(),user=SimpleNamespace(role='reviewer'))
    assert 'technical: timed out' in captured[0].data_quality_banner
    assert 'groq:test' in captured[0].extracted_by


def test_both_exports_carry_the_undetermined_count():
    from tests.test_export import _report, _pdf_strings, _docx_text
    from app.compliance.models import CheckStatus
    from app.compliance.export import export_pdf, export_docx
    report=_report()
    for item in report.items:
        item.status=CheckStatus.NOT_ASSESSABLE
    phrase=f'{report.completion.undetermined} not established either way'
    assert phrase in _pdf_strings(export_pdf(report))
    assert phrase in _docx_text(export_docx(report))
