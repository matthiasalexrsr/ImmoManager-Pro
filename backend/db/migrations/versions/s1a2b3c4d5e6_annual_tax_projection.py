"""Immutable reviewed cash classifications and annual source snapshots.

Revision ID: s1a2b3c4d5e6
Revises: r1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "s1a2b3c4d5e6"
down_revision = "r1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("annual_tax_profiles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("previous_version_id", sa.String(), sa.ForeignKey("annual_tax_profiles.id", ondelete="RESTRICT")),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("actor_id", sa.String(), nullable=False), sa.Column("spec_json", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("idx_tax_profiles_portfolio_year", "annual_tax_profiles", ["portfolio_id", "tax_year", "created_at", "id"])
    op.create_table("annual_tax_projections",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("profile_version_id", sa.String(), sa.ForeignKey("annual_tax_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("previous_projection_id", sa.String(), sa.ForeignKey("annual_tax_projections.id", ondelete="RESTRICT"), unique=True),
        sa.Column("annual_root_key", sa.String(), unique=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("actor_id", sa.String(), nullable=False), sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False), sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("idx_tax_projections_portfolio_year", "annual_tax_projections", ["portfolio_id", "tax_year", "created_at", "id"])
    op.create_table("annual_tax_sources",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("portfolio_id", sa.String(), sa.ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("projection_id", sa.String(), sa.ForeignKey("annual_tax_projections.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("booking_id", sa.String(), nullable=False), sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("source_json", sa.Text(), nullable=False), sa.Column("sha256", sa.String(64), nullable=False))
    op.create_index("idx_tax_sources_projection_sequence", "annual_tax_sources", ["projection_id", "sequence_number"], unique=True)


def downgrade():
    connection = op.get_bind()
    # Guard the entire revision BEFORE the first index/table mutation.
    for name in ("annual_tax_sources", "annual_tax_projections", "annual_tax_profiles"):
        if connection.execute(sa.text(f"SELECT 1 FROM {name} LIMIT 1")).first():
            raise RuntimeError("Annual tax downgrade would erase review/source evidence. Restore a verified complete backup instead.")
    for name in ("annual_tax_sources", "annual_tax_projections", "annual_tax_profiles"):
        op.drop_table(name)
