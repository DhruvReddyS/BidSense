"""Deterministic shortlist signals and cross-vendor query routing.

Scores are used only to reduce a large pool to the reviewer-requested size. They
are never exposed as a legal rank and every selected candidate carries the raw
facts that caused inclusion.

Three properties of the reduction are load-bearing, and each was a real defect:

  MISSING IS NOT WORST   A factor the extractor could not read is dropped from
                         that candidate's score, and the remaining weights are
                         renormalised. Scoring it zero -- which is what the
                         earlier min-max pass did -- silently penalised a vendor
                         for OUR extraction failure, and ranked a vendor whose
                         price was unreadable identically to one who quoted the
                         worst price in the pool. The vendor-side report is
                         explicit that "we could not read this" is not the same
                         as failing; the reduction must not contradict it.
  RANK, NOT MIN-MAX      Positions, not magnitudes. One ten-thousand-crore
                         outlier under min-max compressed three genuinely
                         different vendors into [0.0, 0.002, 0.004] -- erasing
                         exactly the distinction the reduction exists to make.
                         Rank normalisation is monotone-invariant, so a single
                         extreme bid cannot flatten the rest of the pool.
  TIES ARE NOT BROKEN    Candidates tied at the cut-off are all included, so the
                         pool may exceed the requested size. Taking whichever of
                         two equally-scored vendors happened to sort first by
                         vendor_id is an arbitrary exclusion, and an arbitrary
                         exclusion from a procurement shortlist is precisely the
                         kind of decision that cannot be defended on challenge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal


FACTOR_KEYS = {"experience", "project_scale", "technical_approach", "pricing"}


@dataclass(frozen=True)
class Candidate:
    row: object
    vendor_id: str
    vendor_name: str
    experience: float | None
    project_scale: Decimal | None
    technical_approach: float
    pricing: Decimal | None


def build_candidate(row: object) -> Candidate:
    projects = list(getattr(row, "past_projects", ()) or ())
    values = [p.value_inr for p in projects if p.value_inr is not None]
    return Candidate(
        row=row,
        vendor_id=row.vendor_id,
        vendor_name=row.vendor_name,
        # `or 0` here read a vendor whose years-in-business could not be
        # extracted as a vendor founded this year. None means unknown.
        experience=(
            None if getattr(row, "years_in_business", None) is None
            else float(row.years_in_business)
        ),
        project_scale=max(values) if values else None,
        technical_approach=1.0 if row.has_technical_approach else 0.0,
        pricing=row.quoted_price_inr,
    )


def _normalise(
    values: list[Decimal | float | None], *, lower_is_better: bool = False
) -> list[float | None]:
    """Rank-normalise to [0, 1], preserving None as "unknown".

    Returns None in every position whose input was None. Callers must therefore
    renormalise over the factors actually present for a candidate rather than
    treating a gap as a zero -- see the module docstring.

    Tied inputs share their average rank, so equal values produce equal signals
    and cannot be separated by list order.
    """
    known = sorted({float(value) for value in values if value is not None})
    if not known:
        return [None] * len(values)
    if len(known) == 1:
        # One distinct value: present candidates are indistinguishable on this
        # factor. Scoring them 1.0 keeps the factor from dragging the whole
        # composite down when every candidate is identical on it.
        return [None if value is None else 1.0 for value in values]

    span = len(known) - 1
    position = {value: index / span for index, value in enumerate(known)}
    return [
        None
        if value is None
        else (1.0 - position[float(value)] if lower_is_better else position[float(value)])
        for value in values
    ]


@dataclass(frozen=True)
class ShortlistEntry:
    """A selected candidate and the basis on which it was selected."""

    candidate: Candidate
    score: float | None
    #: Factor keys that contributed. Shorter than the requested set means the
    #: extractor could not read the rest for this vendor.
    scored_on: tuple[str, ...]
    #: Requested factors this vendor could not be scored on.
    unscored: tuple[str, ...]
    #: True when the vendor shares the cut-off score with another vendor and is
    #: included because ties are not broken arbitrarily.
    tied_at_cutoff: bool = False

    @property
    def basis(self) -> str:
        """One line a reviewer can read, naming what the score rests on."""
        total = len(self.scored_on) + len(self.unscored)
        if self.score is None:
            return (
                "Not scored: none of the requested factors could be read from "
                "this submission. Included for manual review."
            )
        if self.unscored:
            return (
                f"Scored on {len(self.scored_on)} of {total} requested factors; "
                f"not readable from this bid: {', '.join(self.unscored)}."
            )
        return f"Scored on all {total} requested factors."


def _active_weights(weights: dict[str, float]) -> dict[str, float]:
    active = {
        key: max(0.0, float(value))
        for key, value in weights.items()
        if key in FACTOR_KEYS and value > 0
    }
    return active or {key: 1.0 for key in FACTOR_KEYS}


def score_candidates(
    candidates: list[Candidate], weights: dict[str, float]
) -> list[ShortlistEntry]:
    """Score every candidate, renormalising over the factors each one has.

    A candidate missing a factor is compared on the ones it has, not punished
    for the gap. A candidate missing all of them scores None -- unscorable is
    reported as unscorable rather than dressed up as last place.
    """
    active = _active_weights(weights)
    signals: dict[str, list[float | None]] = {
        "experience": _normalise([c.experience for c in candidates]),
        "project_scale": _normalise([c.project_scale for c in candidates]),
        "technical_approach": _normalise([c.technical_approach for c in candidates]),
        "pricing": _normalise([c.pricing for c in candidates], lower_is_better=True),
    }

    entries: list[ShortlistEntry] = []
    for index, candidate in enumerate(candidates):
        present = [key for key in active if signals[key][index] is not None]
        missing = tuple(sorted(key for key in active if signals[key][index] is None))
        if not present:
            entries.append(ShortlistEntry(candidate, None, (), missing))
            continue
        divisor = sum(active[key] for key in present)
        score = sum(active[key] * signals[key][index] for key in present) / divisor
        entries.append(
            ShortlistEntry(candidate, score, tuple(sorted(present)), missing)
        )
    return entries


def shortlist_with_basis(
    candidates: list[Candidate], target_count: int, weights: dict[str, float]
) -> list[ShortlistEntry]:
    """The qualified pool, each entry carrying why it is in it.

    Candidates tied with the last included candidate are all included, so the
    returned pool can be larger than `target_count`. That is deliberate: see
    TIES ARE NOT BROKEN in the module docstring.
    """
    if not candidates or target_count <= 0:
        return []

    entries = score_candidates(candidates, weights)
    # Unscorable candidates sort last -- but as a named state, not as score 0.
    ordered = sorted(
        entries,
        key=lambda entry: (
            entry.score is None,
            -(entry.score or 0.0),
            entry.candidate.vendor_id,
        ),
    )

    chosen = ordered[:target_count]
    cutoff = chosen[-1].score if chosen else None
    tied: list[ShortlistEntry] = []
    if cutoff is not None:
        for entry in ordered[target_count:]:
            if entry.score is not None and entry.score == cutoff:
                tied.append(entry)
            else:
                break

    if tied:
        boundary = {entry.candidate.vendor_id for entry in tied}
        boundary.update(
            entry.candidate.vendor_id for entry in chosen if entry.score == cutoff
        )
        chosen = [
            ShortlistEntry(
                entry.candidate,
                entry.score,
                entry.scored_on,
                entry.unscored,
                tied_at_cutoff=entry.candidate.vendor_id in boundary,
            )
            for entry in chosen + tied
        ]

    return sorted(chosen, key=lambda entry: entry.candidate.vendor_name.casefold())


def choose_shortlist(
    candidates: list[Candidate], target_count: int, weights: dict[str, float]
) -> list[Candidate]:
    """Return an unranked qualified pool with stable, reproducible membership."""
    return [entry.candidate for entry in shortlist_with_basis(candidates, target_count, weights)]


#: Intent vocabulary for the deterministic router.
#:
#: NOT an "agent": this is a lookup table, and calling it anything grander
#: oversells it. Determinism is the actual argument for it -- an evaluation
#: committee can be shown exactly why a question was answered from SQL facts
#: rather than from bid prose, which no LLM router can offer -- and that
#: argument only holds if the thing is described accurately.
#:
#: The vocabulary was widened against the DEV split of data/router_queries.json
#: only. The original twelve-query set scored 12/12 because every query in it
#: contained a trigger word; a fifty-query set written to include natural
#: paraphrases scored 60%, and the gap was almost entirely missing vocabulary:
#: "disqualification" and "exclusion" never reached the audit route, and
#: "propose", "plan" and "risks" never reached the qualitative one.
_AUDIT_TERMS = (
    "why", "eliminated", "rejected", "reason", "disqualif", "exclusion",
    "excluded", "audit trail", "grounds", "knocked out", "went wrong",
    "justify", "did not qualify", "fail",
)
_QUALITATIVE_TERMS = (
    "approach", "methodology", "scalability", "quality", "narrative",
    "propose", "proposal", "plan", "describe", "summaris", "summariz",
    "risks", "staffing", "safety", "phase", "explains", "explain how",
    "reads as", "thought through", "credible", "assurance",
)
_STRUCTURED_TERMS = (
    "turnover", "price", "quoted", "experience", "project value",
    "shortlisted", "pending", "status", "how many", "count", "list",
    "lowest", "highest", "average", "blacklisted", "threshold", "name the",
)
_COMPARATIVE_TERMS = (
    "compare", "comparison", "stack up", "rank", "contrast", "versus",
    " vs ", "side by side", "next to each other", "differences",
    "better value", "against vendor",
)


def _matches(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def classify_query(question: str) -> str:
    """Route a pool question to the evidence that can answer it.

    Order is load-bearing. An audit question ("why was Vendor A eliminated?")
    must reach the recorded elimination reason even though it also names
    vendors, because answering it from live facts would reconstruct a decision
    instead of reporting the one actually taken -- and the recorded reason is
    the only defensible answer on challenge.
    """
    text = question.casefold()
    audit = _matches(text, _AUDIT_TERMS)
    qualitative = _matches(text, _QUALITATIVE_TERMS)
    structured = _matches(text, _STRUCTURED_TERMS)
    comparative = _matches(text, _COMPARATIVE_TERMS)

    if audit:
        return "audit"
    # Facts AND narrative asked together: neither source alone answers it.
    if qualitative and (structured or comparative):
        return "hybrid"
    if comparative:
        return "comparative"
    if qualitative:
        return "qualitative"
    return "structured"


def structured_answer(question: str, candidates: list[Candidate], statuses: dict[str, str], reasons: dict[str, str | None]) -> str:
    route = classify_query(question)
    if route == "audit":
        named = [c for c in candidates if c.vendor_name.casefold() in question.casefold() or c.vendor_id.casefold() in question.casefold()]
        rows = named or [c for c in candidates if statuses[c.vendor_id] == "eliminated"]
        if not rows:
            return "No eliminated vendor matched this question."
        statements = []
        for candidate in rows:
            reason = reasons.get(candidate.vendor_id) or "No elimination reason recorded"
            statements.append(f"{candidate.vendor_name}: {reason.rstrip('.') }.")
        return " ".join(statements)
    parts = []
    for c in candidates:
        if "shortlisted" in question.casefold() and statuses[c.vendor_id] != "shortlisted":
            continue
        facts = [f"status {statuses[c.vendor_id]}"]
        # "not stated" rather than "0 years": the honest rendering of a field
        # the extractor could not read, and the same distinction the vendor-side
        # report draws between unreadable and failing.
        facts.append(
            "experience not stated"
            if c.experience is None
            else f"experience {c.experience:g} years"
        )
        if c.project_scale is not None:
            facts.append(f"largest recorded project ₹{c.project_scale:,.0f}")
        if c.pricing is not None:
            facts.append(f"quoted price ₹{c.pricing:,.0f}")
        parts.append(f"{c.vendor_name}: " + ", ".join(facts))
    return "; ".join(parts) if parts else "No vendors matched the requested status."
