"""An account's owner, and what an owner change did so that it can be undone.

``accounts.owner_contact_id``: an account held by one owner alone; its opening balance is that
owner's (services/finance_ledger.opening_accounts). ``ownership_transfers.changes`` records the
shares an owner change ended, removed and created (services/ownership.record_transfer), so that
the latest change can be reverted; ``reverted_at``/``reverted_by`` mark a reverted one. Guarded
like c9a1b3d5e7f9; a downgrade is refused while an account has an owner or a change was reverted.

Revision ID: e1a3c5e7f9b2
Revises: d0b2c4e6f8a1
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.db.migrations.retained import guard_branch_downgrade

revision: str = "e1a3c5e7f9b2"
down_revision: str | None = "d0b2c4e6f8a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRANSFER_COLUMNS = (("changes", sa.JSON()), ("reverted_at", sa.DateTime(timezone=True)), ("reverted_by", sa.String()))


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "owner_contact_id" not in _columns(inspector, "accounts"):
        op.add_column("accounts", sa.Column("owner_contact_id", sa.String(36), nullable=True))
    present = _columns(inspector, "ownership_transfers")
    for name, kind in TRANSFER_COLUMNS:
        if name not in present:
            op.add_column("ownership_transfers", sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    guard_branch_downgrade()
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    accounts = _columns(inspector, "accounts")
    transfers = _columns(inspector, "ownership_transfers")
    if "owner_contact_id" in accounts and bind.execute(
            sa.text("SELECT 1 FROM accounts WHERE owner_contact_id IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Downgrade would discard the owners of accounts; keep this version or remove them first.")
    if "reverted_at" in transfers and bind.execute(
            sa.text("SELECT 1 FROM ownership_transfers WHERE reverted_at IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Downgrade would show reverted owner changes as valid; keep this version.")
    if "owner_contact_id" in accounts:
        op.drop_column("accounts", "owner_contact_id")
    for name, _kind in reversed(TRANSFER_COLUMNS):
        if name in transfers:
            op.drop_column("ownership_transfers", name)
