"""Owners of a property or a unit, and the owner a single booking belongs to.

New table ``ownership_shares``: an owner (a contact of type "owner") holds a share of a property
or of one of its units for a period (services/ownership.py). Bookings get ``owner_contact_id``
for money that belongs to one owner alone, such as a withdrawal. Guarded like b8f0a2c4d6e7, so
create_all databases that already have the table and column pass. A downgrade is refused while a
share or a booking's owner exists: every report by owner would silently change.

Revision ID: c9a1b3d5e7f9
Revises: b8f0a2c4d6e7
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.db.migrations.retained import guard_branch_downgrade

revision: str = "c9a1b3d5e7f9"
down_revision: str | None = "b8f0a2c4d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("ownership_shares"):
        op.create_table(
            "ownership_shares",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("owner_contact_id", sa.String(36), sa.ForeignKey("contacts.id"), nullable=False),
            sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id"), nullable=False),
            sa.Column("unit_id", sa.String(), sa.ForeignKey("units.id"), nullable=True),
            sa.Column("share_percent", sa.Numeric(7, 4, asdecimal=False), nullable=False),
            sa.Column("valid_from", sa.Date(), nullable=True),
            sa.Column("valid_to", sa.Date(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("share_percent > 0 AND share_percent <= 100", name="ck_ownership_share_percent"),
        )
        op.create_index("idx_ownership_shares_property", "ownership_shares", ["property_id"])
        op.create_index("idx_ownership_shares_owner", "ownership_shares", ["owner_contact_id"])
    if "owner_contact_id" not in {column["name"] for column in inspector.get_columns("bookings")}:
        op.add_column("bookings", sa.Column("owner_contact_id", sa.String(36), nullable=True))


def downgrade() -> None:
    guard_branch_downgrade()
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    has_table = inspector.has_table("ownership_shares")
    has_column = "owner_contact_id" in {column["name"] for column in inspector.get_columns("bookings")}
    if has_table and bind.execute(sa.text("SELECT 1 FROM ownership_shares LIMIT 1")).first():
        raise RuntimeError("Downgrade would discard the owners' shares of properties and units; keep this version "
                           "or remove the shares first.")
    if has_column and bind.execute(sa.text("SELECT 1 FROM bookings WHERE owner_contact_id IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Downgrade would discard the owner bookings belong to; keep this version or remove "
                           "the owners from the bookings first.")
    if has_column:
        op.drop_column("bookings", "owner_contact_id")
    if has_table:
        op.drop_index("idx_ownership_shares_owner", table_name="ownership_shares")
        op.drop_index("idx_ownership_shares_property", table_name="ownership_shares")
        op.drop_table("ownership_shares")
