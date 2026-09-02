"""Diff an extracted corrigendum against the notification it amends.

Deterministic and LLM-free, for the same reason `app.normalize.money` is: once
both values are extracted, comparing them is arithmetic, and a model asked to
"work out what changed" produces a plausible answer that cannot be audited. The
model's job here was only to read what the amendment printed.

Two sources of change, and they are kept apart:

  RESTATED FIELDS   the corrigendum prints a new deadline or a new EMD. The old
                    value comes from our own database, not from the model, so
                    `old_value` is always something we can stand behind.
  STATED CHANGES    the corrigendum says "in place of X read Y" in prose. Both
                    values come from the document; `field_path` is inferred in
                    code from the subject line, and stays `unmapped` when the
                    subject matches nothing we hold. An unmapped change is
                    reported to the vendor rather than dropped -- "the tender
                    changed something we could not place" is a true and useful
                    statement, and silently discarding it is not.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from app.extraction import llm_schemas as raw
from app.extraction.convert import parse_date, to_provenance
from app.normalize.money import try_normalize_amount
from app.schemas.common import Provenance
from app.schemas.corrigendum import ChangedField, Corrigendum
from app.schemas.notification import TenderNotification

__all__ = ["diff_corrigendum", "FIELD_LABELS"]

# Human-readable names for the dotted field paths, used by the UI banner and the
# action list. Kept beside the paths so the two cannot drift.
FIELD_LABELS: dict[str, str] = {
    "submission_deadline": "bid submission deadline",
    "pre_bid_query_deadline": "pre-bid query deadline",
    "emd_amount": "EMD amount",
    "contract_value_estimate": "estimated contract value",
}

# Subject wording -> the notification field it refers to. Ordered: the first
# pattern that matches wins, so the more specific ones come first.
_SUBJECT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"pre[\s-]*bid|clarification|query", re.I), "pre_bid_query_deadline"),
    (
        re.compile(r"last date|due date|closing|submission of bids?|bid submission|deadline", re.I),
        "submission_deadline",
    ),
    (re.compile(r"\bemd\b|earnest money|bid security", re.I), "emd_amount"),
    (re.compile(r"estimated cost|contract value|ecv|estimated value", re.I), "contract_value_estimate"),
    (re.compile(r"turnover|revenue", re.I), "eligibility_criteria.turnover"),
    (re.compile(r"experience|similar work|completed work", re.I), "eligibility_criteria.experience"),
    (re.compile(r"net worth|solvency|liquid|working capital", re.I), "eligibility_criteria.financial"),
    (re.compile(r"document|certificate|annexure|form\b", re.I), "mandatory_documents"),
]

UNMAPPED = "unmapped"

# Paths whose value has a shape, and the test for it. A subject line can read
# like a field without being one: "the pre-bid meeting shall now be held in
# hybrid mode" matches the pre-bid pattern, but its new value is not a date and
# it is not an amendment to the pre-bid deadline. Without this check that change
# is classified onto a field already amended, deduplicated away, and lost --
# silently, which is the one outcome this whole feature exists to prevent.
_VALUE_SHAPE = {
    "submission_deadline": lambda v: parse_date(v) is not None,
    "pre_bid_query_deadline": lambda v: parse_date(v) is not None,
    "emd_amount": lambda v: try_normalize_amount(v) is not None,
    "contract_value_estimate": lambda v: try_normalize_amount(v) is not None,
}


def _classify(subject: str, new_value: str | None = None) -> str:
    """Which notification field a stated change refers to, if any.

    Matched on the subject line, then confirmed against the shape of the value.
    A wrong field here is worse than `unmapped`: unmapped still reaches the
    vendor as "the tender changed something we could not place", whereas a
    misfiled change is either deduplicated away or reported against a field it
    never touched.
    """
    for pattern, path in _SUBJECT_PATTERNS:
        if not pattern.search(subject or ""):
            continue
        shape = _VALUE_SHAPE.get(path)
        if shape is not None and not shape(new_value):
            return UNMAPPED
        return path
    return UNMAPPED


def _render(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _same_amount(old_raw: str | None, new_raw: str | None) -> bool:
    """Whether two printed amounts mean the same rupee figure.

    "Rs. 2,00,000" and "Rs. 2 Lakh" are not the same string and are the same
    money. Reporting that as an amendment would put a stale-tender banner in
    front of every vendor for a corrigendum that changed nothing.
    """
    old, new = try_normalize_amount(old_raw), try_normalize_amount(new_raw)
    if old is None or new is None:
        return (old_raw or "").strip() == (new_raw or "").strip()
    return old == new


def _restated_fields(
    parent: TenderNotification,
    header: raw.RawCorrigendumHeader,
    provenance: Provenance,
) -> list[ChangedField]:
    """Fields the corrigendum reprints, compared against what we already hold."""
    changes: list[ChangedField] = []

    for attribute, new_text in (
        ("submission_deadline", header.submission_deadline),
        ("pre_bid_query_deadline", header.pre_bid_query_deadline),
    ):
        if not new_text:
            continue                       # null means "unchanged", not "cleared"
        new_date = parse_date(new_text)
        if new_date is None:
            continue                       # unparseable: not asserted as a change
        old_date = getattr(parent, attribute)
        if old_date == new_date:
            continue
        changes.append(
            ChangedField(
                field_path=attribute,
                old_value=_render(old_date),
                new_value=new_date.isoformat(),
                provenance=provenance,
            )
        )

    for attribute, new_text in (
        ("emd_amount", header.emd_amount_raw),
        ("contract_value_estimate", header.contract_value_raw),
    ):
        if not new_text:
            continue
        old_money = getattr(parent, attribute)
        old_text = old_money.raw_text if old_money else None
        if _same_amount(old_text, new_text):
            continue
        changes.append(
            ChangedField(
                field_path=attribute,
                old_value=old_text,
                new_value=new_text,
                provenance=provenance,
            )
        )

    return changes


def diff_corrigendum(
    parent: TenderNotification,
    header: raw.RawCorrigendumHeader,
    stated: list[raw.RawCorrigendumChange],
    *,
    source_file: str | None = None,
) -> Corrigendum:
    """Build the Section 6 Corrigendum, with `changed_fields` resolved in code."""
    issued = parse_date(header.issued_date)
    header_provenance = Provenance(
        clause_ref=None,
        source_page=1,
        source_snippet=source_file,
        extraction_confidence=None,
    )

    changes = _restated_fields(parent, header, header_provenance)
    already = {c.field_path for c in changes}

    for item in stated:
        path = _classify(item.subject, item.new_value)
        # A restated header field already produced a change with an old value we
        # can vouch for. The prose restatement of the same field would duplicate
        # it, usually with a vaguer old_value.
        if path in already:
            continue
        changes.append(
            ChangedField(
                field_path=path if path != UNMAPPED else f"unmapped:{item.subject[:80]}",
                old_value=item.old_value,
                new_value=item.new_value,
                provenance=to_provenance(item),
            )
        )

    return Corrigendum(
        corrigendum_id=(
            header.corrigendum_id
            or (f"CORRIGENDUM/{source_file}" if source_file else "CORRIGENDUM")
        ),
        parent_tender_id=header.parent_tender_id or parent.tender_id,
        issued_date=issued,
        changed_fields=changes,
    )
