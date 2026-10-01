"""Link bank bookings to receipts and preserve full payment reversals.

Revision ID: d8e9f0a1b2c3
Revises: a7b8c9d0e1f2
"""

import sqlalchemy as sa
from alembic import op

revision = "d8e9f0a1b2c3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None
_naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def _target_fk_names():
    return {fk["constrained_columns"][0]: fk["name"] or
            f"fk_payments_{fk['constrained_columns'][0]}_{fk['referred_table']}"
            for fk in sa.inspect(op.get_bind()).get_foreign_keys("payments")}


def upgrade() -> None:
    old_names = _target_fk_names()
    with op.batch_alter_table("bookings") as batch:
        batch.add_column(sa.Column("allocated_amount", sa.Numeric(12, 2), nullable=False, server_default="0"))
        batch.create_check_constraint("ck_bookings_allocation", "allocated_amount >= 0 AND (allocated_amount = 0 OR allocated_amount <= amount)")
    with op.batch_alter_table("payments", naming_convention=_naming) as batch:
        batch.add_column(sa.Column("booking_id", sa.String(), nullable=True))
        batch.create_foreign_key("fk_payments_booking_id_bookings", "bookings", ["booking_id"], ["id"], ondelete="RESTRICT")
        for column, table in (("receivable_id", "receivables"), ("rent_charge_id", "rent_charges")):
            name = f"fk_payments_{column}_{table}"
            batch.drop_constraint(old_names[column], type_="foreignkey")
            batch.create_foreign_key(name, table, [column], ["id"], ondelete="RESTRICT")
    op.create_index("idx_payments_booking", "payments", ["booking_id"])
    op.create_table(
        "payment_reversals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("payment_id", sa.String(), sa.ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("reversal_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("amount > 0", name="ck_reversals_positive"),
    )


def downgrade() -> None:
    op.drop_table("payment_reversals")
    op.drop_index("idx_payments_booking", table_name="payments")
    with op.batch_alter_table("payments", naming_convention=_naming) as batch:
        batch.drop_constraint("fk_payments_booking_id_bookings", type_="foreignkey")
        batch.drop_column("booking_id")
        for column, table in (("receivable_id", "receivables"), ("rent_charge_id", "rent_charges")):
            name = f"fk_payments_{column}_{table}"
            batch.drop_constraint(name, type_="foreignkey")
            batch.create_foreign_key(name, table, [column], ["id"], ondelete="CASCADE")
    with op.batch_alter_table("bookings") as batch:
        batch.drop_constraint("ck_bookings_allocation", type_="check")
        batch.drop_column("allocated_amount")
