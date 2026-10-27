"""Usage periods and vacancy rows for utility statements.

Utility statements are split by usage period: each tenancy and each vacant
stretch of a unit gets its own row (vacancy rows have no contract and carry
the landlord's share). Contracts get a household size for person-based keys,
allocation keys the meter type that consumption keys use. Guarded like
9d2e7c41a6b3, so create_all databases that already have the columns pass.

Revision ID: 4f8a1c6e9b27
Revises: 9d2e7c41a6b3
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4f8a1c6e9b27"
down_revision: str | None = "9d2e7c41a6b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _new_columns() -> dict[str, list[sa.Column]]:
    return {
        "utility_statements": [
            sa.Column("party", sa.Text(), nullable=False, server_default="tenant"),
            sa.Column("usage_start", sa.Date(), nullable=True),
            sa.Column("usage_end", sa.Date(), nullable=True),
            sa.Column("usage_days", sa.Integer(), nullable=True),
        ],
        "contracts": [sa.Column("persons", sa.Integer(), nullable=True)],
        "allocation_keys": [sa.Column("meter_type", sa.Text(), nullable=True)],
    }


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, columns in _new_columns().items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)

    contract_id = next(c for c in inspector.get_columns("utility_statements") if c["name"] == "contract_id")
    if not contract_id["nullable"]:
        # SQLite cannot relax NOT NULL in place; batch mode rebuilds the table.
        with op.batch_alter_table("utility_statements") as batch:
            batch.alter_column("contract_id", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM utility_statements WHERE contract_id IS NULL")
    with op.batch_alter_table("utility_statements") as batch:
        batch.alter_column("contract_id", existing_type=sa.String(), nullable=False)
    for table, columns in _new_columns().items():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.drop_column(column.name)
