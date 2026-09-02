"""LangGraph extraction pipeline (Phase 1, Section 7 "Extraction Agent(s)").

Design: one specialist extractor per field group, fanned out in parallel from a
single parsed document, then merged into one Section 6 instance.

Why not one prompt returning the whole schema:
  * Accuracy. A focused prompt ("find every eligibility criterion") outperforms
    one asking for eight unrelated things at once, and Section 10 grades
    per-field extraction accuracy.
  * Failure isolation. If evaluation-criteria extraction fails, the eligibility
    criteria still land. One monolithic call fails all-or-nothing.
  * Measurability. Per-node timing and error rates give Section 10 something to
    report per field group rather than a single aggregate.

The trade is more LLM calls per document, which the free tier absorbs at this
project's volume (Section 8.1).
"""

from __future__ import annotations

import logging
import operator
import time
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.extraction import llm_schemas as raw
from app.extraction import prompts
from app.extraction.convert import to_notification, to_submission
from app.extraction.selection import select_pages
from app.ingest.models import ParsedDocument
from app.llm import LLMError, LLMProvider, get_llm
from app.schemas.notification import TenderNotification
from app.schemas.submission import VendorSubmission

logger = logging.getLogger(__name__)


def _notify(state: "ExtractionState", node: str, event: str = "complete") -> None:
    """Report extractor progress to the caller, if it asked to be told.

    Both starts and completions are reported. Completions alone are not enough:
    under free-tier pacing the first extractor can take two minutes, and a
    progress bar sitting at 0% for that long reads as a hung request.

    Progress reporting must never break extraction, so a failing callback is
    swallowed -- a broken progress bar is not a reason to lose a document.
    """
    callback = state.get("on_node_complete")
    if callback is None:
        return
    try:
        callback(node, event)
    except Exception:                     # pragma: no cover - defensive
        logger.debug("progress callback failed for %s", node, exc_info=True)


class ExtractionState(TypedDict, total=False):
    """Each extractor writes its own key, so parallel branches never collide.
    `errors` and `timings` are the exceptions and use additive reducers."""

    document: ParsedDocument
    text: str
    llm: Any

    header: raw.RawHeader | None
    eligibility: list[raw.RawEligibilityCriterion]
    documents: list[raw.RawMandatoryDocument]
    evaluation: list[raw.RawEvaluationCriterion]
    technical: list[raw.RawTechnicalRequirement]
    format_rules: list[raw.RawSubmissionFormatRule]

    vendor_header: raw.RawVendorHeader | None
    turnover: list[raw.RawTurnover]
    certifications: list[raw.RawCertification]
    past_projects: list[raw.RawPastProject]
    submitted_documents: list[raw.RawSubmittedDocument]

    corrigendum_header: raw.RawCorrigendumHeader | None
    corrigendum_changes: list[raw.RawCorrigendumChange]

    on_node_complete: Any
    errors: Annotated[list[str], operator.add]
    timings: Annotated[list[tuple[str, float]], operator.add]


def notification_node_names() -> list[str]:
    return list(_NOTIFICATION_NODES)


def vendor_node_names() -> list[str]:
    return list(_VENDOR_NODES)


def _run(state: ExtractionState, node: str, prompt_template: str, schema):
    """Shared node body: select pages, prompt the model, validate, record timing.

    A failing extractor degrades to an empty result plus a recorded error rather
    than killing the run -- partial extraction that names its gaps is more useful
    to a reviewer than no extraction at all.
    """
    llm: LLMProvider = state["llm"]
    started = time.perf_counter()

    # Each extractor reads only the pages likely to hold its field group. On a
    # 382-page tender, sending the whole document either truncates silently or
    # buries three relevant clauses in 380 pages of contract boilerplate.
    # The budget comes from the PROVIDER, not from a constant. A selection sized
    # for a hosted context silently overflows a local one -- the request
    # succeeds and the model answers from whatever survived the truncation,
    # which looks exactly like a model that missed the clause.
    budget = getattr(llm, "input_char_budget", None)
    text, pages = select_pages(
        state["document"], node, **({"char_budget": budget} if budget else {})
    )
    logger.debug("%s: reading pages %s", node, pages)
    _notify(state, node, "start")

    try:
        # The gate matches the fan-out to what the backend can actually absorb.
        # Against a local model this serializes the extractors; against a hosted
        # API it is effectively a no-op.
        with llm:
            result = llm.generate_structured(
                prompt_template.format(text=text),
                schema,
                system=prompts.SYSTEM_PROMPT,
            )
        elapsed = time.perf_counter() - started
        logger.info("%s: ok in %.2fs (%d pages)", node, elapsed, len(pages))
        _notify(state, node)
        return result, [], [(node, elapsed)]
    except (LLMError, Exception) as exc:  # noqa: BLE001 - deliberately broad
        elapsed = time.perf_counter() - started
        logger.warning("%s: failed after %.2fs: %s", node, elapsed, exc)
        _notify(state, node)   # a failed group still advances progress
        return None, [f"{node}: {exc}"], [(node, elapsed)]


def _list_node(state, node, prompt_template, schema, key):
    result, errors, timings = _run(state, node, prompt_template, schema)
    return {key: list(result.items) if result else [], "errors": errors, "timings": timings}


# --------------------------------------------------------------------------- #
# Notification extractors
# --------------------------------------------------------------------------- #
def extract_header(state: ExtractionState) -> dict:
    result, errors, timings = _run(state, "header", prompts.HEADER_PROMPT, raw.RawHeader)
    return {"header": result, "errors": errors, "timings": timings}


def extract_eligibility(state: ExtractionState) -> dict:
    return _list_node(
        state, "eligibility", prompts.ELIGIBILITY_PROMPT, raw.EligibilityList, "eligibility"
    )


def extract_documents(state: ExtractionState) -> dict:
    return _list_node(
        state, "documents", prompts.MANDATORY_DOCUMENTS_PROMPT, raw.DocumentList, "documents"
    )


def extract_evaluation(state: ExtractionState) -> dict:
    return _list_node(
        state, "evaluation", prompts.EVALUATION_PROMPT, raw.EvaluationList, "evaluation"
    )


def extract_technical(state: ExtractionState) -> dict:
    return _list_node(
        state, "technical", prompts.TECHNICAL_PROMPT, raw.TechnicalList, "technical"
    )


def extract_format_rules(state: ExtractionState) -> dict:
    return _list_node(
        state, "format_rules", prompts.FORMAT_RULES_PROMPT, raw.FormatRuleList, "format_rules"
    )


# --------------------------------------------------------------------------- #
# Vendor extractors
# --------------------------------------------------------------------------- #
def extract_vendor_header(state: ExtractionState) -> dict:
    result, errors, timings = _run(
        state, "vendor_header", prompts.VENDOR_HEADER_PROMPT, raw.RawVendorHeader
    )
    return {"vendor_header": result, "errors": errors, "timings": timings}


def extract_turnover(state: ExtractionState) -> dict:
    return _list_node(state, "turnover", prompts.TURNOVER_PROMPT, raw.TurnoverList, "turnover")


def extract_certifications(state: ExtractionState) -> dict:
    return _list_node(
        state,
        "certifications",
        prompts.CERTIFICATIONS_PROMPT,
        raw.CertificationList,
        "certifications",
    )


def extract_past_projects(state: ExtractionState) -> dict:
    return _list_node(
        state,
        "past_projects",
        prompts.PAST_PROJECTS_PROMPT,
        raw.PastProjectList,
        "past_projects",
    )


def extract_submitted_documents(state: ExtractionState) -> dict:
    return _list_node(
        state,
        "submitted_documents",
        prompts.SUBMITTED_DOCUMENTS_PROMPT,
        raw.SubmittedDocumentList,
        "submitted_documents",
    )


# --------------------------------------------------------------------------- #
# Graphs
# --------------------------------------------------------------------------- #
_NOTIFICATION_NODES = {
    "header": extract_header,
    "eligibility": extract_eligibility,
    "documents": extract_documents,
    "evaluation": extract_evaluation,
    "technical": extract_technical,
    "format_rules": extract_format_rules,
}

_VENDOR_NODES = {
    "vendor_header": extract_vendor_header,
    "turnover": extract_turnover,
    "certifications": extract_certifications,
    "past_projects": extract_past_projects,
    "submitted_documents": extract_submitted_documents,
}


def _fan_out_graph(nodes: dict):
    """START -> all extractors in parallel -> END."""
    graph = StateGraph(ExtractionState)
    for name, fn in nodes.items():
        graph.add_node(name, fn)
        graph.add_edge(START, name)
        graph.add_edge(name, END)
    return graph.compile()


_notification_graph = None
_vendor_graph = None


def notification_graph():
    global _notification_graph
    if _notification_graph is None:
        _notification_graph = _fan_out_graph(_NOTIFICATION_NODES)
    return _notification_graph


def vendor_graph():
    global _vendor_graph
    if _vendor_graph is None:
        _vendor_graph = _fan_out_graph(_VENDOR_NODES)
    return _vendor_graph


class ExtractionResult(TypedDict):
    errors: list[str]
    timings: list[tuple[str, float]]
    parse_warnings: list[str]


def extract_notification(
    document: ParsedDocument,
    *,
    llm: LLMProvider | None = None,
    on_node_complete=None,
) -> tuple[TenderNotification, ExtractionResult]:
    """Run the notification extraction graph over a parsed document."""
    state = {
        "document": document,
        "text": document.full_text(),
        "llm": llm or get_llm(),
        "on_node_complete": on_node_complete,
        "errors": [],
        "timings": [],
    }
    final = notification_graph().invoke(state)

    notification = to_notification(
        final.get("header") or raw.RawHeader(),
        final.get("eligibility") or [],
        final.get("documents") or [],
        final.get("evaluation") or [],
        final.get("technical") or [],
        final.get("format_rules") or [],
        fallback_tender_id=document.file_name,
        fallback_title=document.file_name,
    )
    return notification, {
        "errors": final.get("errors", []),
        "timings": final.get("timings", []),
        "parse_warnings": document.parse_warnings,
    }


def extract_submission(
    document: ParsedDocument,
    *,
    vendor_id: str,
    tender_id: str | None = None,
    llm: LLMProvider | None = None,
    on_node_complete=None,
) -> tuple[VendorSubmission, ExtractionResult]:
    """Run the vendor-bid extraction graph over a parsed document."""
    state = {
        "document": document,
        "text": document.full_text(),
        "llm": llm or get_llm(),
        "on_node_complete": on_node_complete,
        "errors": [],
        "timings": [],
    }
    final = vendor_graph().invoke(state)

    submission = to_submission(
        final.get("vendor_header") or raw.RawVendorHeader(),
        final.get("turnover") or [],
        final.get("certifications") or [],
        final.get("past_projects") or [],
        final.get("submitted_documents") or [],
        vendor_id=vendor_id,
        fallback_vendor_name=document.file_name,
        tender_id=tender_id,
    )
    return submission, {
        "errors": final.get("errors", []),
        "timings": final.get("timings", []),
        "parse_warnings": document.parse_warnings,
    }


# --------------------------------------------------------------------------- #
# Corrigendum (Section 5.6) -- two nodes, not six
# --------------------------------------------------------------------------- #
# A corrigendum is a short document (typically one to three pages) that amends
# an already-extracted notification. It needs the amendment's own identity and
# the list of changes, and nothing else: re-running the full six-way notification
# fan-out over it would spend six requests to re-read fields the corrigendum does
# not restate, against a free tier of twenty per model per day.
def extract_corrigendum_header(state: ExtractionState) -> dict:
    result, errors, timings = _run(
        state,
        "corrigendum_header",
        prompts.CORRIGENDUM_HEADER_PROMPT,
        raw.RawCorrigendumHeader,
    )
    return {"corrigendum_header": result, "errors": errors, "timings": timings}


def extract_corrigendum_changes(state: ExtractionState) -> dict:
    return _list_node(
        state,
        "corrigendum_changes",
        prompts.CORRIGENDUM_CHANGES_PROMPT,
        raw.CorrigendumChangeList,
        "corrigendum_changes",
    )


_CORRIGENDUM_NODES = {
    "corrigendum_header": extract_corrigendum_header,
    "corrigendum_changes": extract_corrigendum_changes,
}

_corrigendum_graph = None


def corrigendum_node_names() -> list[str]:
    return list(_CORRIGENDUM_NODES)


def corrigendum_graph():
    global _corrigendum_graph
    if _corrigendum_graph is None:
        _corrigendum_graph = _fan_out_graph(_CORRIGENDUM_NODES)
    return _corrigendum_graph


def extract_corrigendum(
    document: ParsedDocument,
    parent: TenderNotification,
    *,
    llm: LLMProvider | None = None,
    on_node_complete=None,
):
    """Extract an amendment and diff it against the notification it amends.

    The diff is computed here, in code, from the parent we already hold -- the
    model is never asked what changed. It reads what the corrigendum printed;
    comparing that against a stored value is deterministic, and a wrong answer
    from a comparison is a bug rather than a sampling artefact.
    """
    from app.corrigendum.diff import diff_corrigendum

    state = {
        "document": document,
        "text": document.full_text(),
        "llm": llm or get_llm(),
        "on_node_complete": on_node_complete,
        "errors": [],
        "timings": [],
    }
    final = corrigendum_graph().invoke(state)

    corrigendum = diff_corrigendum(
        parent,
        final.get("corrigendum_header") or raw.RawCorrigendumHeader(),
        final.get("corrigendum_changes") or [],
        source_file=document.file_name,
    )
    return corrigendum, {
        "errors": final.get("errors", []),
        "timings": final.get("timings", []),
        "parse_warnings": document.parse_warnings,
    }
