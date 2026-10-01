"""Index bounded booking pages without deleting or changing existing data.

Revision ID: l1a2b3c4d5e6
Revises: k1a2b3c4d5e6
"""
from alembic import op

revision = "l1a2b3c4d5e6"
down_revision = "k1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    from backend.db.booking_indexes import ensure_booking_indexes
    ensure_booking_indexes(op.get_bind())


def downgrade():
    from backend.db.booking_indexes import BOOKING_INDEXES
    for index in reversed(BOOKING_INDEXES):
        index.drop(op.get_bind(), checkfirst=True)
