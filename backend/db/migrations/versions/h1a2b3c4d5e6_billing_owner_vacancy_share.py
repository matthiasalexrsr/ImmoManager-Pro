"""Preserve explicit owner cost shares in utility billing snapshots.

Revision ID: h1a2b3c4d5e6
Revises: g1a2b3c4d5e6
"""
from importlib import import_module

import sqlalchemy as sa
from alembic import op

revision = "h1a2b3c4d5e6"
down_revision = "g1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from backend.services.billing_settlement import ensure_owner_share_schema
    ensure_owner_share_schema(op.get_bind())


def downgrade() -> None:
    connection = op.get_bind()
    # Alembic SQLite DDL is not transactional. Check the preceding migration's
    # financial evidence before dropping our column on the way to that revision.
    preceding = import_module("backend.db.migrations.versions.g1a2b3c4d5e6_billing_settlement_integrity")
    preceding.assert_no_billing_history(connection)
    if connection.execute(sa.text("SELECT COUNT(*) FROM billing_periods WHERE owner_cost_share IS NOT NULL")).scalar():
        raise RuntimeError("Owner allocation snapshots exist; downgrade refused. Restore a complete backup instead.")
    with op.batch_alter_table("billing_periods") as batch:
        batch.drop_column("owner_cost_share")
