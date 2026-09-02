"""Deterministic pattern extraction for the predictably-formatted header fields.

An extension of the principle already running through this codebase: the model
never computes, and code does anything that can be done exactly. Applied here to
LOCATION rather than arithmetic. Finding "Earnest Money Rs. 31,500/-" in a
key-dates table needs pattern matching, not comprehension -- the label is one of
a dozen known phrasings and the value is a rupee amount on the same line.

This is a CROSS-CHECK, never an override. Three rules make it safe:

  * It only speaks when the model stayed silent. A value the model returned is
    the model's answer, and a regex that disagrees is not automatically right.
  * It never writes into the extracted record. Findings go to the Stage 4
    validation pass, which surfaces them for review. A silent correction would
    be a second unauditable extractor, which is the thing the whole "code never
    guesses" rule exists to prevent.
  * It reports the page and the line it matched, so the reviewer can check it in
    one glance rather than taking its word.

Why these fields: every extraction failure measured tonight clustered on the
same three -- issuing authority, submission deadline, EMD -- across every local
model tested. They are also the three with the most regular printed form, which
is exactly the combination that makes a deterministic backstop worth having.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.extraction.convert import parse_date
from app.ingest.models import ParsedDocument
from app.normalize.money import try_normalize_amount

__all__ = ["PatternHit", "find_header_candidates"]


@dataclass(frozen=True)
class PatternHit:
    """A value found by pattern, with enough context to check it by eye."""

    field: str
    value: str
    page: int
    line: str
    #: Which labelled pattern matched, for the audit trail.
    rule: str


# Label -> field. Ordered most specific first: "Last Date for submission of EMD"
# is not the bid deadline, and a looser "last date" rule would claim it.
_DEADLINE_LABELS = (
    r"last date (?:and time )?for (?:uploading|upload|submission) of (?:e-?)?bids?",
    r"bid submission (?:end )?date(?: ?& ?time)?",
    r"last date (?:and time )?(?:for|of) (?:online )?submission(?! of emd)",
    r"due date (?:and time )?for submission",
    r"closing date (?:and time )?(?:of|for) (?:the )?(?:bid|tender)",
    r"end date (?:and time )?(?:for|of) bid submission",
)
_PREBID_LABELS = (
    r"last date (?:and time )?for receipt of (?:queries|clarifications?)",
    r"pre[\s-]?bid (?:meeting|conference|query|queries|clarification)[^:\n]{0,30}date",
    r"last date (?:and time )?for (?:seeking )?clarifications?",
)
_EMD_LABELS = (
    r"earnest money(?: deposit)?(?: \(emd\))?",
    r"\bemd\b(?: amount)?",
    r"bid security(?: amount)?",
)

# A date as Indian tenders print it: 22.08.2026, 22-08-2026, 22 August 2026.
_DATE = re.compile(
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
    r"|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4})",
    re.IGNORECASE,
)
# A rupee amount. Requires a currency marker or Indian digit grouping, so a bare
# "2026" on the same line is not read as an amount.
_MONEY = re.compile(
    r"((?:rs\.?|inr|₹)\s*[\d,][\d,\s]*(?:\.\d+)?(?:\s*/-)?"
    r"|\b\d{1,3}(?:,\d{2})+,\d{3}(?:\.\d+)?\b)",
    re.IGNORECASE,
)

# Words that make a line the name of an ISSUING BODY rather than prose. Matched
# anywhere in the line rather than at a fixed position: a letterhead reads
# "Indian Institute of Technology (Indian School of Mines) Dhanbad" and
# "HYDERABAD GROWTH CORRIDOR LIMITED", and a pattern anchored on a leading
# capital-then-noun shape misses both -- the noun IS the start of the first, and
# the second's noun ("corridor limited") is not in any sensible whitelist.
_ORG_WORDS = re.compile(
    r"\b(?:municipal corporation|nagar nigam|municipality|panchayat|zilla parishad"
    r"|development authority|improvement trust|smart city"
    r"|public works|jal board|electricity board|power distribution|transmission corporation"
    r"|metro rail|port trust|airport authority"
    r"|institute of|university|college|vidyalaya|hospital"
    r"|corporation|nigam|limited|ltd\.?|pvt|board|department|directorate|ministry"
    r"|commission|council|authority|undertaking|bhavan|sansthan"
    r"|government of|govt\.? of|office of the)\b",
    re.IGNORECASE,
)

# Lines that carry an org word but are not the issuer's name.
_NOT_A_NAME = re.compile(
    r"^\s*(?:name of (?:the )?work|sub|subject|ref|tender|bid|nit|e-?tender|notice"
    r"|phone|tel|fax|email|e-mail|website|www|page|annexure|form|section|clause"
    r"|date|last date|estimated|earnest|contract|scope|for and on behalf)\b",
    re.IGNORECASE,
)

# Lines a label match must NOT be taken from: a table of contents entry, an
# instruction about a form, or a clause reference.
_NOISE = re.compile(r"\.{4,}|page \d+ of \d+|as per (?:form|annexure)", re.IGNORECASE)


def _labelled_value(
    text: str, page: int, labels: tuple[str, ...], value_re: re.Pattern[str], field: str
) -> PatternHit | None:
    """Find `value_re` on a line whose label matches, or on the line after it.

    The line after matters because tenders lay these out as two-column tables
    that flatten to "Last Date and Time for uploading of Bids\\n22 August 2026".
    """
    lines = text.splitlines()
    for label in labels:
        pattern = re.compile(label, re.IGNORECASE)
        for index, line in enumerate(lines):
            if not pattern.search(line) or _NOISE.search(line):
                continue
            for candidate in (line, *(lines[index + 1 : index + 2])):
                match = value_re.search(candidate)
                if match:
                    return PatternHit(
                        field=field,
                        value=match.group(1).strip(),
                        page=page,
                        line=" ".join(line.split())[:160],
                        rule=label[:48],
                    )
    return None


def _authority(text: str, page: int) -> PatternHit | None:
    """The issuing authority, taken from the top of the front page only.

    Restricted to the head of page 1 on purpose: a tender names dozens of
    organisations in its conditions, and the one that ISSUED it is in the
    letterhead. Searching the whole document reliably finds the wrong one --
    usually a bank named in the EMD clause.

    Scored line by line rather than matched positionally. A letterhead is a
    short line containing an institutional word, and which part of the line the
    word sits in carries no information.
    """
    for line in text.splitlines()[:8]:
        stripped = " ".join(line.split())
        if not (8 <= len(stripped) <= 120):
            continue
        if _NOT_A_NAME.match(stripped) or _NOISE.search(stripped):
            continue
        if not _ORG_WORDS.search(stripped):
            continue
        # A line that is mostly digits or punctuation is an address or a code.
        letters = sum(c.isalpha() for c in stripped)
        if letters < len(stripped) * 0.6:
            continue
        return PatternHit(
            field="issuing_authority", value=stripped[:200], page=page,
            line=stripped[:160], rule="letterhead",
        )
    return None


def find_header_candidates(
    document: ParsedDocument, pages: list[int] | None = None
) -> dict[str, PatternHit]:
    """Locate the header fields deterministically, where the format allows.

    `pages` restricts the search to the pages actually sent to the model, so the
    backstop is answering the same question the model was asked. Searching pages
    the model never saw would produce "the regex found it and you didn't" for a
    value that was never in front of it.
    """
    considered = [
        page for page in document.pages
        if pages is None or page.page_number in pages
    ]
    found: dict[str, PatternHit] = {}

    for page in considered:
        text = page.combined_text()
        if not text:
            continue

        if "submission_deadline" not in found:
            hit = _labelled_value(
                text, page.page_number, _DEADLINE_LABELS, _DATE, "submission_deadline"
            )
            if hit and parse_date(hit.value):
                found["submission_deadline"] = hit

        if "pre_bid_query_deadline" not in found:
            hit = _labelled_value(
                text, page.page_number, _PREBID_LABELS, _DATE, "pre_bid_query_deadline"
            )
            if hit and parse_date(hit.value):
                found["pre_bid_query_deadline"] = hit

        if "emd_amount" not in found:
            hit = _labelled_value(text, page.page_number, _EMD_LABELS, _MONEY, "emd_amount")
            # A percentage-based EMD ("1% of the ECV") is a real and common form
            # that this backstop cannot resolve -- it needs the contract value,
            # which is code's job elsewhere. Better to stay silent than to offer
            # "Rs. 1".
            if hit and try_normalize_amount(hit.value):
                found["emd_amount"] = hit

        if "issuing_authority" not in found and page.page_number <= 2:
            hit = _authority(text, page.page_number)
            if hit:
                found["issuing_authority"] = hit

    return found
