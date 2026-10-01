"""Protect monthly rental obligations without discarding existing duplicates.

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
"""

from alembic import op

revision = "f0a1b2c3d4e5"
down_revision = "e9f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from backend.services.rent_ledger import ensure_unique_month_schema
    ensure_unique_month_schema(op.get_bind())


def downgrade() -> None:
    op.drop_index("uq_rent_charges_contract_month", table_name="rent_charges")
