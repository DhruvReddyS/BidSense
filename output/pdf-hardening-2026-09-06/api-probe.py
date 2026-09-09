"""Verify unsupported-text API behavior without mutating stored documents."""
import sys, json
sys.path.insert(0,'backend')
from unittest.mock import patch
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app.api.main import app
from app.api import routes
from app.schemas.notification import TenderNotification
from app.schemas.submission import VendorSubmission
n=TenderNotification(tender_id='PDF-QA',title='Tender')
s=VendorSubmission(vendor_id='PDF-QA-V',vendor_name='中文承包商')
nr=SimpleNamespace(id='qa',extraction_metadata={'provider':'test'})
sr=SimpleNamespace(extraction_metadata={'provider':'test'})
with patch.object(routes,'require_notification',return_value=nr),patch.object(routes,'require_submission',return_value=sr),patch.object(routes,'to_notification_schema',return_value=n),patch.object(routes,'to_submission_schema',return_value=s),patch.object(routes,'staleness_for',return_value=SimpleNamespace(banner=None)):
 with TestClient(app) as client:
  result=client.post('/api/gap-report/export?fmt=pdf',json={'tender_id':'PDF-QA','vendor_id':'PDF-QA-V'})
  assert result.status_code==422,(result.status_code,result.text)
  assert 'Export DOCX' in result.json()['detail']
  docx=client.post('/api/gap-report/export?fmt=docx',json={'tender_id':'PDF-QA','vendor_id':'PDF-QA-V'})
  assert docx.status_code==200 and docx.content[:2]==b'PK'
  print(json.dumps({'pdf_status':result.status_code,'detail':result.json()['detail'],'docx_status':docx.status_code},indent=2))
