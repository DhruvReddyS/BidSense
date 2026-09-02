"""Populate the document store from documents ingested before it existed.

    python -m scripts.backfill_documents [--dry-run]

Citation click-through needs the original file. Rows written before the store
existed have a `source_file` path and no `content_hash`; where that path still
resolves, the bytes are hashed, stored, and the hash written back. Where it does
not, the row is reported and left alone -- the API already tells a vendor that
document is not retained rather than pretending.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models import TenderNotificationRow, VendorSubmissionRow  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.documents import content_hash, store_document  # noqa: E402
from sqlalchemy import select  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    stored = missing = already = 0
    with session_scope() as session:
        for model, label in ((TenderNotificationRow, "notification"), (VendorSubmissionRow, "bid")):
            for row in session.scalars(select(model)):
                name = getattr(row, "tender_id", None) or getattr(row, "vendor_id", "?")
                if row.content_hash:
                    already += 1
                    continue
                if not row.source_file or not Path(row.source_file).exists():
                    print(f"  MISSING  {label:12} {str(name)[:44]:44} {row.source_file}")
                    missing += 1
                    continue
                digest = content_hash(row.source_file)
                if not args.dry_run:
                    store_document(row.source_file, digest=digest)
                    row.content_hash = digest
                print(f"  stored   {label:12} {str(name)[:44]:44} {digest[:12]}")
                stored += 1

    print(f"\n  {stored} stored, {already} already had a hash, {missing} source file(s) gone")
    if missing:
        print("  Those rows keep working; their citations show page and clause "
              "without a page image until the file is re-uploaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
