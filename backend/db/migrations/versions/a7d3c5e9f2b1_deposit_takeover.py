"""Taking over deposits paid before this app's bookings begin.

A deposit received before the app was used has no booking to link, so its file
showed "0,00 € eingegangen" and could not be settled. Deposits now take the day
from which the app keeps the deposit (``carried_on``), the deposit received
until then (``carried_amount``), the interest credited until then
(``carried_interest``) and a note on the evidence (``carried_note``).

Guarded like 981b2631e1e8, so create_all databases that already have the columns
pass. The settled-deposit trigger of 3c7e9a1d5f20 now also keeps the takeover of
a settled deposit (frozen copy below). A downgrade is refused while a deposit
uses the fields, because the received amounts of those files would silently
change.

Revision ID: a7d3c5e9f2b1
Revises: f019a1b2c001
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d3c5e9f2b1"
down_revision: str | None = "f019a1b2c001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MESSAGE = "finalized deposit settlements are immutable"
_SETTLED = "SELECT 1 FROM deposit_settlements s WHERE s.deposit_id = OLD.id AND s.finalized_at IS NOT NULL"
_GUARDED_BEFORE = ("contract_id", "amount", "form")
_GUARDED_AFTER = _GUARDED_BEFORE + ("carried_on", "carried_amount", "carried_interest")


def _new_columns() -> list[sa.Column]:
    return [
        sa.Column("carried_on", sa.Date(), nullable=True),
        sa.Column("carried_amount", sa.Numeric(12, 2, asdecimal=False), nullable=True),
        sa.Column("carried_interest", sa.Numeric(12, 2, asdecimal=False), nullable=True),
        sa.Column("carried_note", sa.Text(), nullable=True),
    ]


def _guard_deposit(bind, columns: tuple[str, ...]) -> None:
    """(Re)create the trigger that keeps a settled deposit's columns (deposit_guards, frozen)."""
    if not sa.inspect(bind).has_table("deposit_settlements"):
        return
    event = "UPDATE OF " + ", ".join(columns)
    if bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS immo_deposits_settled_update")
        op.execute(f"CREATE TRIGGER immo_deposits_settled_update BEFORE {event} ON deposits "
                   f"WHEN EXISTS ({_SETTLED}) BEGIN SELECT RAISE(ABORT, '{_MESSAGE}'); END")
    elif bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS immo_deposits_settled ON deposits")
        op.execute(f"CREATE TRIGGER immo_deposits_settled BEFORE {event} OR DELETE ON deposits "
                   "FOR EACH ROW EXECUTE FUNCTION immo_deposit_part_settled('id')")


def upgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("deposits")}
    for column in _new_columns():
        if column.name not in existing:
            op.add_column("deposits", column)
    _guard_deposit(bind, _GUARDED_AFTER)


def downgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("deposits")}
    names = [column.name for column in _new_columns() if column.name in existing]
    if not names:
        return
    used = " OR ".join(f"{name} IS NOT NULL" for name in names)
    if bind.execute(sa.text(f"SELECT 1 FROM deposits WHERE {used} LIMIT 1")).first():
        raise RuntimeError("Downgrade would discard the takeover of deposits paid before the app's bookings; keep "
                           "this version or clear those fields first.")
    # the trigger names the columns: restore the earlier one before dropping them
    _guard_deposit(bind, _GUARDED_BEFORE)
    for name in names:
        # SQLite drops the column in place; a batch rebuild would also drop the table's triggers
        if bind.dialect.name == "sqlite":
            op.execute(f"ALTER TABLE deposits DROP COLUMN {name}")
        else:
            op.drop_column("deposits", name)
