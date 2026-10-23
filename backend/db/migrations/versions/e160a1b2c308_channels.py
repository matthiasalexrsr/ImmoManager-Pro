"""Frozen channel cases, encrypted original blocks and signed webhook receipts.

Revision ID: e160a1b2c308
Revises: d73f2b9a041c
"""

import sqlalchemy as sa
from alembic import op

revision = "e160a1b2c308"
down_revision = "d73f2b9a041c"
branch_labels = None
depends_on = None


def _table(name, *columns):
    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *columns)


def _index(name, table, columns):
    if name not in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}:
        op.create_index(name, table, columns)


def upgrade():
    _table(
        "channel_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("entity_id", sa.String(120), nullable=False),
        sa.Column("source_kind", sa.String(30), nullable=False),
        sa.Column("source_id", sa.String(120), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot_token", sa.Text(), nullable=False),
        sa.Column("progress_token", sa.Text(), nullable=False),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("integration_connections.id", ondelete="RESTRICT")),
        sa.Column("connection_revision", sa.Integer()),
        sa.Column("external_id", sa.String(200)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("source_kind = entity_type AND source_id = entity_id", name="ck_channel_source_binding"),
    )
    _index("ix_channel_source", "channel_cases", ["source_kind", "source_id", "id"])
    _table(
        "channel_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("channel_cases.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("data_token", sa.Text(), nullable=False),
        sa.UniqueConstraint("case_id", "name", "sequence", name="uq_channel_evidence_block"),
    )
    _table(
        "channel_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("channel_cases.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("replay_hash", sa.String(64), nullable=False),
        sa.Column("data_token", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("case_id", "replay_hash", name="uq_channel_event_replay"),
    )
    _index("ix_channel_event_page", "channel_events", ["case_id", "id"])
    _table(
        "channel_webhooks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("integration_connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("raw_token", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("connection_id", "sha256", name="uq_channel_webhook_replay"),
    )
    _index("ix_channel_webhook_page", "channel_webhooks", ["connection_id", "id"])


def downgrade():
    from backend.db.migrations.retained import require_empty
    names = require_empty(op.get_bind(), ('channel_webhooks', 'channel_events', 'channel_evidence', 'channel_cases'),
                          'Kanalbelege erhalten: Downgrade erfordert einen separat geprüften Export-/Aufbewahrungsplan.')
    for name in names:
        op.drop_table(name)
