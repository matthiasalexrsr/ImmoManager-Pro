"""Seek internal messages by thread, time and stable ID without full materialization.

Revision ID: c61e9a2f034b
Revises: b82d5fa03147
"""

import sqlalchemy as sa
from alembic import op

revision = "c61e9a2f034b"
down_revision = "b82d5fa03147"
branch_labels = None
depends_on = None


def upgrade():
    indexes = {item["name"]: item for item in sa.inspect(op.get_bind()).get_indexes("messages")}
    name = "ix_messages_thread_sent_id"
    columns = ["thread_id", "sent_at", "id"]
    if name in indexes:
        if indexes[name]["column_names"] != columns or indexes[name]["unique"]:
            raise RuntimeError("Existing message page index has an incompatible definition")
    else:
        op.create_index(name, "messages", columns)


def downgrade():
    op.drop_index("ix_messages_thread_sent_id", table_name="messages")
