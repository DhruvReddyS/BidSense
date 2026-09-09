"""Retain the immutable source identity needed to replay interrupted jobs."""
from alembic import op
import sqlalchemy as sa

revision = "c42d18f0a1be"
down_revision = "b71f06e912ad"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ingest_jobs", sa.Column("source_hash", sa.String(length=64), nullable=True))
    op.create_index("ix_ingest_jobs_source_hash", "ingest_jobs", ["source_hash"])


def downgrade():
    op.drop_index("ix_ingest_jobs_source_hash", table_name="ingest_jobs")
    op.drop_column("ingest_jobs", "source_hash")
