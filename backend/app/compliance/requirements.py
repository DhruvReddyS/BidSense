"""Requirement hygiene: deduplication and conditional detection.

Real tender documents are messy in two ways that wreck a naive gap report, both
observed in the GHMC LED tender (68 pages, 65 extracted document requirements):

1. **The same requirement is stated several times.** "Power of Attorney" appears
   in the checklist, in the instructions to bidders, and in the annexure index.
   Extracted verbatim from each, it becomes three separate gap items, and a
   vendor who uploaded it once still sees two red rows.

2. **Many requirements are conditional.** JV and consortium documents apply only
   to bidders who are actually a JV. Flagging them against a sole proprietor
   produced 22 "disqualifying" rows on a bid that was fine on those grounds --
   which buries the one real failure in noise and destroys trust in the report.

Both are handled here rather than in the extractor: the model should report what
the document says, and interpretation belongs in deterministic code we can test
(Section 2.1.3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.compliance.matching import canonical_form, normalise, document_identifiers
from app.schemas.notification import MandatoryDocument


class Applicability(StrEnum):
    """When a requirement actually binds."""

    ALWAYS = "always"
    # Only if the bidder is a JV/consortium; irrelevant to a sole bidder.
    JOINT_VENTURE = "joint_venture"
    # The document itself says "if applicable" / "wherever applicable".
    CONDITIONAL = "conditional"
    # Only if the bidder is claiming a specific concession (MSME, startup, ...).
    CONCESSION = "concession"


_JV_MARKERS = (
    "jv", "j.v", "joint venture", "consortium", "consortia", "lead member",
    "member of the jv", "partner in the jv",
)
_CONDITIONAL_MARKERS = (
    "if applicable", "wherever applicable", "as applicable", "if any",
    "in case of", "if the bidder", "where applicable", "if required",
    "if claimed", "should the bidder",
)
_CONCESSION_MARKERS = (
    "msme", "mse ", "startup", "start-up", "nsic", "udyam",
    "exemption", "concession", "preference under",
)

# A JV marker inside a longer phrase is only decisive when the phrase is *about*
# the JV. "Firm Registration certificate of each bidder / JV / Consortium
# Partner" binds a sole bidder too -- they are the "each bidder" part.
_JV_BUT_STILL_UNIVERSAL = re.compile(
    r"\b(?:each|every|the)\s+bidder\b|\bbidder\s*/\s*jv\b|\bbidder\s*/", re.IGNORECASE
)

class Verifiability(StrEnum):
    """Whether the ABSENCE of this requirement can be concluded mechanically.

    A separate axis from `Applicability`, which says when a requirement binds.
    This says whether "we did not find it" is a finding at all.

    Earned by measurement. On the 19-bid evaluation set four bids that should
    pass were disqualified, and every one of them failed on a "mandatory
    document" that no bid could ever match:

        "relevant documents (copy of Work order, Completion certificate etc.)"
        "Produce documentary evidence to prove past experience, capabilities"
        "Experience of having successfully completed ... (i) One Work Order
         value not less than 80% of Estimated Cost (ii) Two Work Orders ..."
        "Legal Entity: The Bidder could be sole proprietorship /OEM/ ..."
        "Pass-Phrase"

    None of those names an artefact. They are catch-alls, instructions, the
    eligibility conditions already checked on the numeric path, and a portal
    credential. Matching them against a bid's enclosure list cannot succeed, so
    treating a non-match as a missing mandatory document manufactured a
    disqualification out of the tender's own prose.

    The product already draws this distinction everywhere else -- "We could not
    read this value. That is not the same as failing it." -- and this makes the
    document path obey it too: an unverifiable requirement becomes the vendor's
    own check, never an elimination.
    """

    #: Names an artefact a bidder can enclose. Absence is a real gap.
    ENCLOSURE = "enclosure"
    #: A condition, instruction or catch-all. Absence proves nothing.
    UNVERIFIABLE = "unverifiable"


#: Phrases that stand in for a category rather than a thing. A bidder cannot
#: enclose a category, so absence of a category is not absence of a document.
_CATCHALL_MARKERS = (
    "any other", "all other", "relevant documents",
    "as may be required", "as required in", "and other documents",
    "other relevant", "among others",
)

#: "etc." alone is NOT decisive. "Bidder's Declaration regarding Banning,
#: Liquidation etc." and "Solvency certificate from banks etc." both name a
#: real artefact and then trail off; demoting those to a human check would
#: discard two genuine document checks to no purpose. So a trailing "etc."
#: makes a requirement a catch-all only when nothing concrete is named -- and
#: the concrete noun is what name matching works on anyway.
#: Word-boundary match, because the token appears as "etc.", "etc,", "etc "
#: and bare "etc" at end of string -- a list of string variants missed the last.
_TRAILING_ETC = re.compile(r"\betc\b\.?")

#: Nouns that name a thing a bidder can attach.
_DOCUMENT_NOUNS = (
    "certificate", "declaration", "letter", "form", "affidavit", "undertaking",
    "statement", "copy", "card", "deed", "receipt", "challan", "bill",
    "sheet", "report", "licence", "license", "order", "agreement",
    "resolution", "attorney", "return", "invoice", "voucher", "draft",
    "balance sheet", "profit and loss", "registration", "authorisation",
    "authorization", "annexure", "proforma", "schedule", "bond", "guarantee",
)


def _names_an_artefact(text: str) -> bool:
    return any(noun in text for noun in _DOCUMENT_NOUNS)

#: Instructions to demonstrate something, rather than names of what to attach.
_INSTRUCTION_MARKERS = (
    "documentary evidence to prove", "evidence to prove", "produce documentary",
    "establishing the qualification", "to the satisfaction of",
    "to establish that", "in support of the claim",
)

#: Threshold and status language. A requirement phrased as a test is an
#: eligibility criterion; those are evaluated on the numeric and boolean paths,
#: and re-checking them as paperwork puts a bidder in double jeopardy -- failing
#: once on the figure and again on "the certificate stating the figure".
_CONDITION_MARKERS = (
    "not less than", "at least", "minimum of", "shall not be less",
    "experience of having", "legal entity:", "the bidder could be",
    "should be either of", "must have", "shall have a", "shall be a ",
    "turnover on works", "annual turnover for", "annual turnover on",
)

#: Things that are not documents at all.
_NON_DOCUMENT_MARKERS = (
    "pass-phrase", "passphrase", "password", "user id", "login credential",
    "digital signature certificate class",
)

#: An enumeration of alternatives ("(i) ... (ii) ...") is how a tender writes a
#: criterion with options, never how it names a single enclosure.
_OPTION_ENUMERATION = re.compile(r"\((?:i|1)\)[^)]{0,400}?\((?:ii|2)\)", re.IGNORECASE)


def classify_verifiability(doc_name: str) -> Verifiability:
    """Can we conclude anything from not finding this in a bid?

    Deliberately conservative: everything not positively recognised as a
    condition, instruction, catch-all or non-document stays an ENCLOSURE, so a
    genuine missing document is still a genuine failure. The cost of a wrong
    UNVERIFIABLE is one requirement demoted to a human check; the cost of a
    wrong ENCLOSURE is a compliant bidder told they do not qualify.
    """
    text = (doc_name or "").casefold()
    if not text.strip():
        return Verifiability.UNVERIFIABLE

    if any(marker in text for marker in _NON_DOCUMENT_MARKERS):
        return Verifiability.UNVERIFIABLE
    if any(marker in text for marker in _CATCHALL_MARKERS):
        return Verifiability.UNVERIFIABLE
    if _TRAILING_ETC.search(text) and not _names_an_artefact(text):
        return Verifiability.UNVERIFIABLE
    if any(marker in text for marker in _INSTRUCTION_MARKERS):
        return Verifiability.UNVERIFIABLE
    if any(marker in text for marker in _CONDITION_MARKERS):
        return Verifiability.UNVERIFIABLE
    if _OPTION_ENUMERATION.search(text):
        return Verifiability.UNVERIFIABLE
    return Verifiability.ENCLOSURE


_WORD = re.compile(r"[a-z0-9]+")


def classify_applicability(doc_name: str) -> Applicability:
    """Decide whether a requirement binds every bidder.

    Conservative by design: when a phrase names a JV *and* the general bidder,
    it is treated as always-applicable. Under-flagging a real requirement is
    worse than showing one extra row, so ambiguity resolves to ALWAYS.
    """
    lowered = f" {doc_name.lower()} "

    if any(marker in lowered for marker in _CONCESSION_MARKERS):
        return Applicability.CONCESSION

    has_jv = any(f" {m}" in lowered or f"{m} " in lowered for m in _JV_MARKERS)
    if has_jv and not _JV_BUT_STILL_UNIVERSAL.search(doc_name):
        return Applicability.JOINT_VENTURE

    if any(marker in lowered for marker in _CONDITIONAL_MARKERS):
        return Applicability.CONDITIONAL

    return Applicability.ALWAYS


# --------------------------------------------------------------------------- #
# Deduplication
# --------------------------------------------------------------------------- #
# Leading verbs the extractor picks up from checklist phrasing.
_LEADING_VERB = re.compile(
    r"^(?:submit|submission of|copy of|copies of|scanned copy of|attach(?:ed)?|"
    r"enclose(?:d)?|furnish|provide|upload)\s+",
    re.IGNORECASE,
)
# Trailing boilerplate that varies between restatements of the same requirement.
_TRAILING_NOISE = re.compile(
    r"\s*(?:,\s*)?(?:as (?:specified|per|mentioned|given|detailed)\b.*|"
    r"in support of\b.*|which (?:have|has) been\b.*|"
    r"duly (?:signed|attested|filled)\b.*|"
    # Conditional qualifiers are stripped for IDENTITY only. "Power of Attorney"
    # and "Power of Attorney, if applicable" are the same document stated twice,
    # and must collapse to one row. Applicability is still computed from the
    # original text, so the qualifier is not lost -- and a requirement stated
    # unconditionally anywhere still binds.
    r"(?:if|wherever|where|as)\s+(?:applicable|required|any|claimed)\b.*|"
    r"\(.*?\)\s*$)",
    re.IGNORECASE,
)

# Beyond this, a "document name" is really a sentence the extractor over-captured.
MAX_REASONABLE_NAME = 90


def canonical_key(doc_name: str) -> str:
    """A stable identity for one requirement, robust to restatement.

    "Power of Attorney", "Submission of Power of Attorney" and "Copy of Power of
    Attorney duly attested" all collapse to the same key.
    """
    identifiers = document_identifiers(doc_name)
    suffix = "".join(f" | {kind}:{ref}" for kind, ref in sorted(identifiers))
    text = _LEADING_VERB.sub("", doc_name.strip())
    text = _TRAILING_NOISE.sub("", text)
    canonical = canonical_form(text)
    if canonical:
        return canonical + suffix
    tokens = _WORD.findall(normalise(text))
    return " ".join(tokens[:8]) + suffix


def shorten(doc_name: str) -> str:
    """Trim an over-captured name to something a person can read in a table.

    The full text stays available as the requirement's provenance snippet; this
    is only what gets rendered as the row label.
    """
    text = _LEADING_VERB.sub("", doc_name.strip()).strip()
    if len(text) <= MAX_REASONABLE_NAME:
        return text
    trimmed = _TRAILING_NOISE.sub("", text).strip()
    if len(trimmed) <= MAX_REASONABLE_NAME:
        return trimmed
    # Cut at a word boundary rather than mid-word.
    cut = trimmed[:MAX_REASONABLE_NAME].rsplit(" ", 1)[0]
    return f"{cut}…"


@dataclass
class Requirement:
    """One deduplicated document requirement, ready to be checked."""

    key: str
    label: str
    applicability: Applicability
    sources: list[MandatoryDocument]      # every clause that stated it

    @property
    def clause_refs(self) -> list[str]:
        refs = [
            s.provenance.clause_ref for s in self.sources if s.provenance.clause_ref
        ]
        return sorted(set(refs), key=refs.index)

    @property
    def primary(self) -> MandatoryDocument:
        """The statement with the most specific clause reference wins as the
        canonical citation -- a numbered clause beats an unnumbered mention."""
        return min(
            self.sources,
            key=lambda s: (s.provenance.clause_ref is None, len(s.doc_name)),
        )

    @property
    def aliases(self) -> list[str]:
        """Every distinct phrasing seen, so name matching has more to work with."""
        names = {s.doc_name for s in self.sources}
        extra = {a for s in self.sources for a in s.aliases}
        return sorted(names | extra)

    @property
    def verifiability(self) -> "Verifiability":
        """ENCLOSURE only if SOME clause names it as an attachable artefact.

        Judged across every phrasing, taking the most favourable. A tender that
        states a requirement loosely in a covering paragraph and precisely in
        its checklist has still named a document, and the precise statement is
        the one a bidder can act on -- so one ENCLOSURE phrasing makes the
        requirement checkable, exactly as one unconditional phrasing makes it
        binding in `deduplicate`.
        """
        if any(
            classify_verifiability(source.doc_name) is Verifiability.ENCLOSURE
            for source in self.sources
        ):
            return Verifiability.ENCLOSURE
        return Verifiability.UNVERIFIABLE


def deduplicate(documents: list[MandatoryDocument]) -> list[Requirement]:
    """Collapse restatements of the same document into one requirement.

    Order is preserved by first appearance, so the report still reads in
    document order rather than being reshuffled by a hash.
    """
    grouped: dict[str, list[MandatoryDocument]] = {}
    for document in documents:
        grouped.setdefault(canonical_key(document.doc_name), []).append(document)

    requirements: list[Requirement] = []
    for key, sources in grouped.items():
        primary = min(
            sources, key=lambda s: (s.provenance.clause_ref is None, len(s.doc_name))
        )
        # A requirement is conditional only if EVERY statement of it is. If one
        # clause demands it unconditionally, it binds.
        applicabilities = {classify_applicability(s.doc_name) for s in sources}
        applicability = (
            Applicability.ALWAYS
            if Applicability.ALWAYS in applicabilities
            else next(iter(applicabilities))
        )
        requirements.append(
            Requirement(
                key=key,
                label=shorten(primary.doc_name),
                applicability=applicability,
                sources=sources,
            )
        )
    return requirements
