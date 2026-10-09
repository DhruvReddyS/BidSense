"""Verify extracted clause references against the source document.

The product's central claim is that nothing is asserted without a clause and a
page behind it. A citation that names a clause the document does not contain
breaks that claim more quietly than a wrong value does: the number looks
checkable, a reviewer goes to look it up, and it is not there.

This is a real, measured failure. On the HGCL tender the source prints

    28.1 The Chief General Manager will evaluate whether each Tenderer ...
    vi) Liquid assets and/ or credit facilities of not less than Rs.49.855 Crores

and every sub-clause came back from extraction as "2.8.1 (iv)", "2.8.1 (vi)",
"2.8.1 (vii)" -- a spurious dot, applied consistently, so nothing downstream
looked anomalous. The elimination was correct and its citation was not, and the
only reason it surfaced at all was an answer key that happened to disagree.

NOT WIRED INTO THE VALIDATION PASS, AND THAT IS A MEASURED DECISION. Pointed at
the real corpus this flagged 20 of civilworks_01's citations and 19 of
civilworks_02's, which is noise, not twenty findings. Two reasons, both of them
limitations of THIS module rather than of the idea:

  * `_REFERENCE` matches any number, so a 236,000-character tender yields 246
    "references" of which most are amounts and dates ("0.973", "000.00").
    `is_present` is therefore far too easy to satisfy, and `suggest_correction`
    too often finds several colliding candidates and stays silent.
  * Some cited references genuinely are not in the document in any form --
    civilworks_01 contains neither "1.1 (4)" nor "1.1(4)" -- so the model is
    composing a reference from a section number and a list item. That is a real
    defect, but distinguishing it from a formatting difference needs a
    structure-aware extractor that reads line-leading numbering, not a regex
    over flat text.

A correct version would extract references from document STRUCTURE. Until then
this module is a tested utility with a known false-positive rate, used
deliberately rather than run on every ingest.

THE DEFECT IT WAS BUILT FOR IS REAL AND STILL OPEN. The HGCL source prints
"28.1"; extraction returns "2.8.1 (i)" through "2.8.1 (ix)" -- consistently, so
nothing downstream looks anomalous. Reproduced in tests/test_clause_check.py.

WHY DETECT AND NOT AUTO-CORRECT. Rewriting a stored citation to whichever
source reference it resembles would make the evaluation number improve without
the underlying extraction getting any better, and provenance is the last thing
in this system that should be quietly adjusted to fit. So a reference that
cannot be found is reported, with the near-miss named so a human can judge it.
`suggest_correction` exposes the candidate for a caller that wants to offer it,
and nothing calls it automatically.
"""

from __future__ import annotations

import re

#: A clause reference as tenders print them: 4, 4.2, 2.8.1, 11.I.(a), 4.2(iii).
#: Shapes seen in this corpus: 4, 4.2, 2.8.1, 1.1 (4), 2.6 (b), 11.I.(a),
#: 11.II(a), 28.1(vi). The dotted-roman segment ("11.I.") is why a plainer
#: pattern captured only "11" and then offered "11" as a correction for
#: "11.I.(a)" -- a suggestion that looked like a finding and was an artefact.
_REFERENCE = re.compile(
    r"\b\d+(?:\.\d+)*"                              # 11, 4.2, 2.8.1
    r"(?:\.(?:[ivxlcIVXLC]+|[A-Za-z])(?![a-zA-Z]))*"  # .I  .II  .b
    r"(?:\s*\.?\s*\([a-zA-Z0-9]+\))*"                # (vi)  (a)  (4)
)


def _squash(reference: str) -> str:
    """Identity of a reference ignoring typography: "1.1 (4)" -> "11(4)"."""
    return re.sub(r"\s+", "", (reference or "").casefold())


def _digits_only(reference: str) -> str:
    """Just the numeric spine, so "2.8.1" and "28.1" collide deliberately.

    That collision is the point: it is how a misplaced dot is caught. It also
    means a correction is only ever offered when exactly one source reference
    collides, never when several do.
    """
    return re.sub(r"[^0-9]", "", reference or "")


def source_references(text: str) -> set[str]:
    """Every clause-shaped token the document actually prints."""
    return {
        _squash(match.group(0))
        for match in _REFERENCE.finditer(text or "")
        if any(ch.isdigit() for ch in match.group(0))
    }


def is_present(clause_ref: str, references: set[str]) -> bool:
    """True when the document prints this reference, typography aside.

    Prefix acceptance is deliberate: a citation of "28.1" is satisfied by the
    document printing "28.1(vi)", because the clause is there and the extra
    specificity is the document's, not an error in the citation.
    """
    needle = _squash(clause_ref)
    if not needle:
        return False
    return any(ref == needle or ref.startswith(needle) for ref in references)


def suggest_correction(clause_ref: str, references: set[str]) -> str | None:
    """The one source reference whose digits match, if there is exactly one.

    Returns None when nothing collides or when several do -- an ambiguous
    suggestion is worse than none, because it invites a reviewer to accept a
    citation that may still be wrong.
    """
    # A correct reference needs no correction. Without this guard "11.I.(a)"
    # -- which the document does print -- was offered "11.II(a)" because both
    # reduce to the digits "11", turning a sound citation into a false finding.
    if is_present(clause_ref, references):
        return None
    spine = _digits_only(clause_ref)
    if not spine:
        return None
    candidates = {ref for ref in references if _digits_only(ref) == spine}
    candidates.discard(_squash(clause_ref))
    return next(iter(candidates)) if len(candidates) == 1 else None
