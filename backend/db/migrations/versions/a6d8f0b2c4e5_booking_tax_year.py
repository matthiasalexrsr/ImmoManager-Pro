"""Bookings can name the tax year of a payment around the turn of the year.

R12-14: the annual tax evaluation followed the booking date strictly. § 11 Abs. 1 Satz 2 EStG
assigns regularly recurring payments made within ten days around the turn of the year (January
rent paid on 29 December, property tax, loan instalments) to the year they belong to. A booking
now holds that year (``tax_year``); the tax source selects by it, other reports keep the date.

Guarded like a7d3c5e9f2b1, so create_all databases that already have the column pass. A
downgrade is refused while a booking names a tax year: the tax evaluation would silently change.
The column is dropped without a table copy (SQLite >= 3.35), so the booking checks stay.

Revision ID: a6d8f0b2c4e5
Revises: f5c7e9a1b3d4
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.db.migrations.retained import guard_branch_downgrade

revision: str = "a6d8f0b2c4e5"
down_revision: str | None = "f5c7e9a1b3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns("bookings")}


def upgrade() -> None:
    if "tax_year" not in _columns(op.get_bind()):
        op.add_column("bookings", sa.Column("tax_year", sa.Integer(), nullable=True))


def downgrade() -> None:
    guard_branch_downgrade()
    bind = op.get_bind()
    if "tax_year" not in _columns(bind):
        return
    if bind.execute(sa.text("SELECT 1 FROM bookings WHERE tax_year IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Downgrade would discard the tax year of bookings around the turn of the year; keep "
                           "this version or remove the tax years first.")
    op.drop_column("bookings", "tax_year")
