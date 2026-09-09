"""Persist extraction provenance and warnings with the data they describe."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'b71f06e912ad'
down_revision = '94fd38faeba5'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('tender_notifications', 'vendor_submissions'):
        op.add_column(table, sa.Column('extraction_metadata', JSONB(), nullable=False, server_default='{}'))


def downgrade():
    for table in ('vendor_submissions', 'tender_notifications'):
        op.drop_column(table, 'extraction_metadata')
