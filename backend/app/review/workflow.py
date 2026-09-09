"""Deterministic shortlist signals and cross-vendor query routing.

Scores are used only to reduce a large pool to the reviewer-requested size. They
are never exposed as a legal rank and every selected candidate carries the raw
facts that caused inclusion.
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
    experience: float
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
        experience=float(row.years_in_business or 0),
        project_scale=max(values) if values else None,
        technical_approach=1.0 if row.has_technical_approach else 0.0,
        pricing=row.quoted_price_inr,
    )


def _normalise(values: list[Decimal | float | None], *, lower_is_better: bool = False) -> list[float]:
    known = [float(value) for value in values if value is not None]
    if not known:
        return [0.0] * len(values)
    lo, hi = min(known), max(known)
    if lo == hi:
        return [1.0 if value is not None else 0.0 for value in values]
    result = [0.0 if value is None else (float(value) - lo) / (hi - lo) for value in values]
    return [1.0 - value if original is not None else 0.0 for value, original in zip(result, values)] if lower_is_better else result


def choose_shortlist(candidates: list[Candidate], target_count: int, weights: dict[str, float]) -> list[Candidate]:
    """Return an unranked qualified pool with stable, reproducible membership."""
    if not candidates or target_count <= 0:
        return []
    active = {key: max(0.0, float(value)) for key, value in weights.items() if key in FACTOR_KEYS and value > 0}
    if not active:
        active = {"experience": 1.0, "project_scale": 1.0, "technical_approach": 1.0, "pricing": 1.0}
    signals = {
        "experience": _normalise([c.experience for c in candidates]),
        "project_scale": _normalise([c.project_scale for c in candidates]),
        "technical_approach": _normalise([c.technical_approach for c in candidates]),
        "pricing": _normalise([c.pricing for c in candidates], lower_is_better=True),
    }
    scored = []
    for index, candidate in enumerate(candidates):
        score = sum(active[key] * signals[key][index] for key in active) / sum(active.values())
        scored.append((score, candidate.vendor_id, candidate))
    chosen = [item[2] for item in sorted(scored, key=lambda item: (-item[0], item[1]))[:target_count]]
    return sorted(chosen, key=lambda item: item.vendor_name.casefold())


def classify_query(question: str) -> str:
    text = question.casefold()
    audit = any(word in text for word in ("why", "eliminated", "rejected", "reason"))
    qualitative = any(word in text for word in ("approach", "methodology", "scalability", "quality", "narrative"))
    structured = any(word in text for word in ("turnover", "price", "experience", "project value", "shortlisted", "pending", "compare"))
    if audit:
        return "audit"
    if qualitative and structured:
        return "hybrid"
    if qualitative:
        return "qualitative"
    if "compare" in text:
        return "comparative"
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
        facts = [f"status {statuses[c.vendor_id]}", f"experience {c.experience:g} years"]
        if c.project_scale is not None:
            facts.append(f"largest recorded project ₹{c.project_scale:,.0f}")
        if c.pricing is not None:
            facts.append(f"quoted price ₹{c.pricing:,.0f}")
        parts.append(f"{c.vendor_name}: " + ", ".join(facts))
    return "; ".join(parts) if parts else "No vendors matched the requested status."
