"""Utility statements: units of measure, meter replacement, dated occupants, objections, final versions.

- meters get the unit of their readings and a removal date (meter replacement);
  allocation keys the unit they bill in;
- contracts get dated occupants (persons from a date on) for the person key;
- statements keep their advance sections and, once finalized, the frozen
  document they show;
- billing periods get a revision and the version a correction corrects;
- objections (Widerspruch) are recorded against issued statements.

Additive and guarded: databases built by create_all that already have a column
or table pass. A downgrade is refused while any of the new data exists, because
the older program would silently drop it.

Revision ID: c3e8a1f5d9b7
Revises: b8e3d5f7a2c4
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3e8a1f5d9b7"
down_revision: str | None = "b8e3d5f7a2c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _new_columns() -> dict[str, list[sa.Column]]:
    """Frozen DDL of this revision (later model changes must not alter it)."""
    return {
        "meters": [
            sa.Column("measure_unit", sa.String(20), nullable=True),
            sa.Column("removal_date", sa.Date(), nullable=True),
        ],
        "allocation_keys": [sa.Column("measure_unit", sa.Text(), nullable=True)],
        "billing_periods": [
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("corrects_period_id", sa.String(), nullable=True),
            sa.Column("revision_notes", sa.Text(), nullable=True),
        ],
        "utility_statements": [
            sa.Column("advance_sections", sa.JSON(), nullable=True),
            sa.Column("final_document", sa.JSON(), nullable=True),
        ],
    }


def _tables(metadata: sa.MetaData) -> list[sa.Table]:
    # Referenced tables are only reflected names here; create() needs them in the metadata.
    for name in ("contracts", "billing_periods", "utility_statements"):
        sa.Table(name, metadata, sa.Column("id", sa.String(), primary_key=True))
    return [
        sa.Table(
            "contract_occupancies", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("contract_id", sa.String(36), sa.ForeignKey("contracts.id"), nullable=False),
            sa.Column("valid_from", sa.Date(), nullable=False),
            sa.Column("persons", sa.Integer(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("contract_id", "valid_from", name="uq_contract_occupancies_contract_date"),
            sa.CheckConstraint("persons >= 0", name="ck_contract_occupancies_persons"),
            sa.Index("ix_contract_occupancies_contract_id", "contract_id"),
        ),
        sa.Table(
            "billing_objections", metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("billing_period_id", sa.String(),
                      sa.ForeignKey("billing_periods.id", ondelete="CASCADE"), nullable=False),
            sa.Column("statement_id", sa.String(),
                      sa.ForeignKey("utility_statements.id", ondelete="CASCADE"), nullable=True),
            sa.Column("received_on", sa.Date(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("correction_period_id", sa.String(),
                      sa.ForeignKey("billing_periods.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Index("ix_billing_objections_billing_period_id", "billing_period_id"),
        ),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, columns in _new_columns().items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)
    if "idx_billing_periods_corrects" not in {i["name"] for i in inspector.get_indexes("billing_periods")}:
        op.create_index("idx_billing_periods_corrects", "billing_periods", ["corrects_period_id"])
    existing_tables = set(inspector.get_table_names())
    for new_table in _tables(sa.MetaData()):
        if new_table.name not in existing_tables:
            new_table.create(bind)


# (what would be lost, query that finds it)
_KEPT_DATA = [
    ("objections", "SELECT 1 FROM billing_objections LIMIT 1"),
    ("dated occupants", "SELECT 1 FROM contract_occupancies LIMIT 1"),
    ("frozen final statements", "SELECT 1 FROM utility_statements WHERE final_document IS NOT NULL LIMIT 1"),
    ("corrections", "SELECT 1 FROM billing_periods WHERE corrects_period_id IS NOT NULL OR revision > 1 LIMIT 1"),
    ("meter replacements or units", "SELECT 1 FROM meters WHERE removal_date IS NOT NULL "
                                    "OR measure_unit IS NOT NULL LIMIT 1"),
    ("key units", "SELECT 1 FROM allocation_keys WHERE measure_unit IS NOT NULL LIMIT 1"),
]


def downgrade() -> None:
    bind = op.get_bind()
    found = [label for label, query in _KEPT_DATA if bind.execute(sa.text(query)).first()]
    if found:
        raise RuntimeError(
            "Downgrade would discard billing history (" + ", ".join(found) + "); "
            "keep this version or export a snapshot and remove that data first.")
    op.drop_table("billing_objections")
    op.drop_table("contract_occupancies")
    op.drop_index("idx_billing_periods_corrects", table_name="billing_periods")
    for table, columns in _new_columns().items():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.drop_column(column.name)
