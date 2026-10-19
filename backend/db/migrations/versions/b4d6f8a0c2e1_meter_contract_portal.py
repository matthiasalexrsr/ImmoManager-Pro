"""A meter's own supply contract and the providers' customer portals.

The meter form asked for "Vertragsnummer" and "Vertragslaufzeit bis", but meters
had no such columns, so both were silently dropped on save. Meters now keep the
landlord's own supply contract (``contract_number``, ``contract_end_date``) and
a link to the provider's customer portal (``portal_url``); service contracts get
``portal_url`` too. Guarded like a7d3c5e9f2b1, so create_all databases that
already have the columns pass. A downgrade is refused while any of them is used.

Revision ID: b4d6f8a0c2e1
Revises: a7d3c5e9f2b1
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4d6f8a0c2e1"
down_revision: str | None = "a7d3c5e9f2b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _new_columns() -> dict[str, list[sa.Column]]:
    return {
        "meters": [
            sa.Column("contract_number", sa.String(100), nullable=True),
            sa.Column("contract_end_date", sa.Date(), nullable=True),
            sa.Column("portal_url", sa.String(500), nullable=True),
        ],
        "service_contracts": [sa.Column("portal_url", sa.String(500), nullable=True)],
    }


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, columns in _new_columns().items():
        if not inspector.has_table(table):
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    present: dict[str, list[str]] = {}
    for table, columns in _new_columns().items():
        if not inspector.has_table(table):
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        present[table] = [column.name for column in columns if column.name in existing]
    for table, names in present.items():
        if names and bind.execute(sa.text(
                f"SELECT 1 FROM {table} WHERE " + " OR ".join(f"{name} IS NOT NULL" for name in names) + " LIMIT 1")).first():
            raise RuntimeError("Downgrade would discard meter supply contracts or customer portal links; keep this "
                               "version or clear those fields first.")
    for table, names in present.items():
        for name in names:
            # SQLite drops the column in place; a batch rebuild would also drop the table's triggers
            if bind.dialect.name == "sqlite":
                op.execute(f"ALTER TABLE {table} DROP COLUMN {name}")
            else:
                op.drop_column(table, name)
