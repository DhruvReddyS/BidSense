"""Citation faithfulness (Scope Section 10).

Section 10 asks: "does every generated answer's citation actually support the
claim?" This measures it on the labelled query set, deterministically.

FOUR THINGS ARE CHECKED, and they are different questions:

  grounded        A factual answer carries at least one citation and invented
                  none. An uncited correct answer is still a failure here: the
                  vendor has no way to check it.
  invented        The model cited a source number it was never given. Already
                  stripped at generation time; counted here because a stripped
                  invention is still evidence about the model.
  page truthful   The page a citation names really contains the text the
                  citation carries. This is the claim the UI acts on when it
                  renders the source page with the passage marked, so a
                  citation naming the wrong page breaks provenance even when
                  the answer is right.
  claim supported For queries whose answer we know, the labelled fact appears
                  in at least one CITED chunk -- not merely somewhere in the
                  retrieved set. An answer resting on citation [2] while the
                  fact lives in uncited chunk [5] is unsupported.

WHY NO LLM JUDGE. Section 10 offers "manual spot-check + optionally an
LLM-as-judge pass". A judge would be the only component here grading its own
family's output, it is unreproducible run to run, and it costs quota on every
evaluation. The labelled phrases already define what a correct answer contains,
so substring verification against the SOURCE PDF answers the question with no
judgement at all. The cost is that only labelled queries get the
claim-supported check; that number is reported with its own denominator.

GROUNDING IS NOT DETERMINISTIC, SO NEITHER IS THIS NUMBER. The grounded figure
depends on which provider tier served the answer. In one run q06 and q07 came
back with zero citations and scored ungrounded; re-run minutes later against a
different tier (Gemini had been returning 503s) both cited four and three
sources. Treat the grounded percentage as a sample from a distribution, not a
property of the system, and say which it is when quoting it. The page-truthful
and invented-citation figures are stable because they check structure rather
than model behaviour.

CLAIM-SUPPORTED IS A LOWER BOUND. It matches the labelled phrase literally, so
a correct answer phrased differently scores as unsupported: q07's answer
("average annual financial turnover ... at least 30% of the estimated cost") is
right and well-cited, but the label says "Annual Turnover" and that is not a
substring of "annual financial turnover". Labels were NOT broadened to fix
this -- doing so after seeing the result is how an evaluation starts flattering
its subject.

Run:  python -m scripts.evaluate_citations [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.db.models import TenderNotificationRow
from app.db.session import session_scope
from app.ingest.loader import parse_document
from app.rag.answer import answer_question
from app.rag.retrieve import retrieve
from app.schemas.common import DocumentKind

QUERY_PATH = Path(__file__).parents[2] / "data" / "rag_queries.json"
NOTIF_DIR = Path(__file__).parents[2] / "data" / "notifications"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").casefold()


@dataclass
class PageIndex:
    """Page text of one source PDF, for verifying what a citation claims."""

    pages: dict[int, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "PageIndex":
        """Index each page through the ingest pipeline's own parser.

        Comparing a chunk against pdfplumber's `extract_text()` compares a
        table rendered as "Label | Value" against the same table rendered as
        running text, so NO table-derived citation could ever verify. That
        scored citation truthfulness at 50% and the fault was entirely in this
        method -- the measurement has to use the renderer the chunk came from.
        """
        document = parse_document(path, DocumentKind.NOTIFICATION)
        return cls({page.page_number: _norm(page.combined_text()) for page in document.pages})

    def contains(self, page: int | None, needle: str) -> bool | None:
        """None when the page is unknown -- unverifiable, not false."""
        if page is None or page not in self.pages:
            return None
        return _norm(needle) in self.pages[page]


@dataclass
class Result:
    qid: str
    question: str
    answered: bool
    grounded: bool
    n_citations: int
    invented: list[int]
    page_checks: list[bool]          # per citation, where verifiable
    page_unverifiable: int
    claim_supported: bool | None     # None when the answer declined


def _tender_map() -> dict[str, str]:
    with session_scope() as session:
        return {
            Path(row.source_file or "").stem: row.tender_id
            for row in session.scalars(select(TenderNotificationRow)).all()
            if Path(row.source_file or "").stem.startswith("NOTIF_")
        }


def evaluate(limit: int | None) -> tuple[list[Result], list[str]]:
    spec = json.loads(QUERY_PATH.read_text())
    queries = spec["queries"][:limit] if limit else spec["queries"]
    tenders = _tender_map()
    page_cache: dict[str, PageIndex] = {}
    results: list[Result] = []
    skipped: list[str] = []

    for query in queries:
        stem = query["tender"]
        tender_id = tenders.get(stem)
        if tender_id is None:
            skipped.append(f"{query['id']} ({stem} not ingested)")
            continue

        chunks = retrieve(
            query["question"], tender_id=tender_id,
            doc_kind=DocumentKind.NOTIFICATION, top_k=6,
        )
        answer = answer_question(query["question"], chunks)

        if stem not in page_cache:
            page_cache[stem] = PageIndex.load(NOTIF_DIR / f"{stem}.pdf")
        pages = page_cache[stem]

        # Does each citation's page really carry the text it cites? A long chunk
        # can legitimately span a page break, so a distinctive opening fragment
        # is used rather than the whole body.
        checks: list[bool] = []
        unverifiable = 0
        for citation in answer.citations:
            probe = _norm(citation.text)
            probe = probe[: min(120, len(probe))]
            # Strip the synthesised table marker, which is ours, not the page's.
            probe = re.sub(r"^\[table on page \d+\]\s*", "", probe)
            verdict = pages.contains(citation.source_page, probe[:80])
            if verdict is None:
                unverifiable += 1
            else:
                checks.append(verdict)

        supported: bool | None = None
        if answer.answered:
            phrases = [_norm(p) for p in query["answer_contains"]]
            cited_text = " ".join(_norm(c.text) for c in answer.citations)
            supported = any(p in cited_text for p in phrases)

        results.append(Result(
            qid=query["id"], question=query["question"],
            answered=answer.answered, grounded=answer.is_grounded,
            n_citations=len(answer.citations), invented=list(answer.invented_citations),
            page_checks=checks, page_unverifiable=unverifiable,
            claim_supported=supported,
        ))
    return results, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="evaluate only the first N queries")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    results, skipped = evaluate(args.limit)
    if not results:
        print("Nothing evaluated. Is the corpus ingested?")
        return 1

    print(f"{'id':5} {'ans':4} {'grnd':5} {'cites':6} {'pages ok':9} {'claim':6}  question")
    print("-" * 100)
    for r in results:
        page_str = (
            f"{sum(r.page_checks)}/{len(r.page_checks)}" if r.page_checks else "n/a"
        )
        claim = {True: "yes", False: "NO", None: "-"}[r.claim_supported]
        print(f"{r.qid:5} {str(r.answered):4} {str(r.grounded):5} {r.n_citations:6} "
              f"{page_str:9} {claim:6}  {r.question[:46]}")

    answered = [r for r in results if r.answered]
    judged = [r for r in results if r.claim_supported is not None]
    all_page_checks = [c for r in results for c in r.page_checks]
    invented_total = sum(len(r.invented) for r in results)

    print("\n" + "=" * 100)
    print(f"Queries evaluated        : {len(results)}"
          + (f"   (skipped {len(skipped)})" if skipped else ""))
    print(f"Answered (not declined)  : {len(answered)}/{len(results)}")
    if answered:
        grounded = sum(1 for r in answered if r.grounded)
        print(f"Grounded answers         : {grounded}/{len(answered)} "
              f"({grounded / len(answered) * 100:.1f}%)  <- has a citation, invented none")
    print(f"Invented citations       : {invented_total}"
          "   <- stripped before display; non-zero is still a finding")
    if all_page_checks:
        ok = sum(all_page_checks)
        print(f"Citation page truthful   : {ok}/{len(all_page_checks)} "
              f"({ok / len(all_page_checks) * 100:.1f}%)  <- cited page really holds the text")
    unver = sum(r.page_unverifiable for r in results)
    if unver:
        print(f"  (unverifiable pages    : {unver} -- citation carried no page)")
    if judged:
        supported = sum(1 for r in judged if r.claim_supported)
        print(f"Labelled claim supported : {supported}/{len(judged)} "
              f"({supported / len(judged) * 100:.1f}%)  <- fact is in a CITED chunk")

    bad = [r for r in results if r.answered and not r.grounded]
    if bad:
        print("\nUngrounded answers -- a factual claim the vendor cannot check:")
        for r in bad:
            print(f"  {r.qid}: {r.question}  (citations={r.n_citations}, invented={r.invented})")

    unsupported = [r for r in judged if not r.claim_supported]
    if unsupported:
        print("\nAnswered, but the labelled fact was NOT in a cited chunk:")
        for r in unsupported:
            print(f"  {r.qid}: {r.question}")
        print("  These mirror the retrieval misses: the answer could not cite "
              "evidence\n  that was never retrieved. Reported here so the two "
              "metrics are not\n  mistaken for independent confirmations.")

    if args.json:
        args.json.write_text(json.dumps(
            {"results": [r.__dict__ for r in results], "skipped": skipped},
            indent=2, default=str))
        print(f"\nWritten to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
