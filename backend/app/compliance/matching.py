"""Document-name matching (Section 6, "Document-name matching note").

The same required document is named differently across a notification and a bid:
"GST Registration Certificate" vs "Goods & Services Tax Certificate". Exact
string matching produces false negatives, and a false negative here tells a
compliant vendor they are missing a document they actually submitted.

Three tiers, cheapest first, each recording HOW it matched so the audit trail
(5.5) can show why a document counted as present:

  exact      normalised string equality
  alias      a curated synonym table for the standard Indian tender documents
  embedding  BGE cosine similarity, for everything the table doesn't cover

The alias table exists because embeddings alone are unreliable on short, jargon-
heavy strings -- "PAN Card" and "TAN Certificate" are lexically and semantically
close but are entirely different documents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

# Cosine similarity above which two document names are treated as the same
# document. Deliberately high: a false positive marks a missing document as
# present, which is the more dangerous error for a vendor about to submit.
DEFAULT_EMBEDDING_THRESHOLD = 0.86

# Canonical name -> the ways it actually appears in Indian tender documents.
DOCUMENT_ALIASES: dict[str, list[str]] = {
    "gst registration certificate": [
        "gst certificate",
        "gstin certificate",
        "goods and services tax certificate",
        "goods & services tax certificate",
        "gst registration",
        "certificate of gst registration",
    ],
    "pan card": ["permanent account number", "pan", "pan copy", "income tax pan"],
    "audited balance sheet": [
        "audited financial statements",
        "audited annual accounts",
        "balance sheet and profit and loss account",
        "audited accounts",
        "annual audited statements",
    ],
    "emd demand draft": [
        "earnest money deposit",
        "emd",
        "emd proof",
        "bid security",
        "demand draft towards emd",
        "earnest money",
    ],
    "iso 9001 certificate": [
        "iso 9001:2015 certificate",
        "iso 9001:2015",
        "quality management system certificate",
        "iso certification",
    ],
    "power of attorney": ["authorisation letter", "board resolution", "authority letter"],
    "work experience certificate": [
        "experience certificate",
        "completion certificate",
        "performance certificate",
        "work order copy",
        "satisfactory completion certificate",
    ],
    "solvency certificate": ["bank solvency certificate", "banker's certificate"],
    "non blacklisting declaration": [
        "self declaration of non blacklisting",
        "affidavit of non debarment",
        "declaration regarding blacklisting",
        "undertaking of non blacklisting",
    ],
    "provident fund registration": ["epf registration", "pf registration certificate"],
    "esi registration": ["employees state insurance registration"],
    "tender fee receipt": ["cost of tender document", "tender document fee"],
    "turnover certificate": ["ca certificate for turnover", "chartered accountant certificate"],
    "incorporation certificate": [
        "certificate of incorporation",
        "registration certificate of the firm",
        "partnership deed",
        "company registration certificate",
    ],
    "labour licence": ["contract labour licence", "labour registration"],
}

_PUNCTUATION = re.compile(r"[^\w\s]")
_WHITESPACE = re.compile(r"\s+")
# Filler that carries no identifying information for a document name.
_STOPWORDS = {
    "the", "of", "a", "an", "for", "and", "copy", "copies", "attested",
    "self", "duly", "valid", "latest", "original", "photocopy", "scanned",
}


def normalise(name: str) -> str:
    """Lowercase, strip punctuation and filler, collapse whitespace."""
    text = _PUNCTUATION.sub(" ", (name or "").lower())
    tokens = [t for t in _WHITESPACE.split(text) if t and t not in _STOPWORDS]
    return " ".join(tokens)


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, str]:
    """Flattened alias -> canonical lookup, including each canonical itself."""
    index: dict[str, str] = {}
    for canonical, aliases in DOCUMENT_ALIASES.items():
        index[normalise(canonical)] = canonical
        for alias in aliases:
            index[normalise(alias)] = canonical
    return index


def canonical_form(name: str) -> str | None:
    """Map a document name onto a known canonical name, if the table covers it."""
    return _alias_index().get(normalise(name))


@dataclass(frozen=True)
class MatchResult:
    """Why a requirement was or was not considered satisfied."""

    matched: bool
    method: str | None          # 'exact' | 'alias' | 'embedding' | None
    score: float | None
    matched_name: str | None    # the submitted document that satisfied it

    @property
    def is_uncertain(self) -> bool:
        """Embedding matches near the threshold deserve a human glance rather
        than being reported as settled fact."""
        return (
            self.matched
            and self.method == "embedding"
            and self.score is not None
            and self.score < DEFAULT_EMBEDDING_THRESHOLD + 0.04
        )


NO_MATCH = MatchResult(matched=False, method=None, score=None, matched_name=None)


def match_document(
    required: str,
    submitted: list[str],
    *,
    extra_aliases: list[str] | None = None,
    threshold: float = DEFAULT_EMBEDDING_THRESHOLD,
    use_embeddings: bool = True,
) -> MatchResult:
    """Decide whether `required` appears among `submitted`.

    `extra_aliases` carries per-tender aliases captured at extraction time, so a
    notification that defines its own shorthand is honoured without editing the
    global table.
    """
    if not submitted:
        return NO_MATCH

    required_norm = normalise(required)

    # Tier 1: exact, after normalisation.
    for name in submitted:
        if normalise(name) == required_norm:
            return MatchResult(True, "exact", 1.0, name)

    # Tier 2: the curated alias table, plus any tender-specific aliases.
    required_canonical = canonical_form(required)
    extra_norms = {normalise(a) for a in (extra_aliases or [])}
    for name in submitted:
        name_norm = normalise(name)
        if name_norm in extra_norms:
            return MatchResult(True, "alias", 1.0, name)
        submitted_canonical = canonical_form(name)
        if (
            required_canonical is not None
            and submitted_canonical is not None
            and required_canonical == submitted_canonical
        ):
            return MatchResult(True, "alias", 1.0, name)

    # Tier 3: embedding similarity for names the table doesn't know.
    if not use_embeddings:
        return NO_MATCH
    try:
        best_name, best_score = _best_embedding_match(required, tuple(submitted))
    except Exception:
        # Model unavailable: report no match rather than guessing. A vendor
        # sees "not found -- check manually", never a fabricated match.
        return NO_MATCH

    if best_score >= threshold:
        return MatchResult(True, "embedding", round(best_score, 4), best_name)
    return MatchResult(False, None, round(best_score, 4), None)


@lru_cache(maxsize=512)
def _best_embedding_match(required: str, submitted: tuple[str, ...]) -> tuple[str, float]:
    from app.vector.embeddings import embed_passages

    vectors = embed_passages([required, *submitted])
    required_vec, rest = vectors[0], vectors[1:]
    # Vectors are unit-normalised, so the dot product is cosine similarity.
    scores = [sum(a * b for a, b in zip(required_vec, v)) for v in rest]
    best = max(range(len(scores)), key=scores.__getitem__)
    return submitted[best], scores[best]
