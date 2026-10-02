"""Query-side expansion of Indian procurement vocabulary (Section 4.5).

Tender documents write "EMD"; vendors ask about "earnest money". Those are the
same thing and a dense retriever does not know it.

Measured against the real GHMC chunk
`[table on page 2] 11. | emd @ 1% | rs. 2,98,720.00`:

    0.4621   "What is the earnest money payable for this tender?"
    0.6429   "What is the EMD payable for this tender?"

An 0.18 cosine penalty for using the long form of the term the document
abbreviates -- enough to drop the correct chunk from rank 1 to rank 193 of 388,
which is how three of this corpus's EMD questions came to be unanswerable.

Expansion is applied to the QUERY only. Rewriting indexed text would work
equally well on paper (0.4621 -> 0.6310 when the chunk itself is expanded) and
was rejected: citation highlighting matches the stored snippet against words on
the source page, so editing what we store to improve retrieval would degrade
the provenance the whole product rests on.

WHY A LOOKUP AND NOT AN LLM. This runs on every question. A glossary is free,
deterministic, inspectable, and cannot hallucinate a synonym -- and a wrong
expansion measurably HURTS: appending "EMD" to "By when must I upload my bid?"
moved the correct deadline chunk from 0.6941 to 0.6090. So terms are expanded
only when actually present, and the table below is the whole of the behaviour.
"""

from __future__ import annotations

import re

#: Bidirectional domain vocabulary. Each entry lists forms that mean the same
#: thing; whichever appears in the question, the others are appended.
#:
#: Short, ambiguous abbreviations are deliberately absent. "SD" (security
#: deposit) collides with ordinary words and "PG" means both performance
#: guarantee and postgraduate in Indian tender prose, so neither is expanded
#: from its abbreviation -- only toward it.
_EQUIVALENCES: tuple[tuple[str, ...], ...] = (
    ("earnest money deposit", "earnest money", "emd", "bid security"),
    ("estimated contract value", "ecv", "estimated cost put to tender"),
    ("initial security deposit", "isd"),
    ("performance guarantee", "performance bank guarantee"),
    ("bank guarantee", "bg"),
    ("bill of quantities", "boq"),
    ("notice inviting tender", "nit"),
    ("operation and maintenance", "o&m"),
    ("defect liability period", "dlp"),
    ("joint venture", "jv"),
    ("letter of intent", "loi"),
    ("memorandum of understanding", "mou"),
    ("goods and services tax", "gst"),
    ("permanent account number", "pan"),
    ("micro small and medium enterprises", "msme"),
    ("engineering procurement and construction", "epc"),
    ("pre-qualification", "prequalification", "pq"),
    ("turnover", "annual turnover", "average annual turnover"),
    ("blacklisted", "debarred", "blacklisting"),
)

#: Longest form first, so "earnest money deposit" is matched before "earnest
#: money" and the term is not expanded twice.
_TERMS: list[tuple[str, tuple[str, ...]]] = sorted(
    ((term, group) for group in _EQUIVALENCES for term in group),
    key=lambda pair: -len(pair[0]),
)


def _present(term: str, haystack: str) -> bool:
    """Whole-term match, so "pan" does not fire inside "expansion"."""
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack) is not None


def expand_query(question: str, *, max_additions: int = 4) -> str:
    """Append the equivalent forms of any domain term present in the question.

    The original wording is preserved and leads, because it carries the user's
    actual emphasis; additions are appended as bare terms. Returns the question
    unchanged when it contains no known term, which is the common case for
    free-form questions and keeps this a no-op rather than a distortion.
    """
    if not question or not question.strip():
        return question

    lowered = question.casefold()
    additions: list[str] = []
    matched_groups: set[tuple[str, ...]] = set()

    for term, group in _TERMS:
        if group in matched_groups or not _present(term, lowered):
            continue
        matched_groups.add(group)
        for other in group:
            if other != term and not _present(other, lowered) and other not in additions:
                additions.append(other)

    # Slice BEFORE deciding whether anything was added: with max_additions=0
    # the earlier form appended an empty join and returned the question with a
    # trailing space -- a modified query that added nothing.
    kept = additions[: max(0, max_additions)]
    if not kept:
        return question
    return f"{question} {' '.join(kept)}"
