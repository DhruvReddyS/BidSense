"""Vendor and tender specifications for synthetic bid generation (Section 9.2).

Section 9.2.1 is the load-bearing idea: **the compliance outcome is fixed before
the document is written**. Each VendorSpec therefore states `intended_status`
and `intended_reason` first; the prose is generated to match that intent. Doing
it the other way round produces documents with no answer key, and Section 10's
evaluation chapter then has nothing to measure against.

The distribution per tender follows Section 9.2.2:
  - fully compliant
  - missing exactly one mandatory document
  - below a numeric threshold
  - borderline (exactly at a threshold, or an expired certificate)
  - one blacklisted
and a mix of strong and weak technical write-ups, so the fluency-bias guard in
Section 5.4 has something to be tested against.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TenderProfile:
    """The real requirements a generated bid must speak to."""

    notification_id: str
    tender_ref: str
    authority: str
    authority_address: str
    work_title: str
    sector: str
    estimated_cost: str
    emd: str
    bid_due: str
    # Requirements taken from the actual extracted notification, so a generated
    # bid answers the clauses the pipeline will check it against.
    turnover_requirement: str
    experience_requirement: str
    key_documents: tuple[str, ...]
    technical_context: str
    # How long a bid for this tender should run. Proportionate to the tender's
    # value: a Rs. 12 lakh boundary wall does not attract a 200-page bid.
    bid_scale: str = "standard"


@dataclass
class VendorSpec:
    """One planned bid. Intent first, content second."""

    vendor_id: str
    notification_id: str
    vendor_name: str
    constitution: str
    city: str
    established: int
    intended_status: str            # 'pass' | 'eliminate'
    intended_reason: str
    intended_failed_clause: str
    writeup_quality: str            # 'strong' | 'weak'
    turnover: list[tuple[str, str]]
    net_worth: str
    bank_credit: str
    projects: list[dict]
    certifications: list[tuple[str, str]]
    quoted_price: str
    quoted_words: str
    omitted_documents: tuple[str, ...] = ()
    is_blacklisted: bool = False
    # Sits exactly on a threshold (Section 9.2.2). An off-by-one comparison --
    # ">" where the tender says "not less than" -- flips precisely these, and
    # nothing else in the set would catch it. Declared rather than inferred from
    # the notes, so a reworded note cannot silently drop the coverage.
    is_borderline: bool = False
    # How this bid names the documents it encloses (Section 6, document-name
    # matching). "as_printed" copies the tender's own wording, which is what a
    # generated corpus does by default and is precisely the problem: every name
    # then matches by string equality and the alias, lexical and embedding tiers
    # are never executed on real data. "alias" and "reworded" restate the names
    # the way a bidder actually would, so the matcher has to earn the match.
    # See app.bidgen.paraphrase.
    document_naming: str = "as_printed"
    notes: str = ""
    extra_declarations: list[str] = field(default_factory=list)

    @property
    def years_in_business(self) -> int:
        return 2025 - self.established
