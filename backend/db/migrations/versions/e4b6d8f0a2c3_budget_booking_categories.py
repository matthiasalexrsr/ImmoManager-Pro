"""Budgets name the booking categories their actual amount is taken from.

The actual amount of a budget was entered by hand only. A budget now keeps the booking
categories (``booking_category_ids``, a JSON list) whose expenses of its property and year make
up the actual amount when the user takes it from the bookings (services/budget_actuals.py).

Guarded like a7d3c5e9f2b1, so create_all databases that already have the column pass. A
downgrade is refused while a budget names categories: the choice would be lost silently.

Revision ID: e4b6d8f0a2c3
Revises: d1f3a5c7e9b2
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.db.migrations.retained import guard_branch_downgrade

revision: str = "e4b6d8f0a2c3"
down_revision: str | None = "d1f3a5c7e9b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns("budgets")}


def upgrade() -> None:
    if "booking_category_ids" not in _columns(op.get_bind()):
        op.add_column("budgets", sa.Column("booking_category_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    guard_branch_downgrade()
    bind = op.get_bind()
    if "booking_category_ids" not in _columns(bind):
        return
    for (value,) in bind.execute(sa.text("SELECT booking_category_ids FROM budgets "
                                         "WHERE booking_category_ids IS NOT NULL")):
        if value not in (None, "[]", []):
            raise RuntimeError("Downgrade would discard the booking categories of budgets; remove them from the "
                               "budgets first or keep this version.")
    with op.batch_alter_table("budgets") as batch:
        batch.drop_column("booking_category_ids")
