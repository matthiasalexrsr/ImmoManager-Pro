"""Receivables can be marked as claims of their own ("other": damage, keys, …).

R12-15: the period result left receivables entered by hand out, because one may repeat a
monthly rent. A receivable of kind "other" now counts there as income on its due date.

Guarded like a7d3c5e9f2b1, so create_all databases that already have the column pass. A
downgrade is refused while a receivable is marked: the period result would silently change.

Revision ID: f5c7e9a1b3d4
Revises: e4b6d8f0a2c3
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.db.migrations.retained import guard_branch_downgrade

revision: str = "f5c7e9a1b3d4"
down_revision: str | None = "e4b6d8f0a2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns("receivables")}


def upgrade() -> None:
    if "kind" not in _columns(op.get_bind()):
        op.add_column("receivables", sa.Column("kind", sa.String(20), nullable=True))


def downgrade() -> None:
    guard_branch_downgrade()
    bind = op.get_bind()
    if "kind" not in _columns(bind):
        return
    if bind.execute(sa.text("SELECT 1 FROM receivables WHERE kind IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Downgrade would discard the kind of receivables marked as other claims; keep this "
                           "version or remove the marks first.")
    with op.batch_alter_table("receivables") as batch:
        batch.drop_column("kind")
