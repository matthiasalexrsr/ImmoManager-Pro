"""Direct debit details of tenants: the debtor's IBAN, BIC, account holder and mandate date.

New nullable columns on ``tenants`` beside the existing ``sepa_mandate`` (the mandate
reference). Guarded like f4c6e8a0b2d3, so create_all databases that already have the
columns pass. A downgrade is refused while any tenant has one of them; SQLite drops
the columns in place.

Revision ID: a5c7e9b1d3f5
Revises: f4c6e8a0b2d3
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.db.migrations.retained import guard_branch_downgrade

revision: str = "a5c7e9b1d3f5"
down_revision: str | None = "f4c6e8a0b2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (("sepa_iban", sa.String(34)), ("sepa_bic", sa.String(11)), ("sepa_account_holder", sa.Text()),
           ("sepa_mandate_date", sa.Date()))


def _present(inspector) -> set[str]:
    return {column["name"] for column in inspector.get_columns("tenants")}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("tenants"):
        return
    present = _present(inspector)
    for name, kind in COLUMNS:
        if name not in present:
            op.add_column("tenants", sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    guard_branch_downgrade()
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("tenants"):
        return
    present = [name for name, _ in COLUMNS if name in _present(inspector)]
    if not present:
        return
    used = " OR ".join(f"{name} IS NOT NULL" for name in present)
    if bind.execute(sa.text(f"SELECT 1 FROM tenants WHERE {used} LIMIT 1")).first():
        raise RuntimeError("Downgrade would discard the direct debit details (IBAN, account holder, mandate date) "
                           "of tenants; keep this version or remove those details first.")
    for name in present:
        # SQLite drops the column in place; a batch rebuild would also drop the table's triggers
        if bind.dialect.name == "sqlite":
            op.execute(f"ALTER TABLE tenants DROP COLUMN {name}")
        else:
            op.drop_column("tenants", name)
