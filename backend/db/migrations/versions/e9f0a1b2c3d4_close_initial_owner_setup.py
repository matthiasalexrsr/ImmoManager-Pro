"""Persist the singleton initial-owner setup guard.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
"""

import sqlalchemy as sa
from alembic import op

revision = "e9f0a1b2c3d4"
down_revision = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_setup",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("completed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_auth_setup_singleton"),
    )
    op.execute("INSERT INTO auth_setup (id) SELECT 1 WHERE EXISTS (SELECT 1 FROM users)")


def downgrade() -> None:
    op.drop_table("auth_setup")
