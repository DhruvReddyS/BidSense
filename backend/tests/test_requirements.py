"""Requirement deduplication and conditional detection.

Both behaviours were driven by the real GHMC tender: 65 extracted document
requirements, of which 9 groups were restatements of the same document and 9
applied only to joint ventures.
"""

from __future__ import annotations

import pytest

from app.compliance.requirements import (
    Applicability,
    canonical_key,
    classify_applicability,
    deduplicate,
    shorten,
)
from app.schemas.common import Provenance
from app.schemas.notification import MandatoryDocument


def doc(name: str, clause: str | None = None) -> MandatoryDocument:
    return MandatoryDocument(
        doc_name=name, provenance=Provenance(clause_ref=clause)
    )


# --------------------------------------------------------------------------- #
# Canonical identity
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Power of Attorney", "Submission of Power of Attorney"),
        ("Power of Attorney", "Copy of Power of Attorney"),
        ("PAN Card", "Photocopy of PAN card"),
        (
            "Completion Certificates of works",
            "Completion Certificates of works which have been cited in support of "
            "fulfillment of eligibility criteria as specified in Tender Document.",
        ),
        ("GST Registration Certificate", "Copy of GST registration"),
    ],
)
def test_restatements_collapse_to_one_key(a: str, b: str) -> None:
    """Real tenders state the same requirement in several clauses. Extracted
    verbatim from each, a vendor who uploaded it once still sees red rows."""
    assert canonical_key(a) == canonical_key(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("PAN Card", "TAN Certificate"),
        ("Form FIN-1", "Form FIN-2"),
        ("Audited Balance Sheet", "Bid Securing Declaration"),
    ],
)
def test_different_documents_keep_different_keys(a: str, b: str) -> None:
    assert canonical_key(a) != canonical_key(b)


def test_deduplicate_keeps_one_row_per_requirement():
    requirements = deduplicate([
        doc("Power of Attorney", "5.1"),
        doc("Submission of Power of Attorney", "22"),
        doc("Copy of Power of Attorney duly attested", None),
        doc("PAN Card", "5.2"),
    ])
    assert len(requirements) == 2
    poa = next(r for r in requirements if "Attorney" in r.label)
    assert len(poa.sources) == 3
    assert "5.1" in poa.clause_refs and "22" in poa.clause_refs


def test_the_most_specific_statement_is_cited():
    """A numbered clause beats an unnumbered mention as the citation."""
    requirements = deduplicate([
        doc("Copy of Power of Attorney duly attested and notarised", None),
        doc("Power of Attorney", "5.1"),
    ])
    assert requirements[0].primary.provenance.clause_ref == "5.1"


def test_every_phrasing_is_kept_as_an_alias():
    """Name matching has more to work with when it knows every phrasing used."""
    requirements = deduplicate([
        doc("GST Registration Certificate", "5.1"),
        doc("Copy of GST registration", "22"),
    ])
    assert len(requirements) == 1
    assert any("GST registration" in a for a in requirements[0].aliases)


# --------------------------------------------------------------------------- #
# Applicability
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name",
    [
        "Joint Venture Agreement",
        "JV / Consortium Agreement",
        "letter of intent to form JV / Consortium",
        "Authorization to represent the firm or JV / Consortium",
    ],
)
def test_joint_venture_documents_are_conditional(name: str) -> None:
    """Flagging these against a sole bidder produced 22 disqualifying rows on a
    bid that was fine on those grounds, burying the one real failure."""
    assert classify_applicability(name) is Applicability.JOINT_VENTURE


@pytest.mark.parametrize(
    "name",
    [
        "Photocopy of PAN card",
        "Audited Balance Sheets",
        "Proof of Payment of EMD",
        "Certificate of Incorporation",
        # Names the JV but binds every bidder: "each bidder / JV / Consortium".
        "Firm Registration certificate of each bidder / JV / Consortium Partner",
    ],
)
def test_universal_documents_stay_mandatory(name: str) -> None:
    """Ambiguity resolves to ALWAYS: under-flagging a real requirement is worse
    than showing one extra row."""
    assert classify_applicability(name) is Applicability.ALWAYS


def test_concession_documents_are_conditional():
    assert classify_applicability("MSME registration certificate, if claimed") is (
        Applicability.CONCESSION
    )
    assert classify_applicability("Udyam registration for MSE preference") is (
        Applicability.CONCESSION
    )


def test_explicitly_conditional_wording_is_detected():
    assert classify_applicability("Power of Attorney, if applicable") is (
        Applicability.CONDITIONAL
    )


def test_one_unconditional_statement_makes_a_requirement_binding():
    """If any clause demands it outright, it binds -- regardless of a softer
    restatement elsewhere."""
    requirements = deduplicate([
        doc("Power of Attorney, if applicable", "22"),
        doc("Power of Attorney", "5.1"),
    ])
    assert requirements[0].applicability is Applicability.ALWAYS


# --------------------------------------------------------------------------- #
# Display names
# --------------------------------------------------------------------------- #
def test_over_captured_names_are_shortened_for_display():
    long_name = (
        "Completion Certificates of works which have been cited in support of "
        "fulfillment of eligibility criteria as specified in Tender Document."
    )
    label = shorten(long_name)
    assert len(label) <= 92
    assert label.startswith("Completion Certificates")


def test_short_names_are_left_alone():
    assert shorten("PAN Card") == "PAN Card"


def test_leading_verbs_are_trimmed():
    assert shorten("Submission of Power of Attorney") == "Power of Attorney"
    assert shorten("Copy of GST registration") == "GST registration"
