"""Ingest tender documents from the command line (Phase 1).

    # one notification
    python -m scripts.ingest notification data/notifications/NOTIF_ITservices_01.pdf

    # every notification in a folder -- the Phase 1 "test against 5-10 real
    # notifications first" step
    python -m scripts.ingest notification data/notifications/ --report

    # a vendor bid against a tender
    python -m scripts.ingest vendor data/vendors/VENDOR_01.pdf \
        --vendor-id V-01 --tender-id TSTS/2026/IT/0042

    # parse only, no LLM and no database -- checks OCR/table handling on a new
    # document format before spending API calls on it
    python -m scripts.ingest inspect data/notifications/NOTIF_ITservices_01.pdf
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingest import ocr_available, missing_dependencies, parse_document  # noqa: E402
from app.schemas.common import DocumentKind  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("ingest")

SUPPORTED = {".pdf", ".docx"}


def _collect(target: Path) -> list[Path]:
    if target.is_dir():
        return sorted(p for p in target.iterdir() if p.suffix.lower() in SUPPORTED)
    return [target]


def cmd_inspect(args) -> int:
    """Parse only. No LLM, no database -- safe to run on any new format."""
    for path in _collect(Path(args.path)):
        document = parse_document(path, DocumentKind.NOTIFICATION)
        print(f"\n=== {document.file_name} ===")
        print(
            f"pages={document.page_count} chars={document.total_chars} "
            f"ocr_pages={document.ocr_page_count} scanned={document.is_scanned}"
        )
        for page in document.pages:
            preview = " ".join(page.text.split())[:100]
            print(
                f"  p{page.page_number}: {page.char_count:>6} chars "
                f"[{page.method.value}] {len(page.tables)} tables | {preview}"
            )
        for warning in document.parse_warnings:
            print(f"  WARNING: {warning}")
    return 0


def _run_batch(args, runner) -> int:
    from app.extraction import IngestReport

    reports: list[IngestReport] = []
    for path in _collect(Path(args.path)):
        try:
            reports.append(runner(path))
        except Exception as exc:
            log.error("%s failed: %s", path.name, exc)

    print("\n" + "=" * 70)
    for report in reports:
        print(report.summary())
        for error in report.extraction_errors:
            print(f"    ERROR: {error}")
        for warning in report.parse_warnings[:3]:
            print(f"    WARN:  {warning}")

    if reports:
        ok = sum(1 for r in reports if r.ok)
        total = sum(r.total_seconds for r in reports)
        print("=" * 70)
        print(
            f"{ok}/{len(reports)} clean | {total:.1f}s total | "
            f"{total / len(reports):.1f}s avg per document"
        )

    if args.report:
        out = Path(args.report)
        out.write_text(
            json.dumps(
                [
                    {
                        "file": r.file_name,
                        "identifier": r.identifier,
                        "pages": r.pages,
                        "ocr_pages": r.ocr_pages,
                        "chunks": r.chunks_indexed,
                        "errors": r.extraction_errors,
                        "warnings": r.parse_warnings,
                        "node_timings": dict(r.node_timings),
                        "seconds": {
                            "parse": round(r.parse_seconds, 3),
                            "extract": round(r.extract_seconds, 3),
                            "persist": round(r.persist_seconds, 3),
                        },
                    }
                    for r in reports
                ],
                indent=2,
            )
        )
        print(f"Report written to {out}")

    return 0 if all(r.ok for r in reports) else 1


def cmd_notification(args) -> int:
    from app.extraction import ingest_notification

    return _run_batch(args, lambda p: ingest_notification(p, index=not args.no_index))


def cmd_vendor(args) -> int:
    from app.extraction import ingest_submission

    paths = _collect(Path(args.path))
    if len(paths) > 1 and args.vendor_id:
        log.error("--vendor-id cannot be used with a folder; ids are derived per file")
        return 2

    def run(path: Path):
        # For batch runs the vendor id comes from the filename convention in
        # Section 9.2.2 step 6: VENDOR_<notification>_<serial>.pdf
        vendor_id = args.vendor_id or path.stem
        return ingest_submission(
            path,
            vendor_id=vendor_id,
            tender_id=args.tender_id,
            index=not args.no_index,
        )

    return _run_batch(args, run)


def main() -> int:
    parser = argparse.ArgumentParser(description="TenderIQ document ingestion")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect = subparsers.add_parser("inspect", help="parse only, no LLM or DB")
    inspect.add_argument("path")
    inspect.set_defaults(func=cmd_inspect)

    for name, handler in (("notification", cmd_notification), ("vendor", cmd_vendor)):
        sub = subparsers.add_parser(name, help=f"ingest a {name} (file or folder)")
        sub.add_argument("path")
        sub.add_argument("--no-index", action="store_true", help="skip vector indexing")
        sub.add_argument("--report", help="write a JSON run report to this path")
        if name == "vendor":
            sub.add_argument("--vendor-id", help="defaults to the filename stem")
            sub.add_argument("--tender-id", help="tender this bid is against")
        sub.set_defaults(func=handler)

    args = parser.parse_args()
    if not ocr_available():
        log.warning(
            "OCR unavailable (%s) -- scanned pages will be reported as missing. "
            "Install with: brew install tesseract poppler",
            ", ".join(missing_dependencies()),
        )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
