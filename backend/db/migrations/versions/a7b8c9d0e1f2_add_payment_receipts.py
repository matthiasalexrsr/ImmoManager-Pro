"""Persist payment receipts and receivable balances.

Revision ID: a7b8c9d0e1f2
Revises: f6a1b2c3d4e5
"""

import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "f6a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("receivables", sa.Column("amount_paid", sa.Numeric(12, 2), nullable=False, server_default="0"))
    op.execute("UPDATE receivables SET amount_paid = amount_due WHERE status = 'paid'")
    op.create_table(
        "payments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("receivable_id", sa.String(), sa.ForeignKey("receivables.id", ondelete="CASCADE")),
        sa.Column("rent_charge_id", sa.String(), sa.ForeignKey("rent_charges.id", ondelete="CASCADE")),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("amount > 0", name="ck_payments_positive"),
        sa.CheckConstraint("(receivable_id IS NULL) != (rent_charge_id IS NULL)", name="ck_payments_one_target"),
    )
    op.create_index("idx_payments_receivable", "payments", ["receivable_id"])
    op.create_index("idx_payments_rent_charge", "payments", ["rent_charge_id"])


def downgrade() -> None:
    op.drop_table("payments")
    with op.batch_alter_table("receivables") as batch:
        batch.drop_column("amount_paid")
