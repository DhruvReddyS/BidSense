"""Measure extraction accuracy per model and per prompt, against document truth.

    python -m scripts.benchmark_extraction --models qwen3:4b,qwen3:14b
    python -m scripts.benchmark_extraction --models qwen3:4b --prompt both
    python -m scripts.benchmark_extraction --provider groq --models llama-3.3-70b-versatile

Why this exists rather than a one-off script: "the model cannot do it" and "the
prompt does not ask properly" look identical from outside, and so do "the model
missed it" and "page selection never sent it". Separating them needs the same
document, the same selected pages and the same scoring run against every
candidate, which is what this does.

GROUND TRUTH IS READ FROM THE DOCUMENT, not from another model's output. Each
expected value below was located by searching the PDF text and confirming the
page it appears on -- see `--verify-truth`, which re-checks that every expected
value is present in the pages actually sent to the model. A benchmark scored
against Gemini's answers would measure agreement with Gemini, not accuracy.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.extraction import llm_schemas as raw  # noqa: E402
from app.extraction import prompts  # noqa: E402
from app.extraction.selection import select_pages  # noqa: E402
from app.ingest import parse_document  # noqa: E402
from app.normalize.money import try_normalize_amount  # noqa: E402
from app.schemas.common import DocumentKind  # noqa: E402

DATA = Path(__file__).resolve().parents[2] / "data"


@dataclass
class Expected:
    """One document's verified truth, with the page each value was found on."""

    path: Path
    label: str
    #: field -> (expected value, page it appears on in the PDF)
    header: dict[str, tuple[str | None, int]]
    min_eligibility: int
    min_documents: int


TRUTH: list[Expected] = [
    Expected(
        path=DATA / "notifications" / "NOTIF_civilworks_01.pdf",
        label="IIT (ISM) 101p",
        header={
            # Printed as "Last Date and Time for uploading of Bids 22 August 2026".
            "submission_deadline": ("2026-08-22", 5),
            # "Last Date and Time for receipt of Queries 19 August 2026".
            "pre_bid_query_deadline": ("2026-08-19", 5),
            "emd_amount_raw": ("31,500", 5),
            "contract_value_raw": ("12,56,561", 5),
            "issuing_authority": ("Indian School of Mines|Indian Institute of Technology", 1),
            "tender_id": ("CMU-12011/17/2026-CMU", 1),
        },
        min_eligibility=8,
        min_documents=8,
    ),
    Expected(
        path=DATA / "notifications" / "NOTIF_supply_01.pdf",
        label="GHMC 68p",
        header={
            "emd_amount_raw": ("2,98,720", 1),
            "issuing_authority": ("Greater Hyderabad Municipal Corporation", 1),
        },
        min_eligibility=5,
        min_documents=10,
    ),
]


@dataclass
class Result:
    model: str
    prompt: str
    document: str
    seconds: float
    fields: dict[str, bool] = field(default_factory=dict)
    values: dict[str, str | None] = field(default_factory=dict)
    eligibility: int = 0
    documents: int = 0
    error: str | None = None

    @property
    def score(self) -> str:
        got = sum(1 for v in self.fields.values() if v)
        return f"{got}/{len(self.fields)}"

    @property
    def correct(self) -> int:
        return sum(1 for v in self.fields.values() if v)


def _matches(expected: str, actual) -> bool:
    """Whether an extracted value carries the expected content.

    Deliberately forgiving about form and strict about substance: a date is
    right if it resolves to the right day however it was printed, an amount is
    right if it normalises to the right rupees, and a name is right if it
    contains the distinguishing phrase. Demanding an exact string would score
    "Rs. 31,500/-" and "Rs. 31,500" differently, which measures formatting.
    """
    if actual is None:
        return False
    text = str(actual).strip()
    if not text or text.lower() in {"none", "null", "n/a", "not stated"}:
        return False

    # Money: compare canonical rupees, not printed form.
    if re.fullmatch(r"[\d,]+", expected):
        want = try_normalize_amount(expected)
        got = try_normalize_amount(text)
        return want is not None and want == got

    # Dates: compare the resolved day.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", expected):
        from app.extraction.convert import parse_date

        got = parse_date(text)
        return got is not None and got.isoformat() == expected

    # Names and references: any alternative, case-insensitive.
    return any(part.lower() in text.lower() for part in expected.split("|"))


def _provider(name: str, model: str):
    if name == "ollama":
        settings.ollama_model = model
        from app.llm.ollama import OllamaProvider

        return OllamaProvider()
    if name == "groq":
        settings.groq_model = model
        from app.llm.groq import GroqProvider

        return GroqProvider()
    if name == "gemini":
        settings.gemini_model = model
        settings.gemini_fallback_models = ""
        from app.llm.gemini import GeminiProvider

        return GeminiProvider()
    raise SystemExit(f"unknown provider {name!r}")


def _header_prompt(variant: str) -> str:
    if variant == "fewshot":
        return prompts.HEADER_PROMPT
    if variant == "bare":
        return prompts.HEADER_PROMPT_NO_EXAMPLES
    raise SystemExit(f"unknown prompt variant {variant!r}")


def verify_truth() -> int:
    """Confirm every expected value is in the pages actually sent to the model.

    Without this the benchmark cannot tell a model that missed a value from a
    page selection that never sent it -- and would blame the model for both.
    """
    failures = 0
    for expected in TRUTH:
        if not expected.path.exists():
            print(f"  SKIP {expected.label}: {expected.path.name} not found")
            continue
        document = parse_document(expected.path, DocumentKind.NOTIFICATION)
        text, pages = select_pages(document, "header")
        print(f"\n  {expected.label}: header selects {len(pages)} pages")
        for name, (value, page) in expected.header.items():
            needle = value.split("|")[0]
            in_pages = page in pages
            # Money and dates are printed differently from their canonical form.
            probe = needle if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", needle) else None
            present = (probe.lower() in text.lower()) if probe else in_pages
            flag = "OK " if present else "MISSING FROM SELECTION"
            if not present:
                failures += 1
            print(f"    {flag:22} {name:24} expected on page {page}")
    return failures


def run(provider_name: str, model: str, prompt_variant: str, limit: int | None) -> list[Result]:
    provider = _provider(provider_name, model)
    template = _header_prompt(prompt_variant)
    results: list[Result] = []

    for expected in TRUTH[: limit or len(TRUTH)]:
        if not expected.path.exists():
            continue
        document = parse_document(expected.path, DocumentKind.NOTIFICATION)
        # Sized to the provider, as the real pipeline does. Groq's free tier
        # caps at 8,000 tokens per minute, so a selection tuned for Gemini is
        # rejected outright with a 413 -- a hosted model with a SMALLER usable
        # window than the local one, which is not the intuitive ordering.
        budget = provider.input_char_budget
        text, _ = select_pages(document, "header", **({"char_budget": budget} if budget else {}))

        result = Result(model=model, prompt=prompt_variant, document=expected.label, seconds=0.0)
        started = time.perf_counter()
        try:
            header = provider.generate_structured(
                template.format(text=text), raw.RawHeader, system=prompts.SYSTEM_PROMPT
            )
            result.seconds = time.perf_counter() - started
            for name, (value, _page) in expected.header.items():
                actual = getattr(header, name, None)
                result.fields[name] = _matches(value, actual)
                result.values[name] = None if actual is None else str(actual)[:60]
        except Exception as exc:
            result.seconds = time.perf_counter() - started
            result.error = f"{type(exc).__name__}: {exc}"[:200]

        # Lists come from separate extractors; only run them when the header
        # worked, since a model that cannot do the small task will not do these.
        if result.error is None:
            for node, template_name, schema, attribute in (
                ("eligibility", prompts.ELIGIBILITY_PROMPT, raw.EligibilityList, "eligibility"),
                ("documents", prompts.MANDATORY_DOCUMENTS_PROMPT, raw.DocumentList, "documents"),
            ):
                try:
                    body, _ = select_pages(
                        document, node, **({"char_budget": budget} if budget else {})
                    )
                    started = time.perf_counter()
                    out = provider.generate_structured(
                        template_name.format(text=body), schema, system=prompts.SYSTEM_PROMPT
                    )
                    result.seconds += time.perf_counter() - started
                    setattr(result, attribute, len(out.items))
                except Exception:
                    pass

        results.append(result)
        print(f"    {model:34} {expected.label:14} {result.score}  {result.seconds:6.1f}s"
              + (f"  ERROR {result.error}" if result.error else ""))
    return results


def table(results: list[Result]) -> str:
    header_fields = sorted({f for r in results for f in r.fields})
    lines = []
    width = max(len(f"{r.model} [{r.prompt}]") for r in results) + 2
    lines.append(
        f"{'model [prompt]':<{width}}{'document':<16}{'header':<9}"
        + "".join(f"{f.replace('_raw','').replace('_',' ')[:13]:<15}" for f in header_fields)
        + f"{'elig':>6}{'docs':>6}{'secs':>8}"
    )
    lines.append("-" * (width + 16 + 9 + 15 * len(header_fields) + 20))
    for r in sorted(results, key=lambda r: (r.document, -r.correct)):
        cells = "".join(
            ("OK" if r.fields.get(f) else ("--" if r.values.get(f) is None else "WRONG")).ljust(15)
            for f in header_fields
        )
        lines.append(
            f"{f'{r.model} [{r.prompt}]':<{width}}{r.document:<16}{r.score:<9}{cells}"
            f"{r.eligibility:>6}{r.documents:>6}{r.seconds:>8.1f}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="ollama")
    parser.add_argument("--models", default="qwen3:4b")
    parser.add_argument("--prompt", default="fewshot", help="fewshot | bare | both")
    parser.add_argument("--limit", type=int, default=None, help="how many documents")
    parser.add_argument("--verify-truth", action="store_true")
    parser.add_argument("--json", help="append results to this file")
    args = parser.parse_args()

    if args.verify_truth:
        missing = verify_truth()
        print(f"\n  {'PASS' if not missing else f'{missing} value(s) not in the selection'}")
        return 0 if not missing else 1

    variants = ["bare", "fewshot"] if args.prompt == "both" else [args.prompt]
    results: list[Result] = []
    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        for variant in variants:
            print(f"\n  == {args.provider}/{model} prompt={variant}")
            results += run(args.provider, model, variant, args.limit)

    print("\n" + table(results))

    if args.json:
        path = Path(args.json)
        existing = json.loads(path.read_text()) if path.exists() else []
        existing += [
            {
                "provider": args.provider, "model": r.model, "prompt": r.prompt,
                "document": r.document, "seconds": round(r.seconds, 1),
                "fields": r.fields, "values": r.values,
                "eligibility": r.eligibility, "documents": r.documents, "error": r.error,
            }
            for r in results
        ]
        path.write_text(json.dumps(existing, indent=1))
        print(f"\n  appended to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
