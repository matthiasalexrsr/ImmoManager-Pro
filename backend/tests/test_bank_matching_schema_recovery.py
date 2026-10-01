"""Actual offline upgrade, retained triggers and source-gone full recovery."""
import os
import shutil
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from backend.db.orm_models import InvoiceORM, PaymentORM
from backend.models import BookingCreate, InvoiceCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import full_recovery
from backend.services.invoice_payment_schema import ensure_invoice_payment_columns, ensure_invoice_payment_immutability
from backend.services.payments import PaymentCreate, PaymentReversalCreate
from backend.tests.test_bank_matching import setup
from backend.tests.test_full_recovery import PASSPHRASE, plan, runtime_template  # noqa: F401 fixture

ROOT = Path(__file__).resolve().parents[2]


def migrate(url, action, revision):
    return subprocess.run([sys.executable, "-m", "alembic", action, revision], cwd=ROOT,
        env={**os.environ, "DATABASE_URL": url, "PYTHONUTF8": "1"}, capture_output=True, text=True, timeout=90)


def test_w1_upgrade_retains_legacy_receipt_balances_and_every_sentinel_trigger(tmp_path):
    url = "sqlite:///" + (tmp_path / "legacy-bank.db").as_posix()
    result = migrate(url, "upgrade", "v1a2b3c4d5e6")
    assert result.returncode == 0, result.stderr
    engine = create_engine(url)
    with engine.begin() as connection:
        ensure_invoice_payment_columns(connection)
        ensure_invoice_payment_immutability(connection)
    with Session(engine) as session:
        store = SQLAlchemyStore(session)
        target, booking = setup(store)
        receipt = store.record_payment("rent_charge", target.id, PaymentCreate(idempotency_key=str(uuid4()),
            amount="40.10", booking_id=booking.id, payment_date=booking.booking_date))
        store.reverse_payment("rent_charge", target.id, receipt.id, PaymentReversalCreate(idempotency_key=str(uuid4()),
            reversal_date=date(2026, 9, 6), reason="Retained historical correction"))
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE migration_sentinel (value INTEGER NOT NULL)")
        connection.exec_driver_sql("INSERT INTO migration_sentinel VALUES (0)")
        connection.exec_driver_sql("""CREATE TRIGGER sentinel_account_change BEFORE UPDATE ON accounts
            BEGIN UPDATE migration_sentinel SET value=value+1; END""")
        connection.exec_driver_sql("""CREATE TRIGGER sentinel_receipt_parent BEFORE DELETE ON rent_charges
            WHEN EXISTS(SELECT 1 FROM payments WHERE rent_charge_id=OLD.id)
            BEGIN SELECT RAISE(ABORT, 'Retained receipt parent'); END""")
        triggers = dict(connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger'").all())
    engine.dispose()
    result = migrate(url, "upgrade", "w1a2b3c4d5e6")
    assert result.returncode == 0, result.stderr
    engine = create_engine(url)
    with engine.connect() as connection:
        after = dict(connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger'").all())
        assert all(after[name] == sql for name, sql in triggers.items())
        assert connection.exec_driver_sql("SELECT value FROM migration_sentinel").scalar_one() == 0
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").first() is None
    with Session(engine) as session:
        store = SQLAlchemyStore(session)
        history = store.list_payments("rent_charge", target.id)
        assert history[0].id == receipt.id and history[0].reversal.reason == "Retained historical correction"
        contract = store.get_contract(target.contract_id)
        invoice = store.create_invoice(InvoiceCreate(property_id=contract.property_id, supplier="Migration invoice",
            invoice_date=date(2026, 9, 1), net_amount=100.30, gross_amount=100.30, vat_rate=0))
        outgoing = store.create_booking(BookingCreate(account_id=booking.account_id, booking_date=booking.booking_date, amount=-100.30))
        store.record_payment("invoice", invoice.id, PaymentCreate(idempotency_key=str(uuid4()), amount="40.10",
            booking_id=outgoing.id, payment_date=outgoing.booking_date))
    engine.dispose()
    result = migrate(url, "downgrade", "v1a2b3c4d5e6")
    assert result.returncode != 0 and "Invoice payment history exists" in result.stderr
    engine = create_engine(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "w1a2b3c4d5e6"
        assert len(connection.execute(select(PaymentORM.id)).all()) == 2
    engine.dispose()


def test_full_recovery_retains_invoice_receipt_reversal_after_source_tree_is_gone(plan, tmp_path):  # noqa: F811
    engine = create_engine("sqlite:///" + plan.database.as_posix())
    with engine.begin() as connection:
        ensure_invoice_payment_immutability(connection)
    with Session(engine) as session:
        store = SQLAlchemyStore(session)
        contract = store.list_contracts()[0]
        from backend.models import AccountCreate
        account = store.create_account(AccountCreate(portfolio_id=store.get_property(contract.property_id).portfolio_id,
            name="Recovery invoice bank", account_type="bank"))
        invoice = store.create_invoice(InvoiceCreate(property_id=contract.property_id, supplier="Source-gone invoice",
            invoice_date=date(2026, 9, 1), net_amount=100.30, gross_amount=100.30, vat_rate=0))
        booking = store.create_booking(BookingCreate(account_id=account.id, booking_date=date(2026, 9, 5), amount=-100.30))
        receipt = store.record_payment("invoice", invoice.id, PaymentCreate(idempotency_key=str(uuid4()), amount="40.10",
            booking_id=booking.id, payment_date=booking.booking_date))
        reversal = store.reverse_payment("invoice", invoice.id, receipt.id, PaymentReversalCreate(idempotency_key=str(uuid4()),
            reversal_date=date(2026, 9, 6), reason="Recovery correction"))
    engine.dispose()
    archive = tmp_path / "complete-invoice.immobak"
    full_recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    assert plan.database.parent.resolve().is_relative_to(tmp_path.resolve())
    shutil.rmtree(plan.database.parent)
    target = tmp_path / "independent-invoice-recovery"
    result = full_recovery.restore_full_backup(archive, target, PASSPHRASE)
    assert result["existing_installation_changed"] is False
    restored_engine = create_engine("sqlite:///" + (target / "database.sqlite3").as_posix())
    with Session(restored_engine) as session:
        restored = SQLAlchemyStore(session)
        assert restored.get_invoice(invoice.id).amount_paid == 0
        assert restored.get_booking(booking.id).allocated_amount == 0
        proof = restored.list_payments("invoice", invoice.id)[0]
        assert proof.id == receipt.id and proof.reversal.id == reversal.id and proof.amount == receipt.amount
        assert session.scalar(select(InvoiceORM.gross_amount).where(InvoiceORM.id == invoice.id)) == 100.30
    restored_engine.dispose()


def test_offline_upgrade_preserves_explicit_legacy_paid_invoice_and_empty_downgrade(tmp_path):
    url = "sqlite:///" + (tmp_path / "legacy-paid-invoice.db").as_posix()
    assert migrate(url, "upgrade", "v1a2b3c4d5e6").returncode == 0
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql("""INSERT INTO invoices
            (id,supplier,invoice_date,net_amount,vat_amount,gross_amount,vat_rate,status,created_at,updated_at)
            VALUES ('legacy-paid','Synthetic paid invoice','2026-01-01',100.30,0,100.30,0,'paid','2026-01-01','2026-01-01')""")
        connection.exec_driver_sql("CREATE TABLE invoice_migration_sentinel (value INTEGER NOT NULL)")
        connection.exec_driver_sql("INSERT INTO invoice_migration_sentinel VALUES (0)")
        connection.exec_driver_sql("""CREATE TRIGGER independent_invoice_change BEFORE UPDATE ON invoices
            BEGIN UPDATE invoice_migration_sentinel SET value=value+1; END""")
        trigger = connection.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name='independent_invoice_change'").scalar_one()
    engine.dispose()
    upgraded = migrate(url, "upgrade", "w1a2b3c4d5e6")
    assert upgraded.returncode == 0, upgraded.stderr
    engine = create_engine(url)
    with engine.connect() as connection:
        assert Decimal(str(connection.exec_driver_sql("SELECT amount_paid FROM invoices WHERE id='legacy-paid'").scalar_one())) == Decimal("100.30")
        assert not connection.exec_driver_sql("SELECT 1 FROM payments").first()
        assert connection.exec_driver_sql("SELECT value FROM invoice_migration_sentinel").scalar_one() == 0
        assert connection.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name='independent_invoice_change'").scalar_one() == trigger
    engine.dispose()
    downgraded = migrate(url, "downgrade", "v1a2b3c4d5e6")
    assert downgraded.returncode == 0, downgraded.stderr
    engine = create_engine(url)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT status FROM invoices WHERE id='legacy-paid'").scalar_one() == "paid"
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").first() is None
    engine.dispose()
