"""Durable checked bank import and immutable publication provenance.

Revision ID: u1a2b3c4d5e6
Revises: t1a2b3c4d5e6
"""
from alembic import op

revision = "u1a2b3c4d5e6"
down_revision = "t1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    from backend.db.bank_import_schema import ensure_bank_import_schema
    ensure_bank_import_schema(op.get_bind())


def downgrade():
    from backend.db.bank_import_models import BANK_IMPORT_TABLES
    from backend.db.bank_import_schema import drop_bank_import_triggers
    drop_bank_import_triggers(op.get_bind())
    for table in reversed(BANK_IMPORT_TABLES):
        table.drop(op.get_bind(), checkfirst=True)
