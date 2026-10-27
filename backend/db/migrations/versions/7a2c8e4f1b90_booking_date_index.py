"""Index date-only booking ranges used by cashflow and other finance totals.

Revision ID: 7a2c8e4f1b90
Revises: 3c7e9a1d5f20
Create Date: 2026-10-13

Existing databases receive this index only through the explicit schema upgrade.
Fresh create_all databases already have it through the matching ORM declaration.
"""

import sqlalchemy as sa
from alembic import op

revision = "7a2c8e4f1b90"
down_revision = "3c7e9a1d5f20"
branch_labels = None
depends_on = None

INDEX = "idx_bookings_date"


def upgrade() -> None:
    indexes = sa.inspect(op.get_bind()).get_indexes("bookings")
    if INDEX not in {index["name"] for index in indexes}:
        op.create_index(INDEX, "bookings", ["booking_date"])


def downgrade() -> None:
    indexes = sa.inspect(op.get_bind()).get_indexes("bookings")
    if INDEX in {index["name"] for index in indexes}:
        op.drop_index(INDEX, table_name="bookings")
