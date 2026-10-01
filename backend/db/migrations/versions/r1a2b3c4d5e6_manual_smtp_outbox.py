"""Durable manually reviewed SMTP outbox and immutable attempt evidence.

Revision ID: r1a2b3c4d5e6
Revises: q1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "r1a2b3c4d5e6"
down_revision = "q1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    def portfolio():
        return sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False)
    def identity():
        return sa.Column("id", sa.String(), primary_key=True)
    def message():
        return sa.Column("message_id", sa.String(), sa.ForeignKey("outbox_messages.id", ondelete="RESTRICT"), nullable=False)
    op.create_table("outbox_messages", identity(), portfolio(),
        sa.Column("idempotency_key", sa.String(200), unique=True, nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("message_id", sa.String(254), unique=True, nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("wire", sa.LargeBinary(), nullable=False),
        sa.Column("wire_sha256", sa.String(64), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("idx_outbox_messages_portfolio", "outbox_messages", ["portfolio_id", "created_at", "id"])
    op.create_table("outbox_events", identity(), portfolio(), message(),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("code", sa.String(100)), sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("message_id", "revision", name="uq_outbox_event_revision"))
    op.create_index("idx_outbox_events_message", "outbox_events", ["message_id", "revision"])
    op.create_index("idx_outbox_events_portfolio", "outbox_events", ["portfolio_id", "id"])
    op.create_table("outbox_commands", identity(), portfolio(), message(),
        sa.Column("idempotency_key", sa.String(200), unique=True, nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text()), sa.Column("claim_token", sa.String()),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("idx_outbox_commands_message", "outbox_commands", ["message_id", "created_at", "id"])


def downgrade():
    connection = op.get_bind()
    if any(connection.scalar(sa.text(f"SELECT count(*) FROM {name}"))
            for name in ("outbox_messages", "outbox_events", "outbox_commands")):
        raise RuntimeError("Outbox snapshots/attempt evidence exist; downgrade would erase communication history")
    for name in ("outbox_commands", "outbox_events", "outbox_messages"):
        op.drop_table(name)
