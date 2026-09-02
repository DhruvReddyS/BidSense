"""Rename a required document the way a real bidder would write it.

The test corpus had a circularity problem. Each synthetic bid's enclosure
checklist was generated verbatim from the requirement list the pipeline
extracted from that notification, so every document name in a bid was
byte-identical to the name it would be matched against. Tier 1 of
`app.compliance.matching` -- normalised string equality -- therefore answered
every check, and the alias table and the embedding tier were never executed on
real data at all. They were tested only against hand-written unit fixtures,
which is a test of the fixture rather than of the corpus.

Real bids do not work that way. A tender asking for "Copy of GST registration"
receives a bid enclosing "Goods & Services Tax Registration Certificate", and a
tender asking for a "Bid Securing Declaration" receives a "Bid Security
Undertaking". Getting that wrong tells a compliant vendor they are missing a
document they actually submitted -- the exact false negative the three tiers
exist to prevent.

Two renaming styles, because they exercise different tiers:

  alias     swaps to a different name for the same document drawn from the
            curated synonym table. Exercises tier 2 and must match at score 1.0.
  reworded  changes content words the table does not know about, so the name
            can only be resolved by embedding similarity. Exercises tier 3, and
            the score it achieves is a measurement rather than a guarantee.

Both are deterministic: the same requirement always renames to the same string,
so a regenerated corpus is diffable and the answer key cannot drift.
"""

from __future__ import annotations

import re

from app.compliance.matching import DOCUMENT_ALIASES, canonical_form, normalise

__all__ = ["NamingStyle", "paraphrase", "rename_catalogue"]

NamingStyle = str  # "as_printed" | "alias" | "reworded"


# Content-word substitutions a bidder would plausibly make. These deliberately
# avoid the stopword list in `matching.normalise` -- swapping "copy" for
# "photocopy" changes nothing after normalisation and would leave the name
# matching exactly, which is the circularity this module exists to break.
#
# Each pair is a genuine synonym in Indian tender usage. A substitution that
# changed the meaning would make the bid non-compliant for real, and the answer
# key would be wrong rather than the matcher.
_SUBSTITUTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bdeclaration\b", re.I), "undertaking"),
    (re.compile(r"\bproof of\b", re.I), "documentary evidence of"),
    (re.compile(r"\bcompletion certificates?\b", re.I), "certificates of satisfactory completion"),
    (re.compile(r"\bwork orders?\b", re.I), "purchase orders placed on us"),
    (re.compile(r"\bexperience\b", re.I), "past performance record"),
    (re.compile(r"\btest report\b", re.I), "type test report"),
    (re.compile(r"\bcompliance sheet\b", re.I), "clause-wise compliance statement"),
    (re.compile(r"\bletter of bid\b", re.I), "bid submission letter"),
    (re.compile(r"\bcovering letter\b", re.I), "forwarding letter"),
    (re.compile(r"\bauthori[sz]ation to represent\b", re.I), "letter authorising the signatory of"),
    (re.compile(r"\bfinancial status\b", re.I), "financial position"),
    (re.compile(r"\bbalance sheets?\b", re.I), "statement of assets and liabilities"),
    (re.compile(r"\bincome tax returns?\b", re.I), "IT returns"),
    (re.compile(r"\bregistration\b", re.I), "enrolment"),
    (re.compile(r"\bannual turnover\b", re.I), "yearly revenue"),
    (re.compile(r"\bnet worth\b", re.I), "shareholders' funds"),
    (re.compile(r"\bchartered accountant\b", re.I), "statutory auditor"),
    (re.compile(r"\bsolvency certificate\b", re.I), "banker's solvency letter"),
    (re.compile(r"\bdigital signature certificate\b", re.I), "class III DSC token certificate"),
    (re.compile(r"\bbid securing\b", re.I), "bid security"),
    (re.compile(r"\bearnest money deposit\b", re.I), "bid security deposit"),
    (re.compile(r"\bmanufacturers? authori[sz]ation\b", re.I), "OEM authorisation"),
    (re.compile(r"\btechnical specification\b", re.I), "technical datasheet"),
    (re.compile(r"\blitigation\b", re.I), "pending court cases"),
    (re.compile(r"\bkey personnel\b", re.I), "deployed technical staff"),
    (re.compile(r"\bkey equipment\b", re.I), "plant and machinery"),
    (re.compile(r"\bshareholding\b", re.I), "share capital"),
    (re.compile(r"\bno deviation\b", re.I), "nil deviation"),
    (re.compile(r"\bintegrity pact\b", re.I), "integrity agreement"),
    (re.compile(r"\bpass-?phrase\b", re.I), "decryption passphrase"),
]

# "Certificate of Incorporation" -> "Incorporation Certificate". A structural
# fallback for names no substitution above matches: it changes the normalised
# token ORDER, which defeats string equality without inventing vocabulary.
_OF_PHRASE = re.compile(r"^(.{3,40}?)\s+of\s+(?:the\s+)?(.{3,60})$", re.I)


def _swap_alias(name: str) -> str | None:
    """A different printed name for the same document, from the curated table."""
    canonical = canonical_form(name)
    if canonical is None:
        return None
    current = normalise(name)
    for alias in [canonical, *DOCUMENT_ALIASES[canonical]]:
        if normalise(alias) != current:
            # Title-cased: a bid prints document names as headings, not lowercase.
            return alias.title().replace("Gst", "GST").replace("Pan", "PAN")
    return None


# A name that quotes a numbered form or annexure is copied verbatim by a real
# bidder -- nobody encloses "Form past performance record" where the tender said
# "Form F-13". Rewording inside one produces test data no bid would contain, and
# a matcher that failed on it would be failing a case that cannot occur.
_FORM_REFERENCE = re.compile(
    r"\b(?:form|annexure|appendix|schedule|proforma|format)\b[\s:.\-]*"
    r"(?:no\.?\s*)?[A-Z0-9][A-Z0-9\-./]*",
    re.I,
)


def _reword(name: str) -> str | None:
    """Change content words the alias table does not cover."""
    if _FORM_REFERENCE.search(name):
        return None

    for pattern, replacement in _SUBSTITUTIONS:
        reworded, count = pattern.subn(replacement, name, count=1)
        if count and normalise(reworded) != normalise(name):
            return reworded

    match = _OF_PHRASE.match(name.strip())
    if match:
        flipped = f"{match.group(2).strip()} {match.group(1).strip()}"
        if normalise(flipped) != normalise(name):
            return flipped
    return None


def paraphrase(name: str, style: NamingStyle) -> str:
    """Rename `name` for a bid written in `style`.

    Falls back rather than failing: `alias` degrades to `reworded` for a document
    the table does not know, and `reworded` returns the name unchanged when
    nothing safe can be substituted. Inventing a name for the sake of the style
    would produce a bid enclosing a document the tender never asked for, which is
    a broken fixture rather than a harder test.
    """
    if style == "alias":
        return _swap_alias(name) or _reword(name) or name
    if style == "reworded":
        return _reword(name) or _swap_alias(name) or name
    return name


def rename_catalogue(names: list[str], style: NamingStyle) -> list[str]:
    """Apply `style` to a whole requirement list, preserving order."""
    if style == "as_printed":
        return list(names)
    return [paraphrase(name, style) for name in names]
