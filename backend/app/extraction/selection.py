"""Page selection for long documents (Phase 1, exposed by real tender data).

Real tenders run to hundreds of pages. The HGCL solar EPC notification in this
project's data set is 382 pages / ~200k tokens -- an order of magnitude past a
local model's context and well past the point where a hosted model reads
carefully. Sending `full_text()` either truncates silently or buries three
relevant clauses in 380 pages of general conditions of contract.

So each extractor gets only the pages likely to contain its field group. This is
retrieval applied to extraction, and it is a genuine IE sub-problem rather than
plumbing: choosing the wrong pages is indistinguishable, downstream, from a
model that failed to find the clause.

Two-stage, cheap first:

  1. Lexical cue scoring. Domain vocabulary is highly diagnostic here --
     "average annual turnover" appears on eligibility pages and essentially
     nowhere else. Fast, no model, no GPU.
  2. Embedding re-ranking, only when the lexical pass is thin. Catches pages
     that paraphrase ("financial capacity of the bidder") without the cue terms.

Short documents skip both: under the budget, every page goes in.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.ingest.models import ParsedDocument

logger = logging.getLogger(__name__)

# Roughly 4 chars per token for English legal prose. 60k chars ~ 15k tokens,
# which leaves comfortable room inside a 40k-token local context alongside the
# system prompt, schema and output.
DEFAULT_CHAR_BUDGET = 60_000

# Pages scoring at least this fraction of the best page are kept. Relative, not
# absolute, because cue density varies hugely between a 68-page and a 382-page
# document.
RELATIVE_KEEP = 0.25


@dataclass(frozen=True)
class FieldGroup:
    """Cue vocabulary and a natural-language description of one field group."""

    name: str
    cues: tuple[str, ...]
    query: str          # used for embedding re-ranking
    always_include_first: int = 0   # front matter that always carries the header


FIELD_GROUPS: dict[str, FieldGroup] = {
    "header": FieldGroup(
        name="header",
        cues=(
            "tender no", "tender reference", "nit no", "e-tender", "etender",
            "name of work", "name of the work", "notice inviting", "issued by",
            "last date", "due date", "bid submission", "pre-bid", "pre bid",
            "earnest money", "emd", "estimated cost", "contract value",
            "bid validity", "tender fee",
        ),
        query="tender reference number, issuing authority, submission deadline, EMD amount, estimated contract value",
        # Identifiers and dates live in the front matter of every Indian tender.
        always_include_first=6,
    ),
    "eligibility": FieldGroup(
        name="eligibility",
        cues=(
            "eligibility", "eligible", "qualification", "qualifying",
            "average annual", "turnover", "annual financial turnover",
            "similar work", "similar nature", "experience of having",
            "years of experience", "net worth", "solvency", "blacklist",
            "debarred", "banned", "registered under", "minimum requirement",
            "pre-qualification", "prequalification",
        ),
        query="bidder eligibility criteria: minimum annual turnover, years of experience, similar completed works, blacklisting",
    ),
    "documents": FieldGroup(
        name="documents",
        cues=(
            "documents to be", "list of documents", "documents required",
            "scanned copy", "shall be enclosed", "shall be uploaded",
            "attach", "annexure", "certificate", "gst", "pan", "affidavit",
            "declaration", "checklist", "enclosure", "self attested",
        ),
        query="list of mandatory documents to be submitted with the bid, certificates, annexures, declarations",
    ),
    "evaluation": FieldGroup(
        name="evaluation",
        cues=(
            "evaluation", "evaluated", "marks", "weightage", "weightage of",
            "scoring", "score", "qcbs", "least cost", "l1", "technical score",
            "financial score", "criteria for evaluation", "award of contract",
            "lowest bidder", "comparative statement",
        ),
        query="bid evaluation criteria, technical and financial weightage, scoring methodology, award of contract",
    ),
    "technical": FieldGroup(
        name="technical",
        cues=(
            "technical specification", "specification", "scope of work",
            "shall conform", "shall comply", "is code", "bis", "iec", "ieee",
            "warranty", "guarantee period", "make and model", "capacity",
            "performance requirement", "quality",
        ),
        query="technical specifications of the goods or works, standards compliance, warranty, scope of work",
    ),
    "format_rules": FieldGroup(
        name="format_rules",
        cues=(
            "envelope", "sealed", "signed and stamped", "page numbered",
            "serially numbered", "shall be submitted in", "format of",
            "submission of bid", "online submission", "hard copy",
            "digital signature", "dsc", "manner of submission", "typed",
        ),
        query="how the bid must be prepared and submitted: envelopes, signing, stamping, page numbering, format",
    ),
    # --- vendor bid side ---
    "vendor_header": FieldGroup(
        name="vendor_header",
        cues=(
            "we hereby", "bidder", "our company", "letter head", "authorised signatory",
            "methodology", "technical approach", "our approach", "work plan",
            "understanding of", "price", "quoted", "amount in words",
        ),
        query="bidder name, years in business, technical approach and methodology narrative, quoted price",
        always_include_first=4,
    ),
    "turnover": FieldGroup(
        name="turnover",
        cues=(
            "turnover", "financial year", "fy 20", "balance sheet",
            "profit and loss", "revenue", "audited", "chartered accountant",
            "gross receipts",
        ),
        query="annual turnover figures per financial year, audited financial statements",
    ),
    "certifications": FieldGroup(
        name="certifications",
        cues=(
            "iso", "certificate", "certification", "registration", "gst",
            "pan", "licence", "license", "valid till", "valid up to",
            "accreditation", "empanel",
        ),
        query="certifications and registrations held by the bidder with validity dates",
    ),
    "past_projects": FieldGroup(
        name="past_projects",
        cues=(
            "completed", "ongoing", "client", "project", "work order",
            "contract value", "commissioned", "executed", "similar work",
            "experience", "performance certificate",
        ),
        query="past and ongoing projects: client, value, year, description of work executed",
    ),
    "submitted_documents": FieldGroup(
        name="submitted_documents",
        # "index" and "page no" are deliberately absent. They match a bid's own
        # table of contents far more strongly than its enclosure checklist, and
        # selecting the contents page led the extractor to return the bid's
        # chapters as its enclosures -- which made every required certificate
        # look missing.
        cues=(
            "enclosed", "not enclosed", "annexure", "attached", "checklist",
            "enclosure", "submitted herewith", "as per annexure",
            "documents enclosed", "list of enclosures", "true copy",
            "self attested", "certified copy",
        ),
        query=(
            "checklist of documents enclosed with this bid, annexures attached, "
            "certificates and declarations submitted"
        ),
    ),
}

_WORD = re.compile(r"[a-z0-9]+")


def _lexical_scores(document: ParsedDocument, group: FieldGroup) -> dict[int, float]:
    """Count cue occurrences per page, normalised by page length.

    Normalising matters: a 3000-char page of general conditions that happens to
    say "certificate" twice must not outrank a 600-char page that is nothing but
    the document checklist.
    """
    scores: dict[int, float] = {}
    for page in document.pages:
        text = page.combined_text().lower()
        if not text:
            continue
        hits = sum(text.count(cue) for cue in group.cues)
        if hits:
            # sqrt damping so one page repeating a cue 40 times doesn't dominate.
            scores[page.page_number] = (hits**0.5) / max(len(text) / 1000, 1) ** 0.5
    return scores


def _embedding_scores(document: ParsedDocument, group: FieldGroup) -> dict[int, float]:
    from app.vector.embeddings import embed_passages, embed_query

    pages = [p for p in document.pages if p.combined_text().strip()]
    if not pages:
        return {}
    query_vec = embed_query(group.query)
    # Only the head of each page is embedded: it is where section headings sit,
    # and embedding 382 full pages costs far more than it adds.
    page_vecs = embed_passages([p.combined_text()[:1200] for p in pages])
    return {
        page.page_number: sum(a * b for a, b in zip(query_vec, vec))
        for page, vec in zip(pages, page_vecs)
    }


def select_pages(
    document: ParsedDocument,
    group_name: str,
    *,
    char_budget: int = DEFAULT_CHAR_BUDGET,
    use_embeddings: bool = True,
) -> tuple[str, list[int]]:
    """Return (text, page_numbers) for the pages relevant to `group_name`.

    The returned text keeps [PAGE N] markers and original page order, so
    `source_page` provenance stays correct -- the model still reports the page
    it actually read the value from, not an index into a reshuffled excerpt.
    """
    group = FIELD_GROUPS.get(group_name)
    if group is None:
        return document.full_text(), [p.page_number for p in document.pages]

    # Short document: no selection needed, and none is safer.
    if document.total_chars <= char_budget:
        return document.full_text(), [p.page_number for p in document.pages]

    scores = _lexical_scores(document, group)

    # A thin lexical result on a long document means the vocabulary missed --
    # fall back to embeddings rather than extracting from three pages.
    thin = len(scores) < 3
    if thin and use_embeddings:
        try:
            scores = _embedding_scores(document, group)
            logger.info("%s: lexical pass thin, used embedding ranking", group_name)
        except Exception as exc:
            logger.warning("%s: embedding ranking unavailable (%s)", group_name, exc)

    if not scores:
        # Nothing matched at all. Send the head of the document rather than
        # nothing -- an empty extraction is the worst possible outcome.
        selected = [p.page_number for p in document.pages][: max(group.always_include_first, 10)]
    else:
        best = max(scores.values())
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        selected = [page for page, score in ranked if score >= best * RELATIVE_KEEP]

    # Front matter carries the identifiers regardless of cue density.
    selected = set(selected) | {
        p.page_number for p in document.pages[: group.always_include_first]
    }

    # Fill in page order, stopping at the budget. Order matters: a clause
    # referring to "the above" needs its neighbours to still precede it.
    chosen: list[int] = []
    used = 0
    for page in document.pages:
        if page.page_number not in selected:
            continue
        body = page.combined_text()
        if used + len(body) > char_budget and chosen:
            break
        chosen.append(page.page_number)
        used += len(body)

    text = "\n\n".join(
        f"[PAGE {n}]\n{document.page(n).combined_text()}" for n in chosen
    )
    logger.info(
        "%s: selected %d/%d pages (%d chars of %d)",
        group_name, len(chosen), document.page_count, used, document.total_chars,
    )
    return text, chosen
