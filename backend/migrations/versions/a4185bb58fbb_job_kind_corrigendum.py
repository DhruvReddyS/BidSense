"""job kind: corrigendum

Adding a member to a Postgres enum is not something Alembic autogenerates -- the
comparison it runs does not look inside enum types -- so this is written by hand.
Without it, uploading a corrigendum fails at INSERT with an invalid-input-value
error rather than anything a user could act on.

`ADD VALUE IF NOT EXISTS` cannot run inside a transaction block on older
Postgres, hence the autocommit block. There is no downgrade: Postgres has no
DROP VALUE, and rewriting the type would have to rewrite every row referencing
it. Leaving an unused label behind is harmless; pretending it can be removed is
not.

Revision ID: a4185bb58fbb
Revises: 5bfd0986e88f
Create Date: 2026-09-02 16:04:06.364344
"""
from alembic import op

revision = "a4185bb58fbb"
down_revision = "5bfd0986e88f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE job_kind ADD VALUE IF NOT EXISTS 'corrigendum'")


def downgrade() -> None:
    # Postgres cannot remove an enum label. The value simply stops being used.
    pass
