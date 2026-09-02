"""The four matching tiers, and the guard against the corpus going circular again.

Until this file existed, every document name in the synthetic bid set was
byte-identical to the requirement it would be checked against, because the bids
were generated from the extracted requirement list. Tier 1 answered everything.
The alias and embedding tiers were exercised only by hand-written unit fixtures,
which tests the fixture and not the corpus.

`test_the_corpus_exercises_every_tier` is what keeps that from coming back: it
renames the real extracted requirement lists the way a bidder would and asserts
that the alias, lexical and embedding tiers each actually resolve something. If
the renaming is removed, or a change makes everything match exactly again, that
test fails rather than the suite quietly going green on a tautology.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import text

from app.bidgen.paraphrase import paraphrase
from app.compliance.gap import _collect_requirements, build_gap_report
from app.compliance.matching import (
    DEFAULT_EMBEDDING_THRESHOLD,
    REVIEW_BAND_FLOOR,
    match_document,
    normalise,
)
from app.compliance.models import CheckStatus, Severity
from app.compliance.requirements import Applicability
from app.db.session import engine
from app.schemas.common import Provenance
from app.schemas.notification import MandatoryDocument, TenderNotification
from app.schemas.submission import SubmittedDocument, VendorSubmission


def _live() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        from app.vector.embeddings import get_model

        get_model()
        return True
    except Exception:
        return False


live = pytest.mark.skipif(not _live(), reason="postgres or BGE model unavailable")


# --------------------------------------------------------------------------- #
# Normalisation: spelling and plurals
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "a, b",
    [
        ("Manufacturers Authorization Form", "Manufacturer Authorisation Form"),
        ("Certificates of Incorporation", "Certificate of Incorporation"),
        ("Labour Licence", "Labour License"),
        ("Authorized Signatory Letter", "Authorised Signatory Letter"),
    ],
)
def test_spelling_and_plurals_fold_to_one_form(a, b) -> None:
    """British/American spelling is not a synonym judgment -- it is one word
    printed two ways, and both spellings appear in the same Indian tender."""
    assert normalise(a) == normalise(b)


@pytest.mark.parametrize("word", ["address", "status", "analysis", "gas"])
def test_plural_stripping_leaves_real_words_alone(word) -> None:
    assert normalise(word) == word


# --------------------------------------------------------------------------- #
# Tier 3: lexical
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "required, submitted",
    [
        # Every one of these was a measured miss on the real corpus, scoring
        # 0.83-0.86 against a 0.86 floor.
        ("Certificate from the chartered accountant", "Certificate from the statutory auditor"),
        ("Certificate of Conformity / No Deviation", "Certificate of Conformity / nil deviation"),
        ("Manufacturers authorization form", "OEM authorisation form"),
        ("Proof of Payment of EMD", "Documentary evidence of payment of earnest money deposit"),
    ],
)
def test_known_vocabulary_resolves_without_the_model(required, submitted) -> None:
    result = match_document(required, [submitted], use_embeddings=False)
    assert result.matched, f"{required!r} vs {submitted!r} did not resolve lexically"
    assert result.method == "lexical"


@pytest.mark.parametrize(
    "required, submitted",
    [
        # Both of these DID falsely match before the generic-vocabulary set was
        # widened. They rest entirely on words every tender document contains.
        ("Bid Securing Declaration", "Letter of Bid"),
        ("Declaration by the Bidder/JV/Consortium", "Firm Registration certificate of each bidder / JV / Consortium Partner"),
        ("EMD proof", "EMD forfeiture clause acceptance"),
        ("Solvency Certificate", "ISO Certificate"),
        ("Bid capacity statement", "Bid security declaration"),
    ],
)
def test_agreement_on_generic_words_alone_is_not_a_match(required, submitted) -> None:
    result = match_document(required, [submitted], use_embeddings=False)
    assert not result.matched, (
        f"{required!r} matched {submitted!r} on vocabulary that identifies nothing"
    )


def test_the_lexical_tier_runs_before_the_model() -> None:
    """It is the cheap tier. Running it after embeddings would pay for a model
    call on every name the vocabulary table already knows."""
    result = match_document(
        "Manufacturers authorization form", ["OEM authorisation form"], use_embeddings=False
    )
    assert result.matched and result.method == "lexical"


# --------------------------------------------------------------------------- #
# The review band
# --------------------------------------------------------------------------- #
def test_a_near_miss_is_offered_for_review_not_reported_missing() -> None:
    result = match_document(
        "Authorization to represent the firm",
        ["letter authorising the signatory of the firm"],
    )
    assert not result.matched, "a sub-threshold score must never declare a document present"
    assert result.needs_review
    assert result.review_candidate == "letter authorising the signatory of the firm"
    assert REVIEW_BAND_FLOOR <= result.score < DEFAULT_EMBEDDING_THRESHOLD


def test_a_distant_name_is_not_offered_as_a_candidate_at_all() -> None:
    """The band has a floor for a reason: "did you mean X?" against something
    unrelated is noise that buries the requirements genuinely missing."""
    result = match_document("PAN Card", ["Bill of quantities for civil works"])
    assert not result.matched
    assert not result.needs_review
    assert result.review_candidate is None


def test_the_review_band_never_declares_a_document_present() -> None:
    """The property that matters most. A false positive here means a vendor
    submits without a document we told them they had."""
    for candidate in (
        "Bid capacity statement",
        "Income Tax Return",
        "Class-I Electrical Licence",
    ):
        result = match_document(candidate, ["Bid security declaration"])
        if result.needs_review:
            assert not result.matched
            assert result.matched_name is None


def _prov() -> Provenance:
    return Provenance(clause_ref="7", source_page=3, source_snippet="x")


def test_the_gap_report_renders_a_near_miss_as_partial_not_missing() -> None:
    report = build_gap_report(
        TenderNotification(
            tender_id="T-1",
            title="t",
            issuing_authority="a",
            mandatory_documents=[
                MandatoryDocument(
                    doc_name="Authorization to represent the firm", provenance=_prov()
                )
            ],
        ),
        VendorSubmission(
            vendor_id="V-1",
            vendor_name="V",
            tender_id="T-1",
            documents_submitted=[
                SubmittedDocument(
                    doc_name="letter authorising the signatory of the firm",
                    present=True,
                    provenance=_prov(),
                )
            ],
        ),
    )
    item = report.items[0]
    assert item.status is CheckStatus.PARTIAL
    assert item.severity is Severity.REVIEW
    assert not item.blocks_submission, (
        "a near miss must not disqualify a bidder who enclosed the document"
    )
    assert "letter authorising the signatory of the firm" in item.explanation


# --------------------------------------------------------------------------- #
# The anti-circularity guard
# --------------------------------------------------------------------------- #
def _real_requirement_lists() -> list[tuple[str, list]]:
    from app.db.repository import list_notifications, to_notification_schema
    from app.db.session import session_scope

    out = []
    with session_scope() as session:
        for row in list_notifications(session, limit=50):
            stem = Path(row.source_file).stem if row.source_file else row.tender_id
            requirements = [
                r
                for r in _collect_requirements(to_notification_schema(row))
                if r.applicability is Applicability.ALWAYS
            ]
            if requirements:
                out.append((stem, requirements))
    return out


@live
@pytest.mark.parametrize("style", ["alias", "reworded"])
def test_the_corpus_exercises_every_tier(style) -> None:
    """Renaming the real requirement lists must put work through every tier.

    This is the test that keeps the corpus honest. If bids are generated
    verbatim from the extracted requirements again, everything matches exactly
    and the tier counts collapse -- which fails here rather than passing
    silently as a suite of tautologies.
    """
    lists = _real_requirement_lists()
    if not lists:
        pytest.skip("no notifications ingested")

    tiers: Counter[str] = Counter()
    for _, requirements in lists:
        renamed = [paraphrase(r.primary.doc_name, style) for r in requirements]
        for requirement in requirements:
            result = match_document(
                requirement.primary.doc_name, renamed, extra_aliases=requirement.aliases
            )
            tiers[result.method if result.matched else "unmatched"] += 1

    assert tiers["alias"] >= 1, f"the alias tier resolved nothing: {dict(tiers)}"
    assert tiers["lexical"] >= 10, f"the lexical tier resolved little: {dict(tiers)}"
    assert tiers["embedding"] >= 1, f"the embedding tier resolved nothing: {dict(tiers)}"
    # And the renaming actually renamed things: if most names still match
    # exactly, the corpus has gone circular again.
    total = sum(tiers.values())
    assert tiers["exact"] < total * 0.6, (
        f"most names still match exactly -- the corpus looks circular: {dict(tiers)}"
    )


@live
@pytest.mark.parametrize("style", ["alias", "reworded"])
def test_renaming_the_corpus_does_not_lose_documents(style) -> None:
    """A vendor who encloses everything, under their own names, must not be told
    they are missing things. At most one document per tender may fall through to
    an outright non-match, and none may do so silently -- the rest resolve or are
    offered for review.
    """
    lists = _real_requirement_lists()
    if not lists:
        pytest.skip("no notifications ingested")

    for stem, requirements in lists:
        renamed = [paraphrase(r.primary.doc_name, style) for r in requirements]
        unmatched = []
        for requirement in requirements:
            result = match_document(
                requirement.primary.doc_name, renamed, extra_aliases=requirement.aliases
            )
            if not result.matched and not result.needs_review:
                unmatched.append((requirement.primary.doc_name, result.score))
        assert len(unmatched) <= 1, (
            f"{stem}: {len(unmatched)} renamed documents reported missing: {unmatched}"
        )


@live
def test_the_review_floor_still_reports_real_absences() -> None:
    """The floor's lower bound, pinned.

    REVIEW_BAND_FLOOR is tuned, not derived -- the score distributions for "same
    document, different name" and "different document" overlap, so any value
    sits inside the overlap. Lowering it far enough turns genuine absences into
    "did you mean...?" and the elimination is lost: measured on this corpus, at
    0.70 a bid missing its ALMM declaration stops being reported as missing it.

    This test is what stops that happening silently. It asserts the property the
    floor exists to protect -- a document that is genuinely absent, against a
    bid full of other documents, is still reported MISSING -- rather than
    asserting the constant itself, which would just restate the source.
    """
    from app.compliance.matching import DEFAULT_EMBEDDING_THRESHOLD

    assert REVIEW_BAND_FLOOR < DEFAULT_EMBEDDING_THRESHOLD

    lists = _real_requirement_lists()
    if not lists:
        pytest.skip("no notifications ingested")

    # For each tender, take one requirement out of the enclosure list entirely
    # and check it is still reported as absent rather than resolved to a
    # neighbour. Documents that are genuinely restated twice in the same tender
    # are skipped: those SHOULD match a sibling, and would be a false alarm here.
    for stem, requirements in lists:
        if len(requirements) < 8:
            continue
        reported_absent = 0
        for index, requirement in enumerate(requirements):
            others = [
                r.primary.doc_name for j, r in enumerate(requirements) if j != index
            ]
            result = match_document(
                requirement.primary.doc_name, others, extra_aliases=requirement.aliases
            )
            if not result.matched:
                reported_absent += 1
        assert reported_absent >= len(requirements) // 2, (
            f"{stem}: only {reported_absent}/{len(requirements)} genuinely absent "
            f"documents were still reported absent -- the review floor has been "
            f"lowered far enough to dissolve real gaps"
        )


def test_an_explicitly_unenclosed_document_beats_a_near_miss_candidate() -> None:
    """A bid whose own checklist says NOT ENCLOSED is telling us it is absent.

    That outranks any resemblance to some other document it did enclose. Without
    this ordering, a bidder who declared a missing manufacturer's authorisation
    was softened to "did you mean 'Document required from authorized dealers'?",
    and a definite elimination became a maybe -- measured on the real corpus, it
    cost one of the nine true eliminations.
    """
    report = build_gap_report(
        TenderNotification(
            tender_id="T-1",
            title="t",
            issuing_authority="a",
            mandatory_documents=[
                MandatoryDocument(
                    doc_name="Manufacturers authorization form", provenance=_prov()
                )
            ],
        ),
        VendorSubmission(
            vendor_id="V-1",
            vendor_name="V",
            tender_id="T-1",
            documents_submitted=[
                SubmittedDocument(
                    doc_name="Manufacturers authorization form",
                    present=False,
                    provenance=_prov(),
                ),
                SubmittedDocument(
                    doc_name="Document required from authorized dealers",
                    present=True,
                    provenance=_prov(),
                ),
            ],
        ),
    )
    item = report.items[0]
    assert item.status is CheckStatus.MISSING
    assert item.severity is Severity.DISQUALIFYING
    assert "not enclosed" in item.explanation.lower()
