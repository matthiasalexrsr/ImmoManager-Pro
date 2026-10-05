"""Payments credited to contracts.

Bookings have no contract: the rent account credited every payment of a
tenant to each of the tenant's contracts, so a tenant with flat and garage
paid everything twice. Allocations record which contract a booking pays,
also split across several. Existing bookings are allocated when the app
starts (backend.services.payment_allocations.allocate_unassigned).

Revision ID: a1d6c3f8e2b4
Revises: 7b3e9d2c5a18
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1d6c3f8e2b4"
down_revision: str | None = "7b3e9d2c5a18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "payment_allocations" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "payment_allocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("booking_id", sa.String(36), sa.ForeignKey("bookings.id"), nullable=False),
        sa.Column("contract_id", sa.String(36), sa.ForeignKey("contracts.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("source", sa.String(10), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_payment_allocations_booking_id", "payment_allocations", ["booking_id"])
    op.create_index("ix_payment_allocations_contract_id", "payment_allocations", ["contract_id"])


def downgrade() -> None:
    op.drop_index("ix_payment_allocations_contract_id", table_name="payment_allocations")
    op.drop_index("ix_payment_allocations_booking_id", table_name="payment_allocations")
    op.drop_table("payment_allocations")
