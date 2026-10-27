"""Index tenant-account booking reads without changing existing data.

Revision ID: 8c4d2e6f1a93
Revises: 6e2f8a4c9b71
Create Date: 2026-10-07
"""

import sqlalchemy as sa
from alembic import op

revision = "8c4d2e6f1a93"
down_revision = "6e2f8a4c9b71"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "idx_bookings_tenant" not in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("bookings")}:
        op.create_index("idx_bookings_tenant", "bookings", ["tenant_id"])


def downgrade() -> None:
    if "idx_bookings_tenant" in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("bookings")}:
        op.drop_index("idx_bookings_tenant", table_name="bookings")
