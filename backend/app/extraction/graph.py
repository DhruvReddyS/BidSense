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
from app.ingest.models import ParsedDocument
from app.llm import LLMError, LLMProvider, get_llm
from app.schemas.notification import TenderNotification
from app.schemas.submission import VendorSubmission

logger = logging.getLogger(__name__)


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

    errors: Annotated[list[str], operator.add]
    timings: Annotated[list[tuple[str, float]], operator.add]


def _run(state: ExtractionState, node: str, prompt_template: str, schema):
    """Shared node body: prompt the model, validate, record timing and errors.

    A failing extractor degrades to an empty result plus a recorded error rather
    than killing the run -- partial extraction that names its gaps is more useful
    to a reviewer than no extraction at all.
    """
    llm: LLMProvider = state["llm"]
    started = time.perf_counter()
    try:
        result = llm.generate_structured(
            prompt_template.format(text=state["text"]),
            schema,
            system=prompts.SYSTEM_PROMPT,
        )
        elapsed = time.perf_counter() - started
        logger.info("%s: ok in %.2fs", node, elapsed)
        return result, [], [(node, elapsed)]
    except (LLMError, Exception) as exc:  # noqa: BLE001 - deliberately broad
        elapsed = time.perf_counter() - started
        logger.warning("%s: failed after %.2fs: %s", node, elapsed, exc)
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
    document: ParsedDocument, *, llm: LLMProvider | None = None
) -> tuple[TenderNotification, ExtractionResult]:
    """Run the notification extraction graph over a parsed document."""
    state = {
        "document": document,
        "text": document.full_text(),
        "llm": llm or get_llm(),
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
) -> tuple[VendorSubmission, ExtractionResult]:
    """Run the vendor-bid extraction graph over a parsed document."""
    state = {
        "document": document,
        "text": document.full_text(),
        "llm": llm or get_llm(),
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
