"""The journal of owner changes (sale, gift, inheritance, division).

New table ``ownership_transfers``: on a day an owner passes a part of their share of a property
or unit to other owners (services/ownership.record_transfer). The shares carry the result for
every calculation; the journal keeps what happened. Guarded like c9a1b3d5e7f9; a downgrade is
refused while the journal holds a change.

Revision ID: d0b2c4e6f8a1
Revises: c9a1b3d5e7f9
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.db.migrations.retained import guard_branch_downgrade

revision: str = "d0b2c4e6f8a1"
down_revision: str | None = "c9a1b3d5e7f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("ownership_transfers"):
        op.create_table(
            "ownership_transfers",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id"), nullable=False),
            sa.Column("unit_id", sa.String(), sa.ForeignKey("units.id"), nullable=True),
            sa.Column("scope", sa.String(10), nullable=False),
            sa.Column("effective_date", sa.Date(), nullable=False),
            sa.Column("from_owner_contact_id", sa.String(36), sa.ForeignKey("contacts.id"), nullable=False),
            sa.Column("fraction_percent", sa.Numeric(7, 4, asdecimal=False), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("receivers", sa.JSON(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("actor_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("idx_ownership_transfers_property", "ownership_transfers", ["property_id", "effective_date"])


def downgrade() -> None:
    guard_branch_downgrade()
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("ownership_transfers"):
        return
    if bind.execute(sa.text("SELECT 1 FROM ownership_transfers LIMIT 1")).first():
        raise RuntimeError("Downgrade would discard the journal of owner changes; keep this version.")
    op.drop_index("idx_ownership_transfers_property", table_name="ownership_transfers")
    op.drop_table("ownership_transfers")
