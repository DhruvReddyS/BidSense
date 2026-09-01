"""Phase 0 bootstrap: create the Postgres schema and the Qdrant collection.

    python -m scripts.bootstrap            # create if absent (idempotent)
    python -m scripts.bootstrap --recreate # DROP and rebuild both (destructive)

Uses Alembic when a migration exists, falling back to create_all so the schema
is usable before the first revision is generated.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.vector.qdrant import collection_stats, ensure_collection  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("bootstrap")


def setup_postgres(recreate: bool) -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    log.info("Postgres reachable at %s:%s", settings.postgres_host, settings.postgres_port)

    if recreate:
        log.warning("Dropping all TenderIQ tables and enum types")
        Base.metadata.drop_all(engine)
        with engine.begin() as conn:
            for enum_name in ("user_role", "criterion_type", "vendor_status"):
                conn.execute(text(f"DROP TYPE IF EXISTS {enum_name} CASCADE"))
            # Reset Alembic's bookkeeping too, or the rebuild is a no-op.
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    if _has_migrations():
        _alembic_upgrade()
        log.info("Applied Alembic migrations to head")
    else:
        Base.metadata.create_all(engine)
        log.info("No migrations present; created schema directly via metadata")
    log.info(
        "%d tables: %s", len(Base.metadata.tables), ", ".join(sorted(Base.metadata.tables))
    )


def _has_migrations() -> bool:
    versions = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    return any(versions.glob("*.py"))


def _alembic_upgrade() -> None:
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(cfg, "head")


def setup_qdrant(recreate: bool) -> None:
    ensure_collection(recreate=recreate)
    log.info("Qdrant collection: %s", collection_stats())


def main() -> int:
    parser = argparse.ArgumentParser(description="TenderIQ Phase 0 bootstrap")
    parser.add_argument(
        "--recreate", action="store_true", help="DROP existing schema/collection first"
    )
    parser.add_argument("--skip-qdrant", action="store_true")
    parser.add_argument("--skip-postgres", action="store_true")
    args = parser.parse_args()

    if not args.skip_postgres:
        setup_postgres(args.recreate)
    if not args.skip_qdrant:
        setup_qdrant(args.recreate)

    log.info("Phase 0 bootstrap complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
