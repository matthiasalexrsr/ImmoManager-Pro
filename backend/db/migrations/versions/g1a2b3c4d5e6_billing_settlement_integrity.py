"""Persistent utility revisions and unique traceable settlement obligations.

Revision ID: g1a2b3c4d5e6
Revises: f0a1b2c3d4e5
"""
from typing import cast

import sqlalchemy as sa
from alembic import op

revision = "g1a2b3c4d5e6"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    from backend.db.orm_models import BillingSettlementORM
    from backend.services.billing_settlement import ensure_billing_schema
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        ensure_billing_schema(connection)
    else:
        op.add_column("billing_periods", sa.Column("source_period_id", sa.String(), nullable=True))
        op.add_column("billing_periods", sa.Column("revision_number", sa.Integer(), server_default="1", nullable=False))
        op.add_column("billing_periods", sa.Column("revision_notes", sa.Text(), nullable=True))
        op.add_column("utility_statements", sa.Column("source_statement_id", sa.String(), nullable=True))
        op.add_column("utility_statements", sa.Column("advance_details", sa.JSON(), nullable=True))
        op.add_column("utility_statements", sa.Column("calculation_hash", sa.String(), nullable=True))
        op.create_foreign_key("fk_billing_revision_source", "billing_periods", "billing_periods", ["source_period_id"], ["id"], ondelete="RESTRICT")
        op.create_foreign_key("fk_statement_revision_source", "utility_statements", "utility_statements", ["source_statement_id"], ["id"], ondelete="RESTRICT")
        ensure_billing_schema(connection)
    cast(sa.Table, BillingSettlementORM.__table__).create(connection, checkfirst=True)


def assert_no_billing_history(connection) -> None:
    """Refuse before DDL when downgrading would erase financial evidence."""
    if connection.execute(sa.text("SELECT COUNT(*) FROM billing_settlements")).scalar():
        raise RuntimeError("Billing settlement history exists; downgrade refused. Restore a complete backup instead.")
    if connection.execute(sa.text(
        "SELECT COUNT(*) FROM utility_statements WHERE advance_details IS NOT NULL "
        "OR calculation_hash IS NOT NULL OR source_statement_id IS NOT NULL "
        "OR status IN ('finalized', 'delivered', 'disputed', 'corrected')"
    )).scalar():
        raise RuntimeError("Billing statement evidence exists; downgrade refused. Restore a complete backup instead.")
    if connection.execute(sa.text(
        "SELECT COUNT(*) FROM billing_periods WHERE source_period_id IS NOT NULL "
        "OR revision_number <> 1 OR revision_notes IS NOT NULL "
        "OR status IN ('finalized', 'delivered', 'disputed', 'corrected')"
    )).scalar():
        raise RuntimeError("Billing revision or finalized period history exists; downgrade refused. Restore a complete backup instead.")


def downgrade():
    connection = op.get_bind()
    assert_no_billing_history(connection)
    op.drop_table("billing_settlements")
    op.drop_index("uq_receivables_statement", table_name="receivables")
    op.drop_index("uq_utility_statements_period_contract", table_name="utility_statements")
    op.drop_index("uq_billing_period_revision_source", table_name="billing_periods")
    with op.batch_alter_table("utility_statements") as batch:
        batch.drop_column("calculation_hash")
        batch.drop_column("advance_details")
        batch.drop_column("source_statement_id")
    with op.batch_alter_table("billing_periods") as batch:
        batch.drop_column("revision_notes")
        batch.drop_column("revision_number")
        batch.drop_column("source_period_id")
