"""Bids engineered to defeat the matcher, rather than bids that merely differ.

Everything else in this suite tests honest variation: a bidder who calls a GST
certificate something else, a tender that prints a requirement as a sentence.
This file tests the opposite assumption -- that someone is trying to be scored
as compliant without being compliant -- because that is the actual threat model
for a tool that decides whether a bid survives.

The four-tier matcher is where it bites. Tiers 3 and 4 exist to accept a
document under an unfamiliar name, and accepting things is exactly the behaviour
an adversary wants more of. Each test below names the attack and the property
that defeats it.

Nothing here requires the embedding model: every attack is aimed at the exact,
alias and lexical tiers, which are the ones that run without it. That is
deliberate -- an attack that only works when the model is unavailable is still
an attack.
"""

from __future__ import annotations

import pytest

from app.compliance.matching import (
    LEXICAL_CONTAINMENT,
    REVIEW_BAND_FLOOR,
    document_identifiers,
    match_document,
)


# --------------------------------------------------------------------------- #
# Collision: a document whose name is lexically adjacent to a different one.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("required,decoy", [
    ("PAN Card", "TAN Certificate"),
    ("TAN Certificate", "PAN Card"),
    ("ISO 9001 Certificate", "ISO 14001 Certificate"),
    ("Audited Balance Sheet", "Provisional Balance Sheet"),
    ("Class II Digital Signature Certificate", "Class III Digital Signature Certificate"),
])
def test_a_near_name_must_not_satisfy_a_different_document(required, decoy):
    """The attack: enclose the cheap document whose name is closest to the
    expensive one. These pairs are lexically and semantically close and are
    entirely different documents -- which is why the alias table exists rather
    than leaving short jargon strings to similarity alone."""
    result = match_document(required, [decoy])
    assert not result.matched, (
        f"{decoy!r} was accepted for {required!r} via {result.method} "
        f"at {result.score}"
    )


def test_a_decoy_may_be_offered_for_review_but_never_claimed():
    """Offering a near-miss is correct; claiming it is the failure."""
    result = match_document("Audited Balance Sheet", ["Provisional Balance Sheet"])
    assert not result.matched
    # Either outcome is acceptable, as long as nothing was declared present.
    if result.needs_review:
        assert result.review_candidate == "Provisional Balance Sheet"


# --------------------------------------------------------------------------- #
# Flooding: pad the enclosure list so something matches by accident.
# --------------------------------------------------------------------------- #

def test_padding_the_enclosure_list_does_not_manufacture_a_match():
    """The attack: submit fifty plausible-sounding titles and hope one is
    scored as the required document. Adding non-matching names must not change
    the verdict for a document that is genuinely absent."""
    padding = [
        f"Annexure {chr(65 + i)} — Supporting Statement {i}" for i in range(26)
    ] + [
        "Covering Letter", "Bid Form", "Price Schedule", "Technical Writeup",
        "Company Profile", "Client References", "Quality Policy",
        "Safety Policy", "Environmental Policy", "Organisation Chart",
    ]
    alone = match_document("Manufacturer Authorization Form", [])
    flooded = match_document("Manufacturer Authorization Form", padding)
    assert not alone.matched
    assert not flooded.matched, (
        f"padding produced a match via {flooded.method} at {flooded.score}"
    )


def test_a_genuine_document_still_matches_inside_a_padded_list():
    """The guard above must not be achieved by refusing long lists."""
    padding = [f"Annexure {i}" for i in range(40)]
    result = match_document(
        "GST Registration Certificate",
        [*padding, "GST Registration Certificate"],
    )
    assert result.matched and result.method == "exact"


# --------------------------------------------------------------------------- #
# Identifier stripping: claim a form by dropping the number that identifies it.
# --------------------------------------------------------------------------- #

def test_a_form_number_is_part_of_the_document_identity():
    """The attack: enclose "Annexure A" and claim it satisfies "Annexure C".
    Form references identify WHICH form, so they cannot be treated as noise."""
    result = match_document("Annexure C — Declaration of Debarment",
                            ["Annexure A — Declaration of Debarment"])
    assert not result.matched, (
        f"a different annexure was accepted via {result.method}"
    )


def test_identifiers_are_extracted_so_they_can_be_compared():
    assert document_identifiers("Annexure C — Declaration") != \
        document_identifiers("Annexure A — Declaration")
    assert document_identifiers("Form 10-B") != document_identifiers("Form 10-C")


def test_the_same_form_under_different_punctuation_still_matches():
    """The guard must not reject honest typography."""
    result = match_document("Annexure-C Declaration of Debarment",
                            ["Annexure C - Declaration of Debarment"])
    assert result.matched, f"honest variation rejected: {result.method}"


# --------------------------------------------------------------------------- #
# Negation: a bid that mentions a document in order to say it is absent.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("declaration", [
    "Manufacturer Authorization Form — not applicable",
    "Manufacturer Authorization Form: not enclosed",
    "We do not enclose the Manufacturer Authorization Form",
    "Manufacturer Authorization Form (to be submitted later)",
])
def test_naming_a_document_to_disclaim_it_is_not_enclosing_it(declaration):
    """The attack is often not even deliberate: a compliance table that lists
    every required document with "N/A" beside it contains every required name.
    A matcher that reads names without their disclaimer scores it as complete."""
    result = match_document("Manufacturer Authorization Form", [declaration])
    assert not result.matched, (
        f"a disclaimer was read as an enclosure via {result.method} "
        f"at {result.score}"
    )


# --------------------------------------------------------------------------- #
# Threshold probing: sit just inside whatever band is most permissive.
# --------------------------------------------------------------------------- #

def test_the_review_band_cannot_be_used_to_claim_a_document():
    """The review band's whole contract: below the threshold NOTHING is
    declared present. If a near-miss could ever set matched=True, an adversary
    would aim for the band rather than for compliance."""
    for required, submitted in [
        ("Certificate from the chartered accountant",
         "Certificate from the statutory auditor"),
        ("Compliance Sheet", "Clause-wise Compliance Statement"),
        ("Tender Processing Fee", "Evidence of payment of EMD"),
    ]:
        result = match_document(required, [submitted])
        if not result.matched:
            continue
        assert result.score is None or result.score >= REVIEW_BAND_FLOOR, (
            f"{submitted!r} claimed {required!r} at {result.score}, "
            f"below the review floor {REVIEW_BAND_FLOOR}"
        )


def test_lexical_containment_is_not_satisfied_by_a_single_shared_word():
    """The attack: name a document so it shares one identifying word with the
    requirement. Containment is a fraction for exactly this reason."""
    assert LEXICAL_CONTAINMENT >= 0.8, (
        "a low containment floor lets one shared word claim a document"
    )
    result = match_document("Solar Module Procurement Declaration",
                            ["Declaration"])
    assert not result.matched, f"a bare 'Declaration' matched via {result.method}"


# --------------------------------------------------------------------------- #
# Empty and degenerate input.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("submitted", [[], [""], ["   "], ["-"], ["N/A"]])
def test_nothing_satisfies_a_requirement(submitted):
    result = match_document("GST Registration Certificate", submitted)
    assert not result.matched


def test_an_empty_requirement_is_not_satisfied_by_anything():
    """A requirement that failed to extract must not be silently satisfied --
    that would turn an extraction gap into a clean bill of health."""
    for required in ("", "   "):
        result = match_document(required, ["GST Registration Certificate"])
        assert not result.matched, (
            "an unreadable requirement was reported as met"
        )
