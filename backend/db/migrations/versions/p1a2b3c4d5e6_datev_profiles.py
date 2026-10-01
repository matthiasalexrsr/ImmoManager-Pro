"""Immutable reviewed DATEV profiles and reproducible export references.

Revision ID: p1a2b3c4d5e6
Revises: o1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "p1a2b3c4d5e6"
down_revision = "o1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("datev_profiles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("previous_version_id", sa.String(), sa.ForeignKey("datev_profiles.id", ondelete="RESTRICT")),
        sa.Column("idempotency_key", sa.String(200), unique=True, nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("spec_json", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("idx_datev_profiles_portfolio", "datev_profiles", ["portfolio_id", "created_at", "id"])
    op.create_table("datev_exports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("profile_version_id", sa.String(), sa.ForeignKey("datev_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("idempotency_key", sa.String(200), unique=True, nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("idx_datev_exports_portfolio", "datev_exports", ["portfolio_id", "created_at", "id"])


def downgrade():
    connection = op.get_bind()
    if any(connection.scalar(sa.text(f"SELECT count(*) FROM {name}"))
           for name in ("datev_profiles", "datev_exports")):
        raise RuntimeError("DATEV mapping versions/export history exist; downgrade would erase audit evidence")
    op.drop_table("datev_exports")
    op.drop_table("datev_profiles")
