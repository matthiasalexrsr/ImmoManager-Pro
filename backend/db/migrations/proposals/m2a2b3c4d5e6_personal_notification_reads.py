"""Reserved M2 proposal. Root must activate it only after composing actual L2.

This directory is intentionally outside Alembic versions discovery. No global
Notification.read_at values become personal evidence and no reads are backfilled.
"""

from alembic import op
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    String,
    inspect,
    text,
)

from backend.services.notification_inbox_validation import (
    TABLE,
    validate_notification_inbox_schema,
)

revision = "m2a2b3c4d5e6"
down_revision = "l2a2b3c4d5e6"
branch_labels = depends_on = None


def _connection():
    connection = op.get_bind()
    if connection.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("Personal notification reads support SQLite and PostgreSQL")
    return connection


def upgrade():
    connection = _connection()
    if validate_notification_inbox_schema(connection):
        raise RuntimeError(
            "Personal notification read family already exists; explicit reconciliation required"
        )
    if not {"users", "notifications"} <= set(inspect(connection).get_table_names()):
        raise RuntimeError("Personal notification read parent family is incomplete")
    op.create_table(
        TABLE,
        Column("actor_id", String(), nullable=False),
        Column("notification_id", String(), nullable=False),
        Column("read_at", DateTime(), nullable=False),
        PrimaryKeyConstraint("actor_id", "notification_id"),
        ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="CASCADE"),
        CheckConstraint(
            "length(actor_id) > 0 AND length(notification_id) > 0",
            name="ck_notification_read_identity",
        ),
    )
    validate_notification_inbox_schema(connection)


def downgrade():
    connection = _connection()
    if not validate_notification_inbox_schema(connection):
        raise RuntimeError("Personal notification read family is absent")
    result = connection.execute(text("SELECT 1 FROM notification_read_states LIMIT 1"))
    try:
        has_evidence = result.first() is not None
    finally:
        result.close()
    if has_evidence:
        raise RuntimeError(
            "Downgrade would erase personal notification read evidence; "
            "retain a compatible full recovery"
        )
    op.drop_table(TABLE)
