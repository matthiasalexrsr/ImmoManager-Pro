"""Persist reviewable rental snapshots and atomic resumable generation.

Revision ID: q1a2b3c4d5e6
Revises: p1a2b3c4d5e6
"""
from alembic import op

revision = "q1a2b3c4d5e6"
down_revision = "p1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    from backend.db.rent_batch_schema import ensure_rent_batch_schema
    ensure_rent_batch_schema(op.get_bind())


def downgrade():
    from backend.db.rent_batch_models import RENT_BATCH_TABLES
    from backend.db.rent_batch_schema import drop_rent_source_triggers
    drop_rent_source_triggers(op.get_bind())
    for table in reversed(RENT_BATCH_TABLES):
        table.drop(op.get_bind(), checkfirst=True)
