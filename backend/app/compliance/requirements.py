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

from app.compliance.matching import canonical_form, normalise
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
    text = _LEADING_VERB.sub("", doc_name.strip())
    text = _TRAILING_NOISE.sub("", text)
    canonical = canonical_form(text)
    if canonical:
        return canonical
    tokens = _WORD.findall(normalise(text))
    return " ".join(tokens[:8])          # first 8 tokens identify the document


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
