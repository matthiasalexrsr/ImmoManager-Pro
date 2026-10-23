"""Heating costs are split by consumption and by a key for the fixed costs.

R12-07: HeizkostenV § 7 and § 8 want 50 to 70 % of heating and hot water costs shared by
consumption and the rest by area (or another key for fixed costs). A cost item now holds that
share (``consumption_share``) and the key of the fixed costs (``fixed_key_id``); the statement
splits it into the two parts.

Guarded like a7d3c5e9f2b1, so create_all databases that already have the columns pass. A
downgrade is refused while a cost item uses them: the statements would silently change. The
columns are dropped without a table copy (SQLite >= 3.35).

Revision ID: b8f0a2c4d6e7
Revises: a6d8f0b2c4e5
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.db.migrations.retained import guard_branch_downgrade

revision: str = "b8f0a2c4d6e7"
down_revision: str | None = "a6d8f0b2c4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns("cost_items")}


def upgrade() -> None:
    existing = _columns(op.get_bind())
    if "consumption_share" not in existing:
        op.add_column("cost_items", sa.Column("consumption_share", sa.Numeric(5, 2, asdecimal=False), nullable=True))
    if "fixed_key_id" not in existing:
        op.add_column("cost_items", sa.Column("fixed_key_id", sa.String(36), nullable=True))


def downgrade() -> None:
    guard_branch_downgrade()
    bind = op.get_bind()
    existing = _columns(bind)
    names = [name for name in ("consumption_share", "fixed_key_id") if name in existing]
    if not names:
        return
    used = " OR ".join(f"{name} IS NOT NULL" for name in names)
    if bind.execute(sa.text(f"SELECT 1 FROM cost_items WHERE {used} LIMIT 1")).first():
        raise RuntimeError("Downgrade would discard the consumption shares of heating costs; keep this version or "
                           "remove the shares first.")
    for name in names:
        op.drop_column("cost_items", name)
