"""Taking over running tenancies: the tenant account starts on a later date.

A contract that began before the app was used gets the first of a month from
which its tenant account is kept here (``ledger_start``) and the account's
balance on that day (``carried_balance``: positive the tenant owes it, negative
a credit). Without them every month since the contract start counted as unpaid.
Guarded like 4f8a1c6e9b27, so create_all databases that already have the
columns pass. A downgrade is refused while a contract uses them, because the
accounts of those tenancies would silently change.

Revision ID: 981b2631e1e8
Revises: 3c7e9a1d5f20
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "981b2631e1e8"
down_revision: str | None = "3c7e9a1d5f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _new_columns() -> list[sa.Column]:
    return [
        sa.Column("ledger_start", sa.Date(), nullable=True),
        sa.Column("carried_balance", sa.Numeric(12, 2, asdecimal=False), nullable=True),
    ]


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("contracts")}
    for column in _new_columns():
        if column.name not in existing:
            op.add_column("contracts", column)


def downgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("contracts")}
    names = [column.name for column in _new_columns() if column.name in existing]
    if not names:
        return
    used = " OR ".join(f"{name} IS NOT NULL" for name in names)
    if bind.execute(sa.text(f"SELECT 1 FROM contracts WHERE {used} LIMIT 1")).first():
        raise RuntimeError("Downgrade would discard the takeover date or carried balance of contracts; keep this "
                           "version or clear those fields first.")
    for name in names:
        # SQLite drops the column in place; a batch rebuild would also drop the table's triggers
        if bind.dialect.name == "sqlite":
            op.execute(f"ALTER TABLE contracts DROP COLUMN {name}")
        else:
            op.drop_column("contracts", name)
