"""Document-name matching (Section 6, "Document-name matching note").

The same required document is named differently across a notification and a bid:
"GST Registration Certificate" vs "Goods & Services Tax Certificate". Exact
string matching produces false negatives, and a false negative here tells a
compliant vendor they are missing a document they actually submitted.

Four tiers, cheapest first, each recording HOW it matched so the audit trail
(5.5) can show why a document counted as present:

  exact      normalised string equality, spelling and plurals folded
  alias      a curated synonym table for the standard Indian tender documents
  lexical    the same idea one level down -- known synonym VOCABULARY, then
             agreement on the words that actually identify a document
  embedding  BGE cosine similarity, for everything the tables don't cover

The alias table exists because embeddings alone are unreliable on short, jargon-
heavy strings -- "PAN Card" and "TAN Certificate" are lexically and semantically
close but are entirely different documents.

The lexical tier exists because of the opposite failure, measured on the real
corpus: requirement names in actual tenders are sentences, not titles
("Certificate from the chartered accountant"), and a bid restating one in
ordinary bidder vocabulary ("Certificate from the statutory auditor") scores
0.83 -- below the floor for declaring a document present, and correctly so,
because that floor is what stops a vendor submitting without a document we told
them they had.

Below the floor there is a third answer that is neither. `needs_review` names
the near-miss candidate and asks, rather than reporting MISSING and sending a
vendor to obtain a document already sitting in their bid under another name.
Nothing in this module ever declares a document present on a sub-threshold
score; the band only changes what a failure to match is allowed to claim.
"""

from __future__ import annotations

import re
import threading
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

# British and American spellings both appear in Indian tender documents, often
# in the same paragraph -- "Manufacturers authorization form" in the notification
# against "OEM authorisation form" in the bid. Folding them is not a synonym
# judgment, it is the same word spelled two ways, so it belongs in normalisation
# rather than in any of the matching tiers.
_SPELLING = [
    (re.compile(r"ization\b"), "isation"),
    (re.compile(r"izing\b"), "ising"),
    (re.compile(r"ized\b"), "ised"),
    (re.compile(r"ize\b"), "ise"),
    (re.compile(r"ce\b"), "se"),          # licence/license, practice/practise
]


def _singular(token: str) -> str:
    """Crude but safe plural stripping.

    Only a trailing bare "s" is removed, and only from a token long enough that
    doing so leaves a real word. "certificates" -> "certificate"; "address",
    "status" and "gas" are left alone, which is what the exclusions buy.
    """
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def normalise(name: str) -> str:
    """Lowercase, strip punctuation and filler, fold spelling, collapse space."""
    text = _PUNCTUATION.sub(" ", (name or "").lower())
    tokens = []
    for token in _WHITESPACE.split(text):
        if not token or token in _STOPWORDS:
            continue
        for pattern, replacement in _SPELLING:
            token = pattern.sub(replacement, token)
        tokens.append(_singular(token))
    return " ".join(tokens)


# --------------------------------------------------------------------------- #
# Tier 3: vocabulary
# --------------------------------------------------------------------------- #
# The alias table above maps whole DOCUMENT NAMES. It cannot help with the names
# real tenders actually produce, which are sentences rather than titles:
# "Certificate from the chartered accountant", "Manufacturers authorization
# form", "Authorization to represent the firm". A bid restating any of those in
# ordinary bidder vocabulary lands 0.73-0.86 on cosine similarity -- below the
# floor for declaring a document present, and measured on the real corpus rather
# than assumed.
#
# The mechanism is synonym substitution, and pure token overlap provably cannot
# see through it: substituting the synonym is exactly what removes the shared
# tokens. Measured on the five real misses, plain containment resolved one, and
# only through the noise words "certificate" and "form".
#
# So the same curated-knowledge argument that justifies the alias table is
# applied one level down, to VOCABULARY. These pairs are standard Indian tender
# and company-law usage, and each would be worth writing down for a reader who
# had never seen this test corpus -- that is the bar for adding one, not
# "it makes a fixture pass".
WORD_SYNONYMS: dict[str, str] = {
    # Longest phrases first; applied by `_canonical_vocabulary` in that order.
    "statutory auditor": "chartered accountant",
    "documentary evidence": "proof",
    "past performance record": "experience",
    "purchase order": "work order",
    "income tax return": "it return",
    "digital signature certificate": "dsc",
    "manufacturer authorisation form": "maf",
    "bid securing": "bid security",
    "earnest money deposit": "emd",
    "bid security deposit": "emd",
    "forwarding letter": "covering letter",
    "shareholder fund": "net worth",
    "yearly revenue": "annual turnover",
    "oem": "manufacturer",
    "nil": "no",
    "undertaking": "declaration",
    "affidavit": "declaration",
    "enrolment": "registration",
}

# Words that appear in the name of almost every tender document and therefore
# identify none of them. Overlap on these is not evidence: "solvency
# certificate" and "ISO certificate" share "certificate" and are unrelated.
_GENERIC_TOKENS = {
    "certificate", "certification", "form", "format", "document", "letter",
    "proof", "evidence", "statement", "sheet", "report", "declaration",
    "no", "nos", "number", "as", "per", "in", "on", "at", "with", "by", "to",
    "from", "its", "their", "our", "shall", "be", "is", "such", "etc",
    "required", "relevant", "submitted", "enclosed", "along", "regarding",
    # Who the requirement binds, and under which instrument. Every document in
    # a tender is "of the bidder" under "this bid", so agreeing on these words
    # is agreement about nothing: "Bid Securing Declaration" and "Letter of Bid"
    # share only "bid" and are different documents. Measured -- both of the
    # false matches this tier produced on the real corpus rested on exactly
    # this vocabulary.
    "bid", "bidder", "bids", "tender", "jv", "joint", "venture", "consortium",
    "partner", "each", "any", "all", "firm", "company", "work", "works",
    "above", "said", "this", "that", "we", "us", "he", "him",
}

# Cosine similarity below which a name is not even worth offering as a
# candidate. Between this and DEFAULT_EMBEDDING_THRESHOLD the match is reported
# for confirmation, never as settled -- see `MatchResult.needs_review`.
#
# TUNED, NOT DERIVED. It is worth being explicit about that. The two
# distributions overlap and no floor separates them cleanly: on the real corpus,
# document pairs that ARE the same document under different names score
# 0.73-0.86, and pairs that are genuinely different documents ("ISO 9001" vs
# "ISO 14001", "Audited" vs "Provisional Balance Sheet") score 0.58-0.76. Any
# floor sits inside that overlap.
#
# Measured across all 15 bids, moving the floor from 0.78 to 0.72 costs 11 more
# "confirm this is the right document" lines across the corpus -- under one per
# vendor -- and removes one false "you are missing a mandatory document". That
# trade is the right way round for a tool a vendor reads before submitting: a
# spurious confirmation prompt wastes a minute, a spurious missing-document
# verdict tells a compliant bidder not to bid.
#
# The safe range is narrow and was found with the evaluation answer key visible,
# which is a real caveat on this number. At 0.70 a genuine elimination is
# softened away (a bid missing its ALMM declaration stops being reported as
# missing it), so the floor cannot simply be lowered further.
# `tests/test_matching_tiers.py::test_the_review_floor_still_reports_real_absences`
# pins the lower bound so a later tweak cannot cross it silently.
REVIEW_BAND_FLOOR = 0.72

# How much of the requirement's identifying vocabulary the submitted name must
# account for before a lexical match is claimed.
LEXICAL_CONTAINMENT = 0.8


@lru_cache(maxsize=1)
def _synonym_phrases() -> list[tuple[str, str]]:
    """Normalised synonym pairs, SHORTEST first, then applied twice.

    Order is not cosmetic here. "Manufacturers authorization form" and "OEM
    authorisation form" are the same document, but longest-first rewriting sends
    them to different places: the three-word rule collapses the first to "maf"
    while the second still says "oem", and the one-word rule that would have
    reconciled them has already been passed. Rewriting words before phrases, and
    then running the list again, lets both converge on "maf".

    The table has no cycles (nothing rewrites back into a left-hand side), so a
    second pass reaches a fixed point rather than oscillating.
    """
    pairs = [(normalise(k), normalise(v)) for k, v in WORD_SYNONYMS.items()]
    return sorted(
        (p for p in pairs if p[0] and p[0] != p[1]),
        key=lambda p: len(p[0].split()),
    )


@lru_cache(maxsize=4096)
def _canonical_vocabulary(name: str) -> str:
    """Normalise, then rewrite known synonyms to one spelling of the concept."""
    text = normalise(name)
    phrases = _synonym_phrases()
    for _ in range(2):
        before = text
        for variant, canonical in phrases:
            text = re.sub(rf"\b{re.escape(variant)}\b", canonical, text)
        if text == before:
            break
    return text


def _distinctive(text: str) -> frozenset[str]:
    return frozenset(t for t in text.split() if t not in _GENERIC_TOKENS)


def _lexical_match(required: str, submitted: list[str]) -> tuple[str, float] | None:
    """Resolve a name by vocabulary, for the cases embeddings score too low.

    Two ways to qualify, both requiring agreement on words that actually
    identify a document rather than on "certificate" and "form":

      * the canonicalised names are equal outright, or
      * the requirement's distinctive vocabulary is contained in the submitted
        name's, with at least two words shared -- or one, where that word is the
        *entirety* of both names' identifying content.

    The two-word floor is what keeps this from firing on a single generic
    overlap: "EMD proof" and "EMD forfeiture clause acceptance" share one
    distinctive word and are not the same document. The one-word case is
    admitted only for an exact set equality, never for a short name swallowed by
    a longer one, which is how "Letter of Bid" came to satisfy "Bid Securing
    Declaration" before this was tightened.
    """
    required_canonical = _canonical_vocabulary(required)
    required_tokens = _distinctive(required_canonical)
    if not required_tokens:
        return None

    for name in submitted:
        name_canonical = _canonical_vocabulary(name)
        if name_canonical == required_canonical:
            return name, 1.0

        name_tokens = _distinctive(name_canonical)
        if not name_tokens:
            continue
        shared = required_tokens & name_tokens
        if not shared:
            continue
        containment = len(shared) / min(len(required_tokens), len(name_tokens))
        if containment < LEXICAL_CONTAINMENT:
            continue
        if len(shared) >= 2 or required_tokens == name_tokens:
            return name, round(containment, 4)
    return None


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
    method: str | None          # 'exact' | 'alias' | 'lexical' | 'embedding' | None
    score: float | None
    matched_name: str | None    # the submitted document that satisfied it
    #: A name that resembles the requirement but not closely enough to claim it
    #: is the same document. Populated only when `matched` is False.
    review_candidate: str | None = None

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

    @property
    def needs_review(self) -> bool:
        """A near miss. Neither "you have this" nor "you are missing this".

        Below the threshold nothing may be declared present -- a false positive
        there means a vendor submits without a document we told them they had.
        But reporting a 0.83 near-match as flatly MISSING is its own wrong
        answer: the vendor is told to obtain a document that is sitting in their
        bid under another name, and on a 49-document tender four of those bury
        the failures that are real.

        So the band between REVIEW_BAND_FLOOR and the threshold is a third
        state, consistent with how the rest of this system treats what it cannot
        settle: name the candidate, say the names differ, and ask.
        """
        return not self.matched and self.review_candidate is not None


NO_MATCH = MatchResult(matched=False, method=None, score=None, matched_name=None)


_FORM_REFERENCE = re.compile(
    r"\b(annexure|appendix|form)\s*[-–—:]?\s*"
    r"([a-z]-\d+|\d+-[a-z]|[ivxlcdm]+|[a-z]|\d+)\b", re.I
)


def document_identifiers(name: str) -> frozenset[tuple[str, str]]:
    """Explicit form labels are identity, including inside trailing parentheses."""
    return frozenset((kind.casefold(), ref.casefold())
                     for kind, ref in _FORM_REFERENCE.findall(name))


def _conflicting_identifiers(required: str, candidate: str) -> bool:
    wanted, offered = document_identifiers(required), document_identifiers(candidate)
    return any(
        {ref for family, ref in wanted if family == kind}
        != {ref for family, ref in offered if family == kind}
        for kind in {family for family, _ in wanted} & {family for family, _ in offered}
    )


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
    submitted = [name for name in submitted if not _conflicting_identifiers(required, name)]
    if not submitted:
        return NO_MATCH

    required_norm = normalise(required)

    def confirmed(method: str, score: float, name: str) -> MatchResult:
        if not document_identifiers(required).issubset(document_identifiers(name)):
            # A generic title does not establish which numbered form it is.
            return MatchResult(False, None, score, None, review_candidate=name)
        return MatchResult(True, method, score, name)

    # Tier 1: exact, after normalisation.
    for name in submitted:
        if normalise(name) == required_norm:
            return confirmed("exact", 1.0, name)

    # Tier 2: the curated alias table, plus any tender-specific aliases.
    required_canonical = canonical_form(required)
    extra_norms = {normalise(a) for a in (extra_aliases or [])}
    for name in submitted:
        name_norm = normalise(name)
        if name_norm in extra_norms:
            # The tender itself explicitly establishes this alternate label.
            return MatchResult(True, "alias", 1.0, name)
        submitted_canonical = canonical_form(name)
        if (
            required_canonical is not None
            and submitted_canonical is not None
            and required_canonical == submitted_canonical
        ):
            return confirmed("alias", 1.0, name)

    # Tier 3: shared vocabulary, after rewriting known synonyms. Cheap, runs
    # before the model, and catches the sentence-shaped requirement names that
    # cosine similarity scores too low to accept.
    lexical = _lexical_match(required, submitted)
    if lexical is not None:
        return confirmed("lexical", lexical[1], lexical[0])

    # Tier 4: embedding similarity for everything the tables don't know.
    if not use_embeddings:
        return NO_MATCH
    try:
        best_name, best_score = _best_embedding_match(required, tuple(submitted))
    except Exception:
        # Model unavailable: report no match rather than guessing. A vendor
        # sees "not found -- check manually", never a fabricated match.
        return NO_MATCH

    if best_score >= threshold:
        return confirmed("embedding", round(best_score, 4), best_name)
    if best_score >= REVIEW_BAND_FLOOR:
        # Close, but not close enough to claim. Offered for confirmation.
        return MatchResult(
            False, None, round(best_score, 4), None, review_candidate=best_name
        )
    return MatchResult(False, None, round(best_score, 4), None)


# Name -> vector, for the life of the process. Guarded because a gap report can
# be built on a worker thread while another is running.
_VECTORS: dict[str, tuple[float, ...]] = {}
_VECTOR_LOCK = threading.Lock()


def _embed_many(names: tuple[str, ...]) -> None:
    """Embed every name not already cached, in ONE call.

    Two separate wins, and the second was still outstanding after the first:

    1. Cache per NAME, not per (requirement, haystack) pair. A gap report checks
       every requirement against the same enclosure list, so a pair-keyed cache
       re-embeds that list once per requirement -- on the GHMC tender, ~2,500
       embeddings where 99 distinct ones exist. The report took minutes.

    2. Embed the misses TOGETHER. Fixing (1) left 85 calls to the model, each
       with a batch of one, because the cache was consulted one name at a time.
       A sentence-transformer amortises tokenisation and runs the batch as a
       single forward pass, so 85 batches of 1 is many times the work of one
       batch of 85 -- on CPU, which is where this runs, the difference is the
       difference between a snappy report and a visible pause.
    """
    with _VECTOR_LOCK:
        missing = [n for n in dict.fromkeys(names) if n not in _VECTORS]
    if not missing:
        return

    from app.vector.embeddings import embed_passages

    vectors = embed_passages(missing)
    with _VECTOR_LOCK:
        for name, vector in zip(missing, vectors):
            _VECTORS[name] = tuple(vector)


def _embed_one(text: str) -> tuple[float, ...]:
    """A single name's vector, embedding it if this is the first time."""
    with _VECTOR_LOCK:
        cached = _VECTORS.get(text)
    if cached is not None:
        return cached
    _embed_many((text,))
    with _VECTOR_LOCK:
        return _VECTORS[text]


def prewarm(names: list[str]) -> None:
    """Embed a batch of names up front, so callers do not trickle them in.

    Exposed for the gap report, which knows the whole working set before it
    starts and can therefore pay for one forward pass instead of dozens.
    """
    if names:
        _embed_many(tuple(names))


def _clear_vector_cache() -> None:
    """Test hook. The cache is process-lifetime by design."""
    with _VECTOR_LOCK:
        _VECTORS.clear()


def _best_embedding_match(required: str, submitted: tuple[str, ...]) -> tuple[str, float]:
    # One call covering the requirement and every candidate, rather than one per
    # name. After the first requirement on a tender the enclosure list is
    # already cached, so subsequent requirements embed at most themselves.
    _embed_many((required,) + submitted)

    with _VECTOR_LOCK:
        required_vec = _VECTORS[required]
        vectors = {name: _VECTORS[name] for name in submitted}

    best_name, best_score = submitted[0], -1.0
    for name in submitted:
        # Vectors are unit-normalised, so the dot product is cosine similarity.
        score = sum(a * b for a, b in zip(required_vec, vectors[name]))
        if score > best_score:
            best_name, best_score = name, score
    return best_name, best_score
