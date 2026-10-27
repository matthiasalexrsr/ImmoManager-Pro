"""Personal assistant conversations, runs, attachments and reviewed proposals."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.schema import SchemaItem

revision = "f019a1b2c001"
down_revision = "f018a1b2c001"
branch_labels = None
depends_on = None

NAMES = ("assistant_conversations", "assistant_messages", "assistant_runs", "assistant_attachments", "assistant_proposals")


def tables():
    metadata = sa.MetaData()
    sa.Table("users", metadata, sa.Column("id", sa.String(36), primary_key=True))
    result = []
    for name in NAMES:
        columns: list[SchemaItem] = [sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False), sa.Column("state", sa.String(24), nullable=False),
            sa.Column("payload_token", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False)]
        if name != NAMES[0]:
            columns.append(sa.Column("conversation_id", sa.String(36),
                sa.ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False))
        result.append(sa.Table(name, metadata, *columns))
    sa.Index("ix_assistant_conversation_owner", result[0].c.owner_id, result[0].c.created_at, result[0].c.id)
    for table, label in zip(result[1:], ("message_page", "run_page", "attachment_owner", "proposal_owner")):
        sa.Index("ix_assistant_" + label, table.c.owner_id, table.c.conversation_id, table.c.created_at, table.c.id)
    sa.Index("ix_assistant_run_work", result[2].c.state, result[2].c.updated_at, result[2].c.id)
    return result


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing = [name for name in NAMES if inspector.has_table(name)]
    if existing and len(existing) != len(NAMES):
        raise RuntimeError("Partial assistant schema; verify private records before upgrading")
    for table in tables():
        if existing:
            columns = {column["name"]: column for column in inspector.get_columns(table.name)}
            if set(columns) != set(table.c.keys()) or any(
                    columns[c.name]["type"].compile(dialect=connection.dialect).upper() != c.type.compile(dialect=connection.dialect).upper()
                    or bool(columns[c.name]["nullable"]) != bool(c.nullable) for c in table.c):
                raise RuntimeError("Assistant table mismatch: " + table.name)
            indexes = {item["name"]: item for item in inspector.get_indexes(table.name)}
            if any(index.name not in indexes or indexes[index.name]["column_names"] != [c.name for c in index.columns]
                   for index in table.indexes):
                raise RuntimeError("Assistant index mismatch: " + table.name)
        else:
            table.create(connection)


def downgrade():
    from backend.db.migrations.retained import require_empty
    connection = op.get_bind()
    require_empty(connection, NAMES, "Private assistant history must not be discarded; restore a verified pre-upgrade full backup")
    for name in reversed(NAMES):
        op.drop_table(name)
