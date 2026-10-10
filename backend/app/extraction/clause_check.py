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

WIRED INTO THE VALIDATION PASS, now that it can tell a composition from a
defect. It was deliberately left out for a long time, and the reason is worth
keeping: pointed at the real corpus the original check flagged 20 of
civilworks_01's citations and 19 of civilworks_02's, which is noise rather than
38 findings, and a flag that fires twenty times per document teaches everyone
to ignore it.

What fixed it was NOT narrowing the reference set. That was the obvious move and
it changed nothing measurable: on a tender page, flat and structural extraction
produce identical findings even though the reference set shrinks from 13 tokens
to 4. The actual flaw was that `is_present` demanded a concatenated reference
appear verbatim, while a legitimate citation COMPOSES a section heading with a
sub-item printed beneath it. civilworks_01 prints

    1.1  Scope of work
     (4) Largest similar completed work of not less than 80% ...

so "1.1 (4)" is a correct, checkable citation that appears nowhere as one token.
Those compositions were most of the twenty findings, and they were never
defects. `is_present_compositional` accepts them.

A misplaced dot does not compose, which is the discrimination that makes the
check worth running: for the HGCL "2.8.1" to be legitimate the document would
have to print a section 2.8 carrying a sub-item 1, and it prints 28.1 instead.
Measured on a representative tender page the findings go from 6 to 2 -- the four
dropped are all compositions, and both survivors are real: the misplaced dot,
with "28.1" named as the near-miss, and a clause genuinely absent in any form.

Structural extraction is still used, because it is what makes
`suggest_correction` unambiguous: fewer colliding digit-spines means a near-miss
is named rather than withheld.

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


# --------------------------------------------------------------------------- #
# Structure-aware extraction.
#
# This is the fix the module docstring above asks for. `_REFERENCE` over flat
# text matches any number, so a 236,000-character tender yields hundreds of
# "references" that are amounts and dates -- which made `is_present` trivial to
# satisfy and `suggest_correction` silent on collisions. The observation that
# fixes it is structural: a tender prints a clause reference at the START of a
# line and then the clause text,
#
#     28.1 The Chief General Manager will evaluate whether each Tenderer ...
#     vi)  Liquid assets and/ or credit facilities of not less than Rs.49.855
#
# whereas the amounts that generate the noise ("Rs.49.855", "0.973", "000.00")
# appear mid-line. Reading only line-leading numbering therefore keeps every
# real reference and discards most of the false ones, without needing a layout
# model.
# --------------------------------------------------------------------------- #

#: Units and currency words that follow a NUMBER, never a clause reference. A
#: table row may legitimately begin with an amount, and "49.855 Crores" at the
#: start of a line is not clause 49.855.
_UNIT_AFTER = re.compile(
    r"^\s*(?:cr|crs|crore|crores|lakh|lakhs|lac|lacs|%|percent|per\s*cent"
    r"|nos?|no\.|kg|km|mtr|metre|metres|m|sqm|sq\.?\s*m|days?|months?|years?"
    r"|hrs?|hours?|rs\.?|inr|usd)\b",
    re.IGNORECASE,
)

_LINE_LEADING = re.compile(
    r"^[\s\u2022\u00b7*\-\u2013\u2014|]*"          # indent, bullet, table pipe
    r"(?P<ref>[1-9]\d*(?:\.\d+)*"                      # 28, 4.2, 2.8.1 -- never 0.x
    r"(?:\.(?:[ivxlc]+|[a-z])(?![a-z]))*"               # .I  .ii  .b
    r"(?:\s*\.?\s*\([a-z0-9]+\))*)"                   # (vi)  (a)  (4)
    r"(?P<tail>.*)$",
    re.IGNORECASE | re.MULTILINE,
)


def structural_references(text: str) -> set[str]:
    """Clause references the document prints as line-leading numbering.

    Deliberately narrower than `source_references`. Three rejections carry the
    whole difference in false-positive rate:

      * a leading zero -- "0.973" is a ratio, and no tender numbers a clause 0;
      * a unit or currency word immediately after the number, so a table row
        beginning "49.855 Crores" is an amount rather than clause 49.855;
      * a bare integer with no clause text after it, which is a table cell or a
        page number rather than a heading.

    A reference followed by nothing but digits and separators is also rejected,
    which is what excludes date and amount columns.
    """
    found: set[str] = set()
    for match in _LINE_LEADING.finditer(text or ""):
        reference = match.group("ref")
        tail = match.group("tail") or ""

        if _UNIT_AFTER.match(tail):
            continue

        # A real clause reference introduces text. A number alone on a line, or
        # followed only by more numbers, is a cell in a table.
        stripped = tail.strip(" .:)\u2013\u2014-|\t")
        if not stripped:
            # Bare "28.1" on its own line is still a plausible heading, but a
            # bare integer is far more likely a page number or a serial column.
            if "." not in reference and "(" not in reference:
                continue
        elif not re.search(r"[A-Za-z]{3}", stripped):
            continue

        found.add(_squash(reference))
    return found


def unverifiable_references(
    clause_refs: list[str], text: str, *, structural: bool = True
) -> list[tuple[str, str | None]]:
    """Cited references the document does not print, each with a near-miss.

    Returns (clause_ref, suggestion_or_None). This is the shape a validation
    pass wants: a finding per citation that cannot be looked up, and the one
    colliding source reference when exactly one collides -- which is how the
    HGCL "2.8.1" against a printed "28.1" is surfaced as a misplaced dot rather
    than as an absent clause.

    Nothing here rewrites a citation. Adjusting stored provenance to whatever it
    resembles would improve the measured number without the extraction getting
    better, and provenance is the last thing in this system that should be
    quietly fitted to expectations.
    """
    references = (
        structural_references(text) if structural else source_references(text)
    )
    findings: list[tuple[str, str | None]] = []
    for clause_ref in clause_refs:
        if not (clause_ref or "").strip():
            continue
        if is_present(clause_ref, references):
            continue
        findings.append((clause_ref, suggest_correction(clause_ref, references)))
    return findings


# --------------------------------------------------------------------------- #
# Compositional presence.
#
# Narrowing the reference set is not what fixes the false-finding rate: measured
# on a tender page, flat and structural extraction produce the SAME findings
# even though the reference set shrinks from 13 to 4. The real flaw is stricter
# than that -- `is_present` demands the concatenated string appear verbatim,
# while a legitimate citation COMPOSES a section heading with a sub-item printed
# underneath it. civilworks_01 prints
#
#     1.1  Scope of work
#          ...
#      (4) The contractor shall provide ...
#
# so "1.1 (4)" is a correct, checkable citation that appears nowhere as a single
# token. Those compositions were most of the twenty findings that made this
# module too noisy to wire in, and they are not defects.
#
# A misplaced dot does NOT compose: for the HGCL "2.8.1" to be legitimate the
# document would have to print a section 2.8 with a sub-item 1 beneath it, and
# it prints 28.1 instead. So compositional presence accepts the false alarms and
# still rejects the real defect, which is exactly the discrimination the module
# docstring says it lacks.
# --------------------------------------------------------------------------- #

#: A sub-item as tenders print them at the start of a line: (4), vi), (a), iii.
_SUB_ITEM = re.compile(
    r"^[\s\u2022\u00b7*\-\u2013\u2014|]*"
    r"\(?(?P<item>[ivxlc]+|[a-z]|\d{1,2})\)"
    r"(?=[\s.:]|$)",
    re.IGNORECASE | re.MULTILINE,
)


def document_sections(text: str) -> dict[str, set[str]]:
    """Line-leading section numbers mapped to the sub-items printed under each.

    A sub-item belongs to the most recent section heading above it, which is how
    a reader attributes it. Scope ends at the next line-leading section.
    """
    sections: dict[str, set[str]] = {}
    current: str | None = None
    for line in (text or "").splitlines():
        heading = _LINE_LEADING.match(line)
        if heading:
            reference = heading.group("ref")
            tail = (heading.group("tail") or "")
            if not _UNIT_AFTER.match(tail) and re.search(r"[A-Za-z]{3}", tail):
                current = _squash(reference)
                sections.setdefault(current, set())
                continue
        item = _SUB_ITEM.match(line)
        if item and current is not None:
            sections[current].add(item.group("item").casefold())
    return sections


def _split_reference(clause_ref: str) -> tuple[str, str | None]:
    """"1.1(4)" -> ("1.1", "4"); "28.1" -> ("28.1", None)."""
    squashed = _squash(clause_ref)
    match = re.match(r"^(?P<section>[\d.]+?)\(?(?P<item>[ivxlc]+|[a-z]|\d{1,2})\)$",
                     squashed, re.IGNORECASE)
    if match:
        return match.group("section").rstrip("."), match.group("item").casefold()
    return squashed, None


def is_present_compositional(clause_ref: str, text: str) -> bool:
    """True when the document prints this clause, verbatim OR by composition.

    Checked in that order, because a verbatim match needs no interpretation.
    """
    references = structural_references(text)
    if is_present(clause_ref, references):
        return True

    section, item = _split_reference(clause_ref)
    if item is None:
        return False

    sections = document_sections(text)
    # The section must exist as a heading, and the sub-item must be printed
    # within it. Either half alone is not a citation.
    for printed, items in sections.items():
        if printed == section or printed.startswith(section):
            if item in items:
                return True
    return False


def unverifiable_citations(
    clause_refs: list[str], text: str
) -> list[tuple[str, str | None]]:
    """The validation-pass shape: citations that cannot be looked up at all.

    Accepts composition, so a section-plus-sub-item citation is not reported;
    rejects a reference whose digits merely resemble a printed one, so the HGCL
    misplaced dot still surfaces with "28.1" named as the near-miss.
    """
    references = structural_references(text)

    # A document with NO readable clause numbering cannot verify any citation,
    # so reporting every one of them is unfounded -- and is the twenty-findings
    # -per-tender noise this module was held back for, in a different form. It
    # arises for real on a scanned tender whose OCR produced prose without
    # recovering the numbering, and on any page that failed to parse. "We could
    # not read this document's structure" is an extraction-coverage problem, not
    # evidence that a citation is wrong.
    if not references:
        return []

    findings: list[tuple[str, str | None]] = []
    for clause_ref in clause_refs:
        if not (clause_ref or "").strip():
            continue
        if is_present_compositional(clause_ref, text):
            continue
        findings.append((clause_ref, suggest_correction(clause_ref, references)))
    return findings
