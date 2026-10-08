"""Booking reversals: a Storno names the booking it cancels.

Adds the nullable ``bookings.reverses_booking_id`` (references bookings, SET NULL) and
its index; existing bookings stay ordinary bookings. A downgrade is refused while a
reversal exists, because the older program would count it as an income or expense of
its own. Without reversals the column is removed again, except on a SQLite database
adopted from create_all(), whose table-level reference SQLite cannot drop: the unused
nullable column stays there, older versions ignore it.

Revision ID: f3b9c1d7e2a5
Revises: b8e3d5f7a2c4
"""

import re

import sqlalchemy as sa
from alembic import op

revision = "f3b9c1d7e2a5"
down_revision = "b8e3d5f7a2c4"
branch_labels = None
depends_on = None

COLUMN = "reverses_booking_id"
INDEX = "idx_bookings_reverses"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if COLUMN not in {column["name"] for column in inspector.get_columns("bookings")}:
        if bind.dialect.name == "sqlite":
            # A nullable REFERENCES column is added in place; rebuilding bookings would
            # touch the tables that reference it (payment allocations).
            op.execute(f"ALTER TABLE bookings ADD COLUMN {COLUMN} VARCHAR REFERENCES bookings(id) ON DELETE SET NULL")
        else:
            op.add_column("bookings", sa.Column(
                COLUMN, sa.String(), sa.ForeignKey("bookings.id", name="fk_bookings_reverses", ondelete="SET NULL"),
                nullable=True,
            ))
    if INDEX not in {index["name"] for index in inspector.get_indexes("bookings")}:
        op.create_index(INDEX, "bookings", [COLUMN])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if COLUMN not in {column["name"] for column in inspector.get_columns("bookings")}:
        return
    bookings = sa.table("bookings", sa.column(COLUMN))
    reversals = bind.execute(sa.select(sa.func.count()).select_from(bookings).where(
        bookings.c[COLUMN].isnot(None))).scalar_one()
    if reversals:
        raise RuntimeError("Cannot remove booking reversal links while reversals exist")
    if INDEX in {index["name"] for index in inspector.get_indexes("bookings")}:
        op.drop_index(INDEX, table_name="bookings")
    if bind.dialect.name == "sqlite":
        ddl = bind.exec_driver_sql("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'bookings'")
        if re.search(rf"foreign\s+key\s*\(\s*\"?{COLUMN}\"?\s*\)", ddl.scalar_one() or "", re.IGNORECASE):
            return
        op.execute(f"ALTER TABLE bookings DROP COLUMN {COLUMN}")
    else:
        op.drop_column("bookings", COLUMN)
