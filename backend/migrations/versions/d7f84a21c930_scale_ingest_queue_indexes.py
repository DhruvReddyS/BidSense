"""Add claim and owner indexes for the durable ingestion queue.

Revision ID: d7f84a21c930
Revises: c42d18f0a1be
"""

from alembic import op

revision = "d7f84a21c930"
down_revision = "c42d18f0a1be"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_ingest_jobs_queue_claim", "ingest_jobs", ["status", "created_at"]
    )
    op.create_index(
        "ix_ingest_jobs_owner_created", "ingest_jobs", ["owner_user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_ingest_jobs_owner_created", table_name="ingest_jobs")
    op.drop_index("ix_ingest_jobs_queue_claim", table_name="ingest_jobs")
