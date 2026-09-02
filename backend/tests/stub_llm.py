"""A scripted LLMProvider for testing the extraction graph without an API key.

Returns canned, schema-valid answers keyed by the output model. This tests the
orchestration, conversion and persistence layers deterministically; extraction
*accuracy* against a real model is measured separately (Section 10) and needs a
real API key.
"""

from __future__ import annotations

from app.extraction import llm_schemas as raw
from app.llm.base import LLMError, LLMProvider
from tests.doc_factory import NOTIFICATION_TRUTH


class StubLLM(LLMProvider):
    """Answers from a fixed script. `fail_on` forces chosen nodes to raise, so
    the graph's partial-failure behaviour can be tested."""

    name = "stub"

    def __init__(self, fail_on: set[str] | None = None, script: dict | None = None):
        self.fail_on = fail_on or set()
        self.calls: list[str] = []
        self.script = script or _default_script()

    def generate_text(self, prompt: str, *, system: str | None = None) -> str:
        return "stub"

    def generate_structured(self, prompt, schema, *, system=None):
        key = schema.__name__
        self.calls.append(key)
        if key in self.fail_on:
            raise LLMError(f"stub forced failure for {key}")
        if key not in self.script:
            raise LLMError(f"stub has no scripted answer for {key}")
        return self.script[key]


def _default_script() -> dict:
    t = NOTIFICATION_TRUTH
    return {
        "RawHeader": raw.RawHeader(
            tender_id=t["tender_id"],
            title=t["title"],
            issuing_authority=t["issuing_authority"],
            sector="IT services",
            submission_deadline=t["submission_deadline"],
            pre_bid_query_deadline=t["pre_bid_deadline"],
            emd_amount_raw="Rs. 2,00,000",
            contract_value_raw="Rs. 12,50,00,000",
        ),
        "EligibilityList": raw.EligibilityList(
            items=[
                raw.RawEligibilityCriterion(
                    criterion="Average annual turnover over last three financial years",
                    type="numeric",
                    threshold_raw="Rs. 5 Cr",
                    unit="INR",
                    clause_ref="4.2",
                    source_page=2,
                    source_snippet=(
                        "The bidder shall have an average annual turnover of not less "
                        "than Rs. 5 Cr (Rupees Five Crore only)"
                    ),
                ),
                raw.RawEligibilityCriterion(
                    criterion="Years of experience in enterprise networking",
                    type="numeric",
                    threshold_raw="5 (five) years",
                    unit="years",
                    clause_ref="4.3",
                    source_page=2,
                    source_snippet="a minimum of 5 (five) years of experience",
                ),
                raw.RawEligibilityCriterion(
                    criterion="Not blacklisted or debarred by any government body",
                    type="boolean",
                    clause_ref="4.5",
                    source_page=2,
                    source_snippet="shall not be blacklisted or debarred",
                ),
            ]
        ),
        "DocumentList": raw.DocumentList(
            items=[
                raw.RawMandatoryDocument(doc_name=name, clause_ref="5.1", source_page=3)
                for name in t["mandatory_docs"]
            ]
        ),
        # This notification publishes no weightage -- Section 4.4's honesty case.
        "EvaluationList": raw.EvaluationList(items=[]),
        "TechnicalList": raw.TechnicalList(
            items=[
                raw.RawTechnicalRequirement(
                    requirement="Switches shall support IEEE 802.3az",
                    clause_ref="6.1",
                    source_page=3,
                ),
                raw.RawTechnicalRequirement(
                    requirement="Three years on-site warranty and support",
                    clause_ref="6.2",
                    source_page=3,
                ),
            ]
        ),
        "FormatRuleList": raw.FormatRuleList(
            items=[
                raw.RawSubmissionFormatRule(
                    rule="Two separate sealed envelopes, Technical and Financial",
                    clause_ref="7.1",
                    source_page=3,
                ),
                raw.RawSubmissionFormatRule(
                    rule="Every page serially numbered, signed and sealed",
                    clause_ref="7.2",
                    source_page=3,
                ),
            ]
        ),
        # --- vendor side ---
        "RawVendorHeader": raw.RawVendorHeader(
            vendor_name="Delta Systems Pvt Ltd",
            years_in_business=8.5,
            pricing_summary="Total quoted price inclusive of taxes",
            quoted_price_raw="Rs. 11,80,00,000",
            technical_approach_text=(
                "Our delivery methodology follows a four-phase rollout beginning "
                "with a site survey across all twelve district offices."
            ),
            declared_debarment=None,
        ),
        "TurnoverList": raw.TurnoverList(
            items=[
                raw.RawTurnover(year="2022-23", amount_raw="Rs. 3.8 Cr", source_page=2),
                raw.RawTurnover(year="2023-24", amount_raw="Rs. 4.2 Cr", source_page=2),
                raw.RawTurnover(year="2024-25", amount_raw="as per annexure IV", source_page=2),
            ]
        ),
        "CertificationList": raw.CertificationList(
            items=[
                raw.RawCertification(
                    name="ISO 9001:2015", valid_till="2027-06-30", doc_present=True
                ),
                raw.RawCertification(name="GST Registration", doc_present=True),
            ]
        ),
        "PastProjectList": raw.PastProjectList(
            items=[
                raw.RawPastProject(
                    client="Andhra Pradesh Technology Services",
                    value_raw="Rs. 2.4 Cr",
                    year=2023,
                    description="Campus network refresh across 40 sites.",
                )
            ]
        ),
        "SubmittedDocumentList": raw.SubmittedDocumentList(
            items=[
                raw.RawSubmittedDocument(doc_name="GST Registration Certificate"),
                raw.RawSubmittedDocument(doc_name="PAN Card"),
                raw.RawSubmittedDocument(
                    doc_name="ISO 9001:2015 Certificate", present=False
                ),
            ]
        ),
    }
