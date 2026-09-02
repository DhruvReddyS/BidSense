"""Post-extraction plausibility checks (Section 10, extraction accuracy).

Extraction can fail without raising. Every node returns, no error is recorded,
the report says OK -- and the notification has no deadline, no EMD and no
issuing authority, because the model quietly returned null for all three. That
is the worst failure mode this system has, because everything downstream treats
a missing value as a fact about the tender rather than a fact about the
extraction. A gap report built on a notification with no deadline tells a vendor
nothing is due.

Measured, not hypothetical. The same 101-page tender, the same model, differing
only in the PROMPT -- an earlier version of this docstring blamed the model, and
that was wrong:

    field               gemini-3.5-flash    qwen3:4b bare   qwen3:4b few-shot
    issuing_authority   IIT (ISM) Dhanbad   (empty)         IIT (ISM) Dhanbad
    submission_deadline 2026-08-22          None            2026-08-22
    emd_amount          Rs. 31,500/-        None            Rs. 31,500/-
    errors reported     0                   0               0

All three runs reported success. The middle column is the one this module exists
for, and the point generalises past any one model: an extraction can be empty,
report no error, and be presented as clean -- whether the cause is a weak model,
a weak prompt, or a page selection that sent the wrong pages. The validator does
not need to know which.

Two principles, the same ones the gap report runs on:

  * A finding is about the EXTRACTION, never about the tender. "We could not
    find a deadline in this document" is the claim; "this tender has no
    deadline" is not, and is what a bare null implies downstream.
  * Nothing here changes a value. Findings are attached and surfaced; a
    validator that silently corrected what it disliked would be a second,
    unauditable extractor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.extraction.patterns import find_header_candidates
from app.ingest.models import ParsedDocument
from app.schemas.notification import TenderNotification
from app.schemas.submission import VendorSubmission

__all__ = [
    "Finding",
    "Severity",
    "validate_notification",
    "validate_submission",
    "summarise",
    "affects_confidence",
]


class Severity(StrEnum):
    #: The value is impossible, not merely surprising -- a deadline before the
    #: pre-bid meeting, a negative amount, a citation to page 400 of a 68-page
    #: document. Something was misread.
    ERROR = "error"
    #: Plausible but worth a human glance: a field a tender of this kind almost
    #: always states, absent; a deadline already past.
    WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    field: str
    severity: Severity
    message: str
    value: str | None = None
    #: Whether this casts doubt on the EXTRACTION, as opposed to reporting
    #: something true but notable about the tender itself.
    #:
    #: The distinction decides whether a run is downgraded to PARTIAL, and it
    #: matters: a deadline that has already passed is a correct reading of an
    #: expired tender, and marking that run "partial" would train everyone to
    #: ignore the flag. A deadline that is simply absent is the opposite -- the
    #: document almost certainly stated one and we did not find it.
    affects_confidence: bool = True

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"[{self.severity.value}] {self.field}: {self.message}"


# Fields a real Indian tender notification states in essentially every case.
# Their absence is far more likely to be a missed extraction than a tender that
# genuinely does not say when bids are due.
_EXPECTED_NOTIFICATION_FIELDS = {
    "submission_deadline": "the last date for submitting bids",
    "issuing_authority": "the department or authority issuing the tender",
    "emd_amount": "the earnest money deposit",
}

# Above this, a "years in business" figure is a misread date rather than a firm
# founded before the Mughal empire.
_MAX_PLAUSIBLE_YEARS = 150


def _amount(money) -> Decimal | None:
    return money.amount_inr if money is not None else None


def _page_findings(
    prefix: str, provenances: list[tuple[str, object]], document: ParsedDocument | None
) -> list[Finding]:
    """Citations must resolve to a page that exists.

    A `source_page` outside the document is not a cosmetic problem: the citation
    is the whole basis on which a vendor is asked to believe an extracted value,
    and one pointing at page 400 of a 68-page tender cannot be checked. It also
    reliably means the model invented the anchor rather than read it.
    """
    if document is None or not document.pages:
        return []
    last = document.page_count
    findings: list[Finding] = []
    for label, provenance in provenances:
        page = getattr(provenance, "source_page", None)
        if page is None:
            continue
        if page < 1 or page > last:
            findings.append(
                Finding(
                    field=f"{prefix}.{label}",
                    severity=Severity.ERROR,
                    message=(
                        f"cites page {page}, but the document has {last} page"
                        f"{'s' if last != 1 else ''}. The citation cannot be checked."
                    ),
                    value=str(page),
                )
            )
    return findings


def validate_notification(
    notification: TenderNotification,
    document: ParsedDocument | None = None,
    *,
    today: date | None = None,
    selected_pages: list[int] | None = None,
) -> list[Finding]:
    """Plausibility of an extracted notification, before it reaches a vendor."""
    today = today or date.today()
    findings: list[Finding] = []

    # Deterministic cross-check, consulted ONLY where the model returned
    # nothing. A pattern that disagrees with an extracted value is not
    # automatically right, and overriding on that basis would be a second
    # unauditable extractor -- so this speaks only into silence.
    patterns = (
        find_header_candidates(document, selected_pages) if document is not None else {}
    )

    # --- fields that should be there and are not -------------------------- #
    for attribute, description in _EXPECTED_NOTIFICATION_FIELDS.items():
        value = getattr(notification, attribute, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            hit = patterns.get(attribute)
            if hit is not None:
                # The document does state it, in a form a pattern can locate.
                # That is a much stronger claim than "this is probably missing",
                # and it is actionable: the reviewer can confirm it in one look.
                findings.append(
                    Finding(
                        field=attribute,
                        severity=Severity.ERROR,
                        message=(
                            f"no value for {description} was extracted, but page "
                            f"{hit.page} of the document appears to state it: "
                            f"\u201c{hit.value}\u201d, read from \u201c{hit.line}\u201d. "
                            "The model missed a value that is present -- check it "
                            "before relying on this extraction."
                        ),
                        value=hit.value,
                    )
                )
                continue
            findings.append(
                Finding(
                    field=attribute,
                    severity=Severity.WARNING,
                    message=(
                        f"no value for {description} was found. Almost every tender "
                        "states one, so this is more likely a missed extraction "
                        "than a tender that does not say."
                    ),
                )
            )

    # --- dates ------------------------------------------------------------ #
    deadline = notification.submission_deadline
    pre_bid = notification.pre_bid_query_deadline
    if deadline is not None and deadline < today:
        findings.append(
            Finding(
                field="submission_deadline",
                severity=Severity.WARNING,
                message=(
                    f"the deadline read from the document ({deadline.isoformat()}) has "
                    "already passed. Either this tender is closed, or the date was "
                    "misread."
                ),
                value=deadline.isoformat(),
                # A closed tender is a real thing, correctly read. Surfaced, but
                # it does not mean the extraction went wrong.
                affects_confidence=False,
            )
        )
    if deadline is not None and pre_bid is not None and pre_bid > deadline:
        findings.append(
            Finding(
                field="pre_bid_query_deadline",
                severity=Severity.ERROR,
                message=(
                    f"pre-bid queries close ({pre_bid.isoformat()}) after bids are due "
                    f"({deadline.isoformat()}), which cannot be right. One of the two "
                    "dates was misread."
                ),
                value=pre_bid.isoformat(),
            )
        )

    # --- money ------------------------------------------------------------ #
    emd = _amount(notification.emd_amount)
    estimate = _amount(notification.contract_value_estimate)
    for label, value in (("emd_amount", emd), ("contract_value_estimate", estimate)):
        if value is not None and value <= 0:
            findings.append(
                Finding(
                    field=label,
                    severity=Severity.ERROR,
                    message=(
                        f"resolved to {value}, which is not a real amount. The printed "
                        "figure was probably a percentage or a footnote marker."
                    ),
                    value=str(value),
                )
            )
    if emd is not None and estimate is not None and emd > estimate:
        findings.append(
            Finding(
                field="emd_amount",
                severity=Severity.ERROR,
                message=(
                    f"the EMD ({emd}) is larger than the whole estimated contract value "
                    f"({estimate}). One of the two figures carries the wrong magnitude."
                ),
                value=str(emd),
            )
        )

    # --- thresholds ------------------------------------------------------- #
    for index, criterion in enumerate(notification.eligibility_criteria):
        threshold = _amount(criterion.threshold_amount)
        if threshold is not None and threshold <= 0:
            findings.append(
                Finding(
                    field=f"eligibility_criteria[{index}].threshold_amount",
                    severity=Severity.ERROR,
                    message=(
                        f"resolved to {threshold} from {criterion.threshold_raw!r}. A "
                        "threshold of zero passes every bidder, so it is never a "
                        "harmless value to leave in place."
                    ),
                    value=criterion.threshold_raw,
                )
            )

    # --- did anything come back at all? ----------------------------------- #
    if not notification.eligibility_criteria:
        findings.append(
            Finding(
                field="eligibility_criteria",
                severity=Severity.WARNING,
                message=(
                    "no eligibility criteria were extracted. A gap report against this "
                    "tender can only check documents, and would report a bid as clear "
                    "without having tested any threshold."
                ),
            )
        )
    if not notification.mandatory_documents:
        findings.append(
            Finding(
                field="mandatory_documents",
                severity=Severity.WARNING,
                message="no required documents were extracted from this tender.",
            )
        )

    findings += _page_findings(
        "eligibility_criteria",
        [(str(i), c.provenance) for i, c in enumerate(notification.eligibility_criteria)],
        document,
    )
    findings += _page_findings(
        "mandatory_documents",
        [(str(i), d.provenance) for i, d in enumerate(notification.mandatory_documents)],
        document,
    )
    return findings


def validate_submission(
    submission: VendorSubmission, document: ParsedDocument | None = None
) -> list[Finding]:
    """Plausibility of an extracted bid."""
    findings: list[Finding] = []

    for index, entry in enumerate(submission.turnover):
        value = _amount(entry.amount)
        if value is not None and value <= 0:
            findings.append(
                Finding(
                    field=f"turnover[{index}]",
                    severity=Severity.ERROR,
                    message=(
                        f"turnover for {entry.year} resolved to {value} from "
                        f"{entry.amount.raw_text!r}. A zero turnover fails every "
                        "financial threshold, so a misread here eliminates a bidder."
                    ),
                    value=entry.amount.raw_text,
                )
            )

    for label, money in (
        ("quoted_price", submission.quoted_price),
        ("liquid_assets", submission.liquid_assets),
        ("net_worth", submission.net_worth),
    ):
        value = _amount(money)
        # Net worth can legitimately be negative; a quoted price cannot be zero.
        if value is not None and value <= 0 and label != "net_worth":
            findings.append(
                Finding(
                    field=label,
                    severity=Severity.ERROR,
                    message=f"resolved to {value} from {money.raw_text!r}, which is not a real amount.",
                    value=money.raw_text,
                )
            )

    years = submission.years_in_business
    if years is not None and (years < 0 or years > _MAX_PLAUSIBLE_YEARS):
        findings.append(
            Finding(
                field="years_in_business",
                severity=Severity.ERROR,
                message=(
                    f"{years} years in business is not plausible; the establishment "
                    "year was probably read as a different number."
                ),
                value=str(years),
            )
        )

    if not submission.turnover:
        findings.append(
            Finding(
                field="turnover",
                severity=Severity.WARNING,
                message=(
                    "no turnover figures were extracted. Every financial threshold in "
                    "the gap report will report as needs-manual-check rather than "
                    "being tested."
                ),
            )
        )
    if not submission.documents_submitted:
        findings.append(
            Finding(
                field="documents_submitted",
                severity=Severity.WARNING,
                message=(
                    "no enclosure list was extracted. Every required document will "
                    "report as missing, whether or not it was actually enclosed."
                ),
            )
        )

    findings += _page_findings(
        "turnover",
        [(str(i), t.provenance) for i, t in enumerate(submission.turnover)],
        document,
    )
    findings += _page_findings(
        "documents_submitted",
        [(str(i), d.provenance) for i, d in enumerate(submission.documents_submitted)],
        document,
    )
    return findings


def affects_confidence(findings: list[Finding]) -> bool:
    """Whether any finding casts doubt on the extraction itself."""
    return any(f.affects_confidence for f in findings)


def summarise(findings: list[Finding]) -> str | None:
    """One line for a job result or a UI banner. None when nothing was found."""
    findings = [f for f in findings if f.affects_confidence]
    if not findings:
        return None
    errors = sum(1 for f in findings if f.severity is Severity.ERROR)
    warnings = len(findings) - errors
    parts = []
    if errors:
        parts.append(f"{errors} implausible value{'s' if errors != 1 else ''}")
    if warnings:
        parts.append(f"{warnings} field{'s' if warnings != 1 else ''} that may have been missed")
    return (
        "This extraction needs review: "
        + " and ".join(parts)
        + ". The figures below may be incomplete."
    )
