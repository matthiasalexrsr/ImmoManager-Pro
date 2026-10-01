"""Complete the migrated user schema with persistent TOTP state.

Revision ID: i1a2b3c4d5e6
Revises: h1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "i1a2b3c4d5e6"
down_revision = "h1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Local SQLite installations may already have these columns from their
    # additive compatibility upgrade. Preserve those credentials/settings.
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "totp_secret" not in columns:
        op.add_column("users", sa.Column("totp_secret", sa.Text(), nullable=True))
    if "totp_enabled" not in columns:
        op.add_column("users", sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
