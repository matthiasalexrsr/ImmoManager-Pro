"""Upgrade either existing October branch without losing data or revision identity."""

from datetime import date

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

import backend.models  # noqa: F401
from backend.db.orm_models import AccountORM, BookingORM, ContractORM, PortfolioORM, PropertyORM, TenantORM, UnitORM
from backend.db.schema_state import SchemaUpgradeRequired, alembic_config, ensure_current

DATE_INDEX = "7a2c8e4f1b90"
TAKEOVER = "981b2631e1e8"
MERGE = "d2e6c8a4f019"


def _exercise_existing_branch(engine, config, revision):
    assert ScriptDirectory.from_config(config).get_heads() == [MERGE]
    command.upgrade(config, revision)
    with engine.begin() as connection:
        connection.execute(sa.insert(PortfolioORM), {"id": "pf", "name": "Existing portfolio"})
        connection.execute(sa.insert(PropertyORM), {"id": "p", "portfolio_id": "pf", "name": "Existing property",
                                                    "property_type": "residential"})
        connection.execute(sa.insert(UnitORM), {"id": "u", "property_id": "p", "label": "Existing unit", "unit_type": "flat"})
        connection.execute(sa.insert(TenantORM), {"id": "t", "full_name": "Existing tenant"})
        connection.execute(sa.insert(ContractORM), {"id": "c", "contract_number": "Existing contract", "property_id": "p",
                                                   "unit_id": "u", "tenant_id": "t", "start_date": date(2020, 1, 1)})
        connection.execute(sa.insert(AccountORM), {"id": "a", "portfolio_id": "pf", "name": "Bank", "account_type": "bank"})
        connection.execute(sa.insert(BookingORM), {"id": "b", "account_id": "a", "booking_date": date(2026, 1, 2), "amount": 123.45})
        if revision == TAKEOVER:
            connection.execute(sa.update(ContractORM).where(ContractORM.id == "c").values(
                ledger_start=date(2026, 1, 1), carried_balance=-250.5))
    with pytest.raises(SchemaUpgradeRequired):
        ensure_current(engine)
    command.upgrade(config, "head")
    engine.dispose()
    ensure_current(engine)
    assert {"ledger_start", "carried_balance"} <= {c["name"] for c in sa.inspect(engine).get_columns("contracts")}
    assert "idx_bookings_date" in {i["name"] for i in sa.inspect(engine).get_indexes("bookings")}
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == MERGE
        assert connection.execute(sa.select(BookingORM.id, BookingORM.amount)).one() == ("b", 123.45)
        assert connection.execute(sa.select(ContractORM.id, ContractORM.ledger_start, ContractORM.carried_balance)).one() == (
            "c", date(2026, 1, 1) if revision == TAKEOVER else None, -250.5 if revision == TAKEOVER else None)


@pytest.mark.parametrize("revision", [DATE_INDEX, TAKEOVER])
def test_sqlite_upgrades_either_existing_branch(tmp_path, monkeypatch, revision):
    url = f"sqlite:///{(tmp_path / 'branch.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    engine = sa.create_engine(url)
    try:
        _exercise_existing_branch(engine, alembic_config(url), revision)
    finally:
        engine.dispose()
