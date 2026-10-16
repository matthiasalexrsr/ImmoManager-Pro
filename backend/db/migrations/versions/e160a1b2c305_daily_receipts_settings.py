"""Personal notification receipts and settings command audit.

Revision ID: e160a1b2c305
Revises: d73f2b9a041c
Legacy shared status/read_at is retained verbatim. No historical reader or time
is inferred: every account starts unread until it explicitly acknowledges.
"""
import sqlalchemy as sa
from alembic import op

revision = "e160a1b2c305"
down_revision = "d73f2b9a041c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("daily_user_state",
        sa.Column("owner_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("key", sa.String(240), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("daily_commands",
        sa.Column("owner_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("key", sa.String(120), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))

    op.create_table("daily_setting_rules",
        sa.Column("scope", sa.String(160), primary_key=True),
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))


def downgrade():
    raise RuntimeError("Persönliche Historie bleibt erhalten; kein automatischer Downgrade.")
