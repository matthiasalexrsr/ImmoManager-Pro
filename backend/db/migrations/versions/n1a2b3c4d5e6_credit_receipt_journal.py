"""Immutable credit payout/offset receipts and exact cents.

Revision ID: n1a2b3c4d5e6
Revises: m1a2b3c4d5e6
SQLite table rebuilding requires an offline migration connection. No rows or
existing trigger definitions are discarded; populated journals cannot downgrade.
"""

import sqlalchemy as sa
from alembic import op

revision = "n1a2b3c4d5e6"
down_revision = "m1a2b3c4d5e6"
branch_labels = None
depends_on = None


def _allocation_check(expression):
    connection = op.get_bind()
    triggers = []
    if connection.dialect.name == "sqlite":
        if connection.execute(sa.text("PRAGMA foreign_keys")).scalar():
            raise RuntimeError("Credit schema upgrade requires the stopped application and an offline SQLite migration connection.")
        triggers = list(connection.execute(sa.text("SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name='bookings' AND sql IS NOT NULL")).scalars())
    checks = {row["name"] for row in sa.inspect(connection).get_check_constraints("bookings")}
    with op.batch_alter_table("bookings") as batch:
        if "ck_bookings_allocation" in checks:
            batch.drop_constraint("ck_bookings_allocation", type_="check")
        batch.create_check_constraint("ck_bookings_allocation", expression)
    for trigger_sql in triggers:
        connection.exec_driver_sql(trigger_sql)
    if connection.dialect.name == "sqlite" and connection.execute(sa.text("PRAGMA foreign_key_check")).first():
        raise RuntimeError("Credit schema upgrade detected inconsistent foreign keys; restore the verified full backup.")


def upgrade():
    _allocation_check("allocated_amount >= 0 AND allocated_amount <= abs(amount)")
    op.create_table("credit_receipts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("contract_id", sa.String(), sa.ForeignKey("contracts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_settlement_id", sa.String(), sa.ForeignKey("billing_settlements.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("idempotency_key", sa.String(100), unique=True, nullable=False),
        sa.Column("amount_cents", sa.Text(), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("booking_id", sa.String(), sa.ForeignKey("bookings.id", ondelete="RESTRICT")),
        sa.Column("target_type", sa.Text()), sa.Column("target_id", sa.String()),
        sa.Column("payment_id", sa.String(), sa.ForeignKey("payments.id", ondelete="RESTRICT"), unique=True),
        sa.Column("note", sa.Text()), sa.Column("actor_id", sa.String()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("method IN ('cash', 'bank', 'offset')", name="ck_credit_method"),
        sa.CheckConstraint("(method = 'bank' AND booking_id IS NOT NULL AND payment_id IS NULL AND target_id IS NULL AND target_type IS NULL) OR (method = 'cash' AND booking_id IS NULL AND payment_id IS NULL AND target_id IS NULL AND target_type IS NULL) OR (method = 'offset' AND booking_id IS NULL AND payment_id IS NOT NULL AND target_id IS NOT NULL AND target_type IN ('receivable', 'rent_charge'))", name="ck_credit_links"))
    for name, column in (("idx_credit_contract", "contract_id"), ("idx_credit_source", "source_settlement_id"), ("idx_credit_booking", "booking_id")):
        op.create_index(name, "credit_receipts", [column])
    op.create_table("credit_reversals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("receipt_id", sa.String(), sa.ForeignKey("credit_receipts.id", ondelete="RESTRICT"), unique=True, nullable=False),
        sa.Column("idempotency_key", sa.String(100), unique=True, nullable=False),
        sa.Column("amount_cents", sa.Text(), nullable=False),
        sa.Column("reversal_date", sa.Date(), nullable=False), sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("payment_reversal_id", sa.String(), sa.ForeignKey("payment_reversals.id", ondelete="RESTRICT"), unique=True),
        sa.Column("actor_id", sa.String()), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))


def downgrade():
    connection = op.get_bind()
    for table in ("credit_receipts", "credit_reversals"):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Credit receipt history exists; downgrade refused. Restore a verified full backup.")
    if connection.execute(sa.text("SELECT 1 FROM bookings WHERE amount < 0 AND allocated_amount > 0 LIMIT 1")).first():
        raise RuntimeError("Negative bank allocations exist; downgrade refused.")
    # Check offline precondition before dropping either journal.
    if connection.dialect.name == "sqlite" and connection.execute(sa.text("PRAGMA foreign_keys")).scalar():
        raise RuntimeError("Credit schema downgrade requires an offline SQLite migration connection.")
    op.drop_table("credit_reversals")
    op.drop_table("credit_receipts")
    _allocation_check("allocated_amount >= 0 AND (allocated_amount = 0 OR allocated_amount <= amount)")
