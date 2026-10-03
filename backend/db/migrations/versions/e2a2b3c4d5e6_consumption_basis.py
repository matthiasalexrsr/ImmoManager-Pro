"""Explicit medium/unit binding; preserve historical statements without backfill."""

import sqlalchemy as sa
from alembic import op

revision = "e2a2b3c4d5e6"
down_revision = "d2a2b3c4d5e6"
branch_labels = depends_on = None

COLUMNS = {
    "allocation_keys": ("consumption_medium", "consumption_unit"),
    "meters": ("measurement_unit",),
}


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    for table, additions in COLUMNS.items():
        present = {column["name"] for column in inspector.get_columns(table)}
        if present.intersection(additions):
            raise RuntimeError("Consumption basis columns already exist; explicit schema reconciliation required")
    for table, additions in COLUMNS.items():
        for name in additions:
            op.add_column(table, sa.Column(name, sa.Text(), nullable=True))


def downgrade():
    connection = op.get_bind()
    for table, additions in COLUMNS.items():
        reference = sa.table(table, *(sa.column(name, sa.Text()) for name in additions))
        if connection.scalar(sa.select(sa.literal(1)).select_from(reference)
                .where(sa.or_(*(reference.c[name].is_not(None) for name in additions))).limit(1)):
            raise RuntimeError("Downgrade would erase confirmed consumption bindings; retain a compatible full recovery")
    # Native column removal retains the original table, FKs, indices and triggers.
    for table, additions in reversed(tuple(COLUMNS.items())):
        for name in reversed(additions):
            op.drop_column(table, name)
