"""Persistent local recurrence and notification identities.

Revision ID: j1a2b3c4d5e6
Revises: i2a2b3c4d5e6
"""
from alembic import op
from sqlalchemy import inspect, text

revision = "j1a2b3c4d5e6"
down_revision = "i2a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    from backend.services.operational_schedule import ensure_operational_schema
    ensure_operational_schema(op.get_bind())


def downgrade():
    connection = op.get_bind()
    existing = set(inspect(connection).get_table_names())
    for table in ("operational_schedules", "operational_occurrences", "operational_dispatches", "operational_ticks"):
        if table in existing and connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar():
            raise RuntimeError("Operational history exists; downgrade refused. Restore a full recovery archive instead.")
    for table in ("operational_ticks", "operational_dispatches", "operational_occurrences", "operational_schedules", "operational_lock"):
        if table in existing:
            op.drop_table(table)
