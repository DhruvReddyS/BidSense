"""Similar titles do not make differently numbered tender forms interchangeable."""
import pytest
from app.compliance.matching import match_document
from app.compliance.requirements import canonical_key, deduplicate
from app.compliance.gap import build_gap_report
from app.schemas.notification import TenderNotification, MandatoryDocument
from app.schemas.submission import VendorSubmission, SubmittedDocument
from app.compliance.models import CheckStatus

@pytest.mark.parametrize('left,right', [
 ('Process Compliance Statement (Annexure-B)', 'Process Compliance Statement (Annexure-II)'),
 ('Declaration as per Form F-12', 'Declaration as per Form F-14'),
 ('Evidence of satisfactory performance for completed projects (Appendix A)', 'Evidence of satisfactory performance for completed projects (Appendix B)'),
])
def test_identifiers_survive_deduplication(left,right):
 assert canonical_key(left)!=canonical_key(right)
 assert len(deduplicate([MandatoryDocument(doc_name=left),MandatoryDocument(doc_name=right)]))==2

@pytest.mark.parametrize('embeddings',[False,True])
def test_conflicting_annexures_cannot_match_even_with_high_similarity(embeddings,monkeypatch):
 monkeypatch.setattr('app.compliance.matching._best_embedding_match',lambda *args:('Process Compliance Statement (Annexure-B)',0.99))
 result=match_document('Process Compliance Statement (Annexure-II)',['Process Compliance Statement (Annexure-B)'],use_embeddings=embeddings)
 assert not result.matched
 assert not result.needs_review


def test_sbi_missing_annexure_survives_present_related_form():
 names=['Process Compliance Statement (Annexure-B)','Process Compliance Statement (Annexure-II)']
 n=TenderNotification(tender_id='T',title='Tender',mandatory_documents=[MandatoryDocument(doc_name=x) for x in names])
 s=VendorSubmission(vendor_id='V',vendor_name='Vendor',documents_submitted=[SubmittedDocument(doc_name=names[0],present=True),SubmittedDocument(doc_name=names[1],present=False),SubmittedDocument(doc_name='Process compliance form',present=True)])
 report=build_gap_report(n,s,use_embeddings=False)
 assert len(report.items)==2
 assert report.items[0].status is CheckStatus.MATCH
 assert report.items[1].status is CheckStatus.MISSING
 assert report.items[1].blocks_submission


def test_same_form_remains_a_match():
 assert match_document('Process Compliance Statement (Annexure-II)',['Process Compliance Statement (Annexure-II)'],use_embeddings=False).matched
 assert canonical_key('Power of Attorney (if applicable)')==canonical_key('Power of Attorney')


def test_generic_title_cannot_establish_the_requested_annexure(monkeypatch):
 monkeypatch.setattr('app.compliance.matching._best_embedding_match',lambda *args:('Process compliance form',0.99))
 result=match_document('Process Compliance Statement (Annexure-II)',['Process compliance form'])
 assert not result.matched
 assert result.needs_review


def test_declared_absence_beats_a_positive_lexical_candidate():
 n=TenderNotification(tender_id='T',title='Tender',mandatory_documents=[MandatoryDocument(doc_name='Technical approach methodology')])
 s=VendorSubmission(vendor_id='V',vendor_name='Vendor',documents_submitted=[SubmittedDocument(doc_name='Technical approach methodology',present=False),SubmittedDocument(doc_name='Detailed technical approach methodology',present=True)])
 # Without the explicit declaration this title is a positive lexical match.
 assert match_document('Technical approach methodology',['Detailed technical approach methodology'],use_embeddings=False).matched
 item=build_gap_report(n,s,use_embeddings=False).items[0]
 assert item.status is CheckStatus.MISSING
 assert item.blocks_submission


def test_declared_absence_tolerates_trailing_table_extraction_noise():
 n=TenderNotification(tender_id='T',title='Tender',mandatory_documents=[MandatoryDocument(doc_name='Process Compliance Statement (Annexure-II)')])
 s=VendorSubmission(vendor_id='V',vendor_name='Vendor',documents_submitted=[SubmittedDocument(doc_name='Process Compliance Statement (Annexure-II) E',present=False),SubmittedDocument(doc_name='Process compliance form',present=True)])
 item=build_gap_report(n,s,use_embeddings=False).items[0]
 assert item.status is CheckStatus.MISSING
 assert item.blocks_submission
