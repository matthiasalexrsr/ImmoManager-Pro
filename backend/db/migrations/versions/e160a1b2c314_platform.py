"""Cross-worker registration quota. Additive; no business rows are changed.

Revision ID: e160a1b2c314
Revises: d73f2b9a041c
"""

import sqlalchemy as sa
from alembic import op

revision = "e160a1b2c314"
down_revision = "d73f2b9a041c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "storage_bindings",
        sa.Column("storage_key", sa.Text(), primary_key=True),
        sa.Column("bucket", sa.String(200), nullable=False),
        sa.Column("endpoint_hash", sa.String(64), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "registration_quotas",
        sa.Column("key_hash", sa.String(64), primary_key=True),
        sa.Column("attempts", sa.JSON(), nullable=False),
    )
    op.create_table(
        "plugin_installations",
        sa.Column("name", sa.String(80), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("backups", sa.JSON(), nullable=False),
        sa.Column("commands", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("storage_bindings")
    op.drop_table("plugin_installations")
    op.drop_table("registration_quotas")
