"""Read-only health check: are both stores up and shaped as Phase 0 expects?"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.vector.qdrant import collection_stats, get_client  # noqa: E402

EXPECTED_TABLES = set(Base.metadata.tables)


def main() -> int:
    ok = True

    print("== PostgreSQL ==")
    try:
        found = set(inspect(engine).get_table_names())
        missing = EXPECTED_TABLES - found
        for table in sorted(EXPECTED_TABLES):
            print(f"  {'OK  ' if table in found else 'MISS'} {table}")
        if missing:
            ok = False
    except Exception as exc:
        print(f"  FAIL: {exc}")
        ok = False

    print("\n== Qdrant ==")
    try:
        stats = collection_stats()
        print(f"  {stats}")
        if not stats.get("exists"):
            ok = False
        elif stats["dim"] != settings.embedding_dim:
            print(f"  FAIL: dim {stats['dim']} != configured {settings.embedding_dim}")
            ok = False
        else:
            indexes = get_client().get_collection(settings.qdrant_collection)
            print(f"  payload indexes: {sorted(indexes.payload_schema or {})}")
    except Exception as exc:
        print(f"  FAIL: {exc}")
        ok = False

    print(f"\n{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
