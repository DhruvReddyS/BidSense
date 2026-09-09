"""An enclosure list cannot prove that bid narrative is absent."""
import pytest
from app.compliance.gap import build_gap_report
from app.compliance.models import CheckStatus, Severity
from app.schemas.notification import TenderNotification, MandatoryDocument
from app.schemas.submission import VendorSubmission, SubmittedDocument
from app.schemas.common import Provenance


def check(name, documents=()):
    notification = TenderNotification(tender_id='T', title='Tender',
        mandatory_documents=[MandatoryDocument(doc_name=name, provenance=Provenance(clause_ref='21', source_page=15))])
    submission = VendorSubmission(vendor_id='V', vendor_name='Vendor', documents_submitted=list(documents))
    return build_gap_report(notification, submission, use_embeddings=False).items[0]


@pytest.mark.parametrize('name', ['information on technical man power', 'contractors alternative technical proposals', 'Method statement', 'Key personnel details'])
def test_narrative_absence_is_not_inferred_from_enclosures(name):
    item = check(name)
    assert item.status is CheckStatus.NOT_ASSESSABLE
    assert item.severity is Severity.REVIEW
    assert 'enclosure' in item.explanation.lower()


def test_explicitly_missing_narrative_still_fails():
    name = 'Method statement'
    item = check(name, [SubmittedDocument(doc_name=name, present=False)])
    assert item.status is CheckStatus.MISSING
    assert item.severity is Severity.DISQUALIFYING


@pytest.mark.parametrize('name', ['Technical manpower certification', 'Manufacturer authorization certificate', 'GST Registration Certificate'])
def test_required_certificates_still_fail_when_absent(name):
    assert check(name).severity is Severity.DISQUALIFYING


def test_matched_document_preserves_bid_citation():
    provenance = Provenance(clause_ref='7.3', source_page=30, source_snippet='Named personnel are deployed for this work.')
    item = check('Method statement', [SubmittedDocument(doc_name='Method statement', present=True, provenance=provenance)])
    assert item.status is CheckStatus.MATCH
    assert item.submission_provenance == provenance


def test_unknown_narrative_action_asks_for_review_not_rewriting():
    from app.compliance.gap import _build_action_list
    from app.compliance.models import ActionGroup

    action = _build_action_list([check('Method statement')])[0]
    assert action.group is ActionGroup.VERIFY
    assert action.action.startswith('Review the relevant section of your bid')
