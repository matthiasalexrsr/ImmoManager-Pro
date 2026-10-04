"""Indexed recurrence continuation without changing retained job evidence."""

from alembic import op
from sqlalchemy import inspect

revision = "h2a2b3c4d5e6"
down_revision = "g2a2b3c4d5e6"
branch_labels = depends_on = None

INDICES = (
    ("ix_scheduler_completed_source", "operational_work_items", ["action_key", "planned_revision", "state", "created_at", "id"]),
    ("ix_scheduler_task_due", "tasks", ["parent_task_id", "due_date", "id"]),
)


def upgrade():
    connection = op.get_bind()
    for name, table, columns in INDICES:
        existing = next((value for value in inspect(connection).get_indexes(table) if value["name"] == name), None)
        if existing is None:
            op.create_index(name, table, columns)
        elif existing["column_names"] != columns or existing.get("unique"):
            raise RuntimeError("Existing scheduler index has an unexpected definition: " + name)


def downgrade():
    for name, table, _ in reversed(INDICES):
        op.drop_index(name, table_name=table)
