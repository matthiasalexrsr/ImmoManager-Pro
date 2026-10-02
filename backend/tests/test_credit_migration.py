"""Frozen n1 schema, real Alembic chain and preservation of populated snapshots."""

from importlib import import_module

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import credit_ledger as service
from backend.services.invoice_payment_schema import ensure_invoice_payment_columns
from backend.tests.test_bank_payments import bank_booking
from backend.tests.test_credit_ledger import credit_scenario, payout

migration = import_module("backend.db.migrations.versions.n1a2b3c4d5e6_credit_receipt_journal")


def migrate(tmp_path, monkeypatch):
    path = tmp_path / 'credit-migrated.db'
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "m1a2b3c4d5e6")
    return config, create_engine(f"sqlite:///{path}")


def current_orm_read_compatibility(engine):
    """Run the additive startup helper before current ORM reads of m1 data.

    The historical two-target constraint remains unchanged; this deliberately
    does not stamp or upgrade the financial schema to w1.
    """
    with engine.begin() as connection:
        before = inspect(connection).get_check_constraints("payments")
        ensure_invoice_payment_columns(connection)
        assert inspect(connection).get_check_constraints("payments") == before
        assert all("invoice_id" not in check["sqltext"] for check in before)


def test_fresh_chain_and_empty_down_up_support_negative_allocations(tmp_path, monkeypatch):
    config, engine = migrate(tmp_path, monkeypatch)
    with engine.begin() as connection:
        connection.execute(text("CREATE TRIGGER synthetic_bookings_history BEFORE DELETE ON bookings BEGIN SELECT 1; END"))
    command.upgrade(config, "n1a2b3c4d5e6")
    with engine.connect() as connection:
        assert {"credit_receipts", "credit_reversals"} <= set(inspect(connection).get_table_names())
        assert "abs(amount)" in inspect(connection).get_check_constraints("bookings")[-1]["sqltext"] or any(
            "abs(amount)" in row["sqltext"] for row in inspect(connection).get_check_constraints("bookings"))
        assert connection.execute(text("SELECT sql FROM sqlite_master WHERE name='synthetic_bookings_history'")).scalar()
    command.downgrade(config, "m1a2b3c4d5e6")
    command.upgrade(config, "head")
    with Session(engine) as db:
        active = SQLAlchemyStore(db)
        source, contract, _, _ = credit_scenario(active, monkeypatch)
        receipt = service.create_receipt(active, payout(source, "100"))
        assert receipt.amount == 100
        assert service.summary(active, contract.id)["available_amount"] == "0.00"
    engine.dispose()


def test_populated_credit_history_refuses_downgrade_before_any_ddl(tmp_path, monkeypatch):
    config, engine = migrate(tmp_path, monkeypatch)
    command.upgrade(config, "head")
    with Session(engine) as db:
        active = SQLAlchemyStore(db)
        source, _, _, _ = credit_scenario(active, monkeypatch)
        receipt = service.create_receipt(active, payout(source))
    with engine.connect() as connection:
        before = connection.execute(text("SELECT name, sql FROM sqlite_master ORDER BY name")).all()
    with pytest.raises(RuntimeError, match="history exists"):
        command.downgrade(config, "m1a2b3c4d5e6")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT name, sql FROM sqlite_master ORDER BY name")).all() == before
        assert connection.execute(text("SELECT id, amount_cents FROM credit_receipts")).one() == (receipt.id, "6000")
    engine.dispose()


def test_online_sqlite_connection_refuses_rebuild_before_mutation(tmp_path, monkeypatch):
    _, engine = migrate(tmp_path, monkeypatch)
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        before = connection.execute(text("SELECT name, sql FROM sqlite_master ORDER BY name")).all()
        with Operations.context(MigrationContext.configure(connection)), pytest.raises(RuntimeError, match="offline SQLite"):
            migration.upgrade()
        assert connection.execute(text("SELECT name, sql FROM sqlite_master ORDER BY name")).all() == before
    engine.dispose()


def test_upgrade_preserves_existing_linked_bank_receipts_and_posted_billing(tmp_path, monkeypatch):
    from datetime import date

    from backend.models import ReceivableCreate
    from backend.services.payments import PaymentCreate
    config, engine = migrate(tmp_path, monkeypatch)
    current_orm_read_compatibility(engine)
    with Session(engine) as db:
        active = SQLAlchemyStore(db)
        source, contract, _, charge = credit_scenario(active, monkeypatch)
        target = active.create_receivable(ReceivableCreate(contract_id=contract.id, due_date=date(2026, 9, 5), amount_due=40))
        original_bank = bank_booking(active, charge, 40)
        original = active.record_payment("receivable", target.id, PaymentCreate(idempotency_key="legacy-bank",
            amount="40", payment_date=original_bank.booking_date, booking_id=original_bank.id))
        negative_bank = bank_booking(active, charge, -80)
    command.upgrade(config, "n1a2b3c4d5e6")
    with Session(engine) as db:
        active = SQLAlchemyStore(db)
        assert active.list_payments("receivable", target.id)[0].id == original.id
        assert active.get_booking(original_bank.id).allocated_amount == 40
        assert active.get_receivable(target.id).amount_paid == 40
        receipt = service.create_receipt(active, payout(source, "60", method="bank", booking_id=negative_bank.id))
        assert receipt.booking_id == negative_bank.id
        assert active.get_booking(negative_bank.id).allocated_amount == 60
        assert db.execute(text("PRAGMA foreign_key_check")).first() is None
    engine.dispose()
