from decimal import Decimal
from types import SimpleNamespace

from app.review.workflow import build_candidate, choose_shortlist, classify_query, structured_answer
from app.review.export import export_docx, export_pdf


def row(vendor_id, *, years=0, project=None, price=None, technical=False, status="pending", reason=None):
    projects = [] if project is None else [SimpleNamespace(value_inr=Decimal(project))]
    return SimpleNamespace(
        vendor_id=vendor_id,
        vendor_name=f"Vendor {vendor_id}",
        years_in_business=years,
        past_projects=projects,
        quoted_price_inr=Decimal(price) if price is not None else None,
        has_technical_approach=technical,
        status=SimpleNamespace(value=status),
        elimination_reason=reason,
    )


def test_shortlist_is_bounded_unranked_and_alphabetical():
    candidates = [build_candidate(row("C", years=3)), build_candidate(row("A", years=9)), build_candidate(row("B", years=6))]
    chosen = choose_shortlist(candidates, 2, {"experience": 1})
    assert [candidate.vendor_id for candidate in chosen] == ["A", "B"]


def test_missing_values_do_not_become_best_price():
    candidates = [build_candidate(row("A", price=None)), build_candidate(row("B", price="100")), build_candidate(row("C", price="200"))]
    assert [c.vendor_id for c in choose_shortlist(candidates, 1, {"pricing": 1})] == ["B"]


def test_router_keeps_audit_and_narrative_distinct():
    assert classify_query("Why was Vendor A eliminated?") == "audit"
    assert classify_query("Which approach addresses scalability?") == "qualitative"
    assert classify_query("Compare shortlisted vendors on experience and approach") == "hybrid"
    assert classify_query("Compare vendors on experience") == "comparative"


def test_audit_answer_uses_persisted_reason():
    candidate = build_candidate(row("A", status="eliminated", reason="Below threshold"))
    answer = structured_answer("Why was Vendor A eliminated?", [candidate], {"A": "eliminated"}, {"A": "Below threshold"})
    assert "Below threshold" in answer


def test_committee_exports_are_real_documents():
    notification = SimpleNamespace(title="Tender", tender_id="T/1", issuing_authority="Authority")
    candidate = row("A", status="eliminated", reason="Below threshold")
    candidate.elimination_clause_ref = "4.2"
    candidate.elimination_source_page = 7
    assert export_pdf(notification, [candidate]).startswith(b"%PDF")
    assert export_docx(notification, [candidate]).startswith(b"PK")
