"""Durable automatic coordination and bounded recurrence lookup indices."""

from alembic import op
from sqlalchemy import inspect, select

from backend.db.operational_job_models import OperationalWorkItemORM
from backend.db.operational_models import OperationalOccurrenceORM
from backend.db.operational_scheduler_models import OperationalSchedulerORM
from backend.db.orm_models import TaskORM

revision = "f2a2b3c4d5e6"
down_revision = "e2a2b3c4d5e6"
branch_labels = depends_on = None

INDICES = (
    ("ix_scheduler_task_parent", TaskORM.__table__, ("parent_task_id", "id")),
    ("ix_scheduler_occurrence_target", OperationalOccurrenceORM.__table__, ("schedule_id", "target_id")),
    ("ix_scheduler_item_fair", OperationalWorkItemORM.__table__, ("lane_id", "state", "attempts", "id")),
)


def upgrade():
    connection = op.get_bind()
    OperationalSchedulerORM.__table__.create(connection)
    for name, table, columns in INDICES:
        if name not in {value["name"] for value in inspect(connection).get_indexes(table.name)}:
            op.create_index(name, table.name, list(columns))


def downgrade():
    connection = op.get_bind()
    if connection.scalar(select(OperationalSchedulerORM.__table__.c.id).limit(1)) is not None:
        raise RuntimeError("Downgrade would erase retained scheduler coordination")
    for name, table, _ in reversed(INDICES):
        op.drop_index(name, table_name=table.name)
    OperationalSchedulerORM.__table__.drop(connection)
