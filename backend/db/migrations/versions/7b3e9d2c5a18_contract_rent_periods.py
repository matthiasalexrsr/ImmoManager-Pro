"""Rent history per contract.

Rents lived only on the unit, so changing a unit's rent rewrote every month of
every contract, and an applied rent adjustment changed nothing. Each contract
now gets rent periods (valid from a date until the next one starts).

Existing contracts get a first period from their start date with the unit's
current rent and advances; when rent adjustments were applied, the first
period starts at the oldest adjustment's previous rent and every applied
adjustment adds a period from its effective date. Contracts that already have
periods are left alone, so the step can run on databases built by create_all.

Revision ID: 7b3e9d2c5a18
Revises: 4f8a1c6e9b27
Create Date: 2026-10-05
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "7b3e9d2c5a18"
down_revision: str | None = "4f8a1c6e9b27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "contract_rent_periods" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "contract_rent_periods",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("contract_id", sa.String(36), sa.ForeignKey("contracts.id"), nullable=False),
            sa.Column("valid_from", sa.Date(), nullable=False),
            sa.Column("cold_rent", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("service_charge_advance", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("heating_advance", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("rent_adjustment_id", sa.String(36), sa.ForeignKey("rent_adjustments.id"), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("contract_id", "valid_from", name="uq_contract_rent_periods_contract_date"),
        )
        op.create_index("ix_contract_rent_periods_contract_id", "contract_rent_periods", ["contract_id"])
    _backfill(bind)


def _backfill(bind: sa.engine.Connection) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    has_periods = {row[0] for row in bind.execute(sa.text("SELECT DISTINCT contract_id FROM contract_rent_periods"))}
    contracts = bind.execute(sa.text(
        "SELECT c.id, c.start_date, u.cold_rent, u.service_charge_advance, u.heating_advance "
        "FROM contracts c LEFT JOIN units u ON u.id = c.unit_id")).fetchall()
    adjustments: dict[str, list] = {}
    for row in bind.execute(sa.text(
            "SELECT id, contract_id, effective_date, previous_rent, new_rent FROM rent_adjustments "
            "WHERE status = 'applied' ORDER BY effective_date")):
        adjustments.setdefault(row[1], []).append(row)

    insert = sa.text(
        "INSERT INTO contract_rent_periods (id, contract_id, valid_from, cold_rent, service_charge_advance, "
        "heating_advance, source, rent_adjustment_id, created_at, updated_at) "
        "VALUES (:id, :contract_id, :valid_from, :cold, :service, :heating, :source, :adjustment, :now, :now)")
    for contract_id, start, cold, service, heating, *_ in contracts:
        if contract_id in has_periods or start is None:
            continue
        applied = adjustments.get(contract_id, [])
        first_cold = applied[0][3] if applied else cold
        rows = {str(start): (first_cold, "contract_start", None)}
        for adj_id, _, effective, _previous, new_rent in applied:
            rows[str(effective) if str(effective) > str(start) else str(start)] = (new_rent, "adjustment", adj_id)
        for valid_from, (amount, source, adj_id) in rows.items():
            bind.execute(insert, {
                "id": str(uuid.uuid4()), "contract_id": contract_id, "valid_from": valid_from,
                "cold": amount or 0, "service": service or 0, "heating": heating or 0,
                "source": source, "adjustment": adj_id, "now": now})


def downgrade() -> None:
    op.drop_index("ix_contract_rent_periods_contract_id", table_name="contract_rent_periods")
    op.drop_table("contract_rent_periods")
