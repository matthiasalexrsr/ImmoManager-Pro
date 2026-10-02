"""Durable refresh families with consumed-token replay detection.

Revision ID: t1a2b3c4d5e6
Revises: s1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "t1a2b3c4d5e6"
down_revision = "s1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("device_label", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime()),
        sa.Column("revoke_reason", sa.String(32)),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("current_refresh_hash", sa.String(64), nullable=False),
        sa.Column("legacy_refresh_hash", sa.String(64), unique=True))
    op.create_index("idx_auth_sessions_user_created", "auth_sessions", ["user_id", "created_at", "id"])
    op.create_table("auth_refresh_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime()),
        sa.UniqueConstraint("session_id", "generation", name="uq_auth_refresh_generation"))
    op.create_index("idx_auth_refresh_session", "auth_refresh_tokens", ["session_id"])


def downgrade():
    connection = op.get_bind()
    for name in ("auth_sessions", "auth_refresh_tokens"):
        if connection.scalar(sa.text(f"SELECT 1 FROM {name} LIMIT 1")) is not None:
            raise RuntimeError("Session downgrade would remove replay/revocation protection; retain database or use full offline recovery")
    op.drop_table("auth_refresh_tokens")
    op.drop_table("auth_sessions")
