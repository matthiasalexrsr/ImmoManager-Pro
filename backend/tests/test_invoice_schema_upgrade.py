"""Synthetic unversioned create_all databases: actual DDL, receipts and rollback."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from importlib import import_module

import pytest
from alembic import command, op
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import invoice_schema_upgrade as tool
from backend.db.booking_indexes import BOOKING_INDEXES, ensure_booking_indexes
from backend.db.contract_wizard_models import (
    ContractAttachmentChunkORM,
    ContractAttachmentORM,
    ContractDraftORM,
)
from backend.db.form_draft_models import FormDraftORM
from backend.db.orm_models import Base
from backend.models import AccountCreate, BookingCreate, InvoiceCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import form_draft_crypto
from backend.services.iban_encryption import IBANKeyring, generate_key
from backend.services.invoice_payment_schema import ensure_invoice_payment_columns, ensure_invoice_payment_immutability
from backend.services.payments import FinancialConsistencyError, PaymentCreate, PaymentReversalCreate
from backend.tests.test_credit_migration import migrate
from backend.tests.test_payments import seed


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    """create_all source with known pre-w1 checks, no Alembic stamp anywhere.

    Frozen DDL operations remove today's invoice additions and install the
    historical budget check, while retaining newer private/evidence ledgers.
    This models an additive local installation, not an invented Alembic version.
    """
    path = tmp_path / "standalone.sqlite"
    engine = create_engine("sqlite:///" + path.as_posix(), hide_parameters=True)
    Base.metadata.create_all(engine)
    ring = IBANKeyring("synthetic", {"synthetic": generate_key()}, (), generate_key())
    monkeypatch.setattr(form_draft_crypto, "current_keyring", lambda: ring)
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        target = seed(store, "receivable")
        contract = store.get_contract(target.contract_id)
        prop = store.get_property(contract.property_id)
        account = store.create_account(AccountCreate(portfolio_id=prop.portfolio_id, name="Synthetic bank", account_type="bank"))
        bank = store.create_booking(BookingCreate(account_id=account.id, booking_date=date(2026, 9, 5), amount=100.30))
        old = store.record_payment("receivable", target.id, PaymentCreate(idempotency_key="before-upgrade",
            amount=Decimal("40.10"), payment_date=bank.booking_date, booking_id=bank.id))
        old_reversal = store.reverse_payment("receivable", target.id, old.id, PaymentReversalCreate(
            idempotency_key="before-upgrade-reversal", reversal_date=date(2026, 9, 6), reason="Synthetic correction"))
        invoice = store.create_invoice(InvoiceCreate(property_id=prop.id, supplier="Synthetic supplier",
            invoice_date=date(2026, 9, 1), net_amount=100.30, gross_amount=100.30, vat_rate=0))
        inherited = store.create_invoice(InvoiceCreate(property_id=prop.id, supplier="Historical synthetic",
            invoice_date=date(2026, 9, 1), net_amount=50.20, gross_amount=50.20, vat_rate=0, status="paid"))
        negative = store.create_booking(BookingCreate(account_id=account.id, booking_date=date(2026, 9, 7), amount=-100.30))
        now = datetime(2026, 9, 8, 10, 15, 0, 123456)
        draft_id = "d" * 64
        draft_payload = json.dumps({"values": {"name": "Synthetic private unsaved €"},
            "edit_revision": {"updatedAt": "2026-09-08T10:15:00.123456"}}, ensure_ascii=False).encode()
        cipher = form_draft_crypto.encrypt(draft_payload, draft_id.encode())
        db.add(FormDraftORM(id=draft_id, user_id="synthetic-owner", collection="properties", entity_id=prop.id,
            form_key="default", scope_hash="a" * 64, revision="private-original-revision", payload=cipher,
            updated_at=now, expires_at=now + timedelta(days=7)))
        pdf = b"%PDF-1.7\nSynthetic immutable database bytes\x00\xff\n%%EOF"
        evidence = b"Synthetic attachment evidence\x00\xfe"
        db.add(ContractDraftORM(id="wizard-original", portfolio_id=prop.portfolio_id, actor_id="synthetic-owner",
            create_key="wizard-key", create_hash="b" * 64, data={"tenant_id": contract.tenant_id}, revision=7,
            state="reviewed", review={"version": 7}, review_hash="c" * 64, pdf=pdf,
            pdf_sha256=hashlib.sha256(pdf).hexdigest(), created_at=now, updated_at=now))
        db.flush()
        db.add(ContractAttachmentORM(id="attachment-original", portfolio_id=prop.portfolio_id, draft_id="wizard-original",
            source_document_id="synthetic-document", metadata_snapshot={"name": "Synthetic attachment"},
            sha256=hashlib.sha256(evidence).hexdigest(), size_bytes=len(evidence), mode="frozen"))
        db.flush()
        db.add(ContractAttachmentChunkORM(attachment_id="attachment-original", position=0,
            portfolio_id=prop.portfolio_id, data=evidence))
        db.commit()
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.rollback()
        connection.exec_driver_sql("BEGIN EXCLUSIVE")
        with Operations.context(MigrationContext.configure(connection)):
            import_module("backend.db.migrations.versions.w1a2b3c4d5e6_invoice_payment_receipts").downgrade()
            import_module("backend.db.migrations.versions.n1a2b3c4d5e6_credit_receipt_journal")._allocation_check(tool.OLD_ALLOCATION)
        connection.exec_driver_sql("CREATE TABLE sentinel(id INTEGER PRIMARY KEY, visits INTEGER NOT NULL)")
        connection.exec_driver_sql("INSERT INTO sentinel VALUES (1,0)")
        connection.exec_driver_sql("CREATE TRIGGER invoice_business_update AFTER UPDATE ON invoices BEGIN UPDATE sentinel SET visits=visits+1; END")
        connection.exec_driver_sql("CREATE TRIGGER cross_table_history BEFORE DELETE ON sentinel BEGIN SELECT amount FROM payments LIMIT 1; END")
        connection.exec_driver_sql("CREATE INDEX retained_booking_partial ON bookings(payment_text) WHERE amount < 0")
        connection.commit()
        assert "alembic_version" not in inspect(connection).get_table_names()
        assert all("invoice_id" not in c["sqltext"] for c in inspect(connection).get_check_constraints("payments"))
    yield path, engine, invoice.id, inherited.id, negative.id, old.id, old_reversal.id, cipher, draft_payload
    engine.dispose()


def state(path):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        schema = db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
        rows = {table: db.execute('SELECT * FROM "' + table.replace('"', '""') + '" ORDER BY rowid').fetchall()
                for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
    return schema, rows


def additive_booking_allocation_without_check(engine):
    """Reproduce startup's actual ALTER-column shape, no invented named CHECK."""
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.rollback()
        connection.exec_driver_sql("BEGIN EXCLUSIVE")
        with Operations.context(MigrationContext.configure(connection)):
            with op.batch_alter_table("bookings") as batch:
                batch.drop_constraint("ck_bookings_allocation", type_="check")
                batch.drop_column("allocated_amount")
                batch.create_check_constraint("retained_booking_status", "length(status) > 0")
        # Exact additive startup DDL from backend/db/session.py.
        connection.exec_driver_sql("ALTER TABLE bookings ADD COLUMN allocated_amount NUMERIC(12, 2) NOT NULL DEFAULT 0")
        connection.exec_driver_sql("CREATE TRIGGER retained_booking_budget AFTER UPDATE ON bookings BEGIN UPDATE sentinel SET visits=visits+1; END")
        connection.commit()
        checks = {row["name"] for row in inspect(connection).get_check_constraints("bookings")}
        assert checks == {"ck_bookings_amount_nonzero", "retained_booking_status"}


def historical_inline_booking_reference(engine):
    """Reproduce the old startup's ALTER FK, retaining synthetic receipt links."""
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.rollback()
        connection.exec_driver_sql("BEGIN EXCLUSIVE")
        triggers = list(connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND sql IS NOT NULL"))
        for name, _ in triggers:
            connection.exec_driver_sql(f"DROP TRIGGER {tool._quoted(name)}")
        links = list(connection.exec_driver_sql("SELECT id,booking_id FROM payments"))
        foreign_key = next(fk for fk in inspect(connection).get_foreign_keys("payments")
                           if fk["constrained_columns"] == ["booking_id"])
        with Operations.context(MigrationContext.configure(connection)):
            with op.batch_alter_table("payments", naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}) as batch:
                batch.drop_index("idx_payments_booking")
                batch.drop_constraint(foreign_key["name"] or "fk_payments_booking_id_bookings", type_="foreignkey")
                batch.drop_column("booking_id")
        # Exact additive startup DDL: SQLAlchemy's FK reflection misses RESTRICT.
        connection.exec_driver_sql("ALTER TABLE payments ADD COLUMN booking_id VARCHAR REFERENCES bookings(id) ON DELETE RESTRICT")
        for payment_id, booking_id in links:
            connection.exec_driver_sql("UPDATE payments SET booking_id=? WHERE id=?", (booking_id, payment_id))
        connection.exec_driver_sql("CREATE INDEX idx_payments_booking ON payments(booking_id)")
        for index in BOOKING_INDEXES:
            connection.exec_driver_sql(f"DROP INDEX IF EXISTS {tool._quoted(index.name)}")
        ensure_booking_indexes(connection)
        # Reflection also misses DESC/collation and can omit expression indexes.
        connection.exec_driver_sql("CREATE INDEX retained_booking_expression ON bookings(lower(payment_text) COLLATE NOCASE DESC,booking_date DESC) WHERE amount < 0")
        connection.exec_driver_sql("CREATE UNIQUE INDEX retained_booking_unique ON bookings(id COLLATE NOCASE DESC) WHERE amount < 0")
        for _, sql in triggers:
            connection.exec_driver_sql(sql)
        connection.commit()


@pytest.mark.parametrize("allocation_check", [False, True])
def test_actual_alter_fk_and_desc_collation_expression_indexes_survive_upgrade_and_receipts(legacy, tmp_path, allocation_check):
    path, engine, invoice_id, _, bank_id, *_ = legacy
    if not allocation_check:
        additive_booking_allocation_without_check(engine)
    historical_inline_booking_reference(engine)
    with engine.begin() as connection:
        ensure_invoice_payment_columns(connection)
    before = state(path)
    with engine.connect() as connection:
        original_keys = tool._foreign_keys(connection, "payments")
        original_indexes = tool._indexes(connection, "bookings")
        for index in BOOKING_INDEXES:
            assert [column[2] for column in original_indexes[index.name][3] if column[1] in {"booking_date", "id"}] == [1, 1]
        assert any(row[2:6] == ("booking_id", "id", "NO ACTION", "RESTRICT") for row in original_keys)
        original_index_sql = dict(connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name='bookings' AND sql IS NOT NULL").all())
    backup = tmp_path / "HISTORICAL-SHAPE-PREVIOUS.sqlite"
    tool.upgrade_legacy_sqlite(path, backup, offline=True)
    assert state(backup) == before
    with engine.connect() as connection:
        assert original_keys <= tool._foreign_keys(connection, "payments")
        assert tool._indexes(connection, "bookings") == original_indexes
        assert dict(connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name='bookings' AND sql IS NOT NULL").all()) == original_index_sql
        with sqlite3.connect(backup) as previous:
            for table, rows in before[1].items():
                projection = ','.join(tool._quoted(column[1]) for column in previous.execute(
                    f"PRAGMA table_info({tool._quoted(table)})"))
                assert connection.exec_driver_sql(f"SELECT {projection} FROM {tool._quoted(table)} ORDER BY rowid").all() == rows
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        receipt = store.record_payment("invoice", invoice_id, PaymentCreate(idempotency_key="historic-shape-invoice",
            amount=Decimal("40.10"), booking_id=bank_id, payment_date=date(2026, 9, 7)))
        assert receipt.amount == Decimal("40.10") and store.get_booking(bank_id).allocated_amount == 40.10
        reversal = store.reverse_payment("invoice", invoice_id, receipt.id, PaymentReversalCreate(
            idempotency_key="historic-shape-reversal", reversal_date=date(2026, 9, 8), reason="Synthetic review"))
        assert reversal.amount == Decimal("40.10") and store.get_booking(bank_id).allocated_amount == 0


def test_versioned_n1_w1_chain_preserves_actual_inline_fk_and_desc_expression_indexes(tmp_path, monkeypatch):
    config, engine = migrate(tmp_path, monkeypatch)
    try:
        historical_inline_booking_reference(engine)
        with engine.begin() as connection:
            ensure_invoice_payment_columns(connection)
            foreign_keys = tool._foreign_keys(connection, "payments")
            indexes = tool._indexes(connection, "bookings")
            original_sql = dict(connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name='bookings' AND sql IS NOT NULL").all())
        for revision in ("n1a2b3c4d5e6", "w1a2b3c4d5e6"):
            command.upgrade(config, revision)
            with engine.connect() as connection:
                assert foreign_keys <= tool._foreign_keys(connection, "payments")
                assert tool._indexes(connection, "bookings") == indexes
                assert dict(connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name='bookings' AND sql IS NOT NULL").all()) == original_sql
                assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
                assert connection.exec_driver_sql("PRAGMA foreign_key_check").first() is None
    finally:
        engine.dispose()


@pytest.mark.parametrize("additive_read_columns", [False, True])
@pytest.mark.parametrize("allocation_check", [False, True])
def test_unversioned_upgrade_preserves_previous_all_rows_triggers_private_and_frozen_ledgers_and_real_receipt(legacy, tmp_path, additive_read_columns, allocation_check):
    path, engine, invoice_id, inherited_id, bank_id, old_id, reversal_id, cipher, plaintext = legacy
    if not allocation_check:
        additive_booking_allocation_without_check(engine)
    if additive_read_columns:
        with engine.begin() as connection:
            ensure_invoice_payment_columns(connection)
            ensure_invoice_payment_immutability(connection)
            # This fixture intentionally includes an earlier startup backfill;
            # the offline transaction itself must never change the sentinel.
    before = state(path)
    with engine.connect() as connection:
        assert inspect(connection).get_check_constraints("payments")
    backup = tmp_path / "PREVIOUS.sqlite"
    result = tool.upgrade_legacy_sqlite(path, backup, offline=True)
    assert result == {"upgraded": True, "backup_created": True, "scope": "local_invoice_receipt_schema", "alembic_version_changed": False}
    assert state(backup) == before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='alembic_version'").fetchone() is None
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("PRAGMA foreign_key_check").fetchone() is None
        assert db.execute("SELECT payload FROM form_drafts").fetchone() == (cipher,)
        assert form_draft_crypto.decrypt(cipher, ("d" * 64).encode()) == plaintext
        assert db.execute("SELECT visits FROM sentinel").fetchone() == tuple(before[1]["sentinel"][0][1:])
        assert db.execute("SELECT amount_paid,status FROM invoices WHERE id=?", (inherited_id,)).fetchone() == (50.20, "paid")
        for table in ("form_drafts", "contract_wizard_drafts", "contract_attachment_evidence", "contract_attachment_chunks", "payment_reversals"):
            assert db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall() == before[1][table]
        original_triggers = {name: sql for name, sql in before[0] if sql and sql.startswith("CREATE TRIGGER")}
        assert all(db.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone() == (sql,)
                   for name, sql in original_triggers.items())
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        assert store.list_payments()[0].id == old_id
        assert store.list_payments()[0].reversal.id == reversal_id
        receipt = store.record_payment("invoice", invoice_id, PaymentCreate(idempotency_key="invoice-after-upgrade",
            amount=Decimal("40.10"), payment_date=date(2026, 9, 7), booking_id=bank_id))
        assert receipt.amount == Decimal("40.10") and store.get_booking(bank_id).allocated_amount == 40.10
        assert store.get_invoice(invoice_id).amount_paid == 40.10
        reversal = store.reverse_payment("invoice", invoice_id, receipt.id, PaymentReversalCreate(
            idempotency_key="invoice-reversal", reversal_date=date(2026, 9, 8), reason="Synthetic review"))
        assert reversal.amount == Decimal("40.10") and store.get_booking(bank_id).allocated_amount == 0
        assert store.get_invoice(invoice_id).amount_paid == 0
    after = state(path)
    tool.upgrade_legacy_sqlite(path, tmp_path / "SECOND-PREVIOUS.sqlite", offline=True)
    assert state(path) == after  # Already upgraded, including immutable receipts.
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.exec_driver_sql("UPDATE payments SET amount=1 WHERE id=?", (receipt.id,))
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.exec_driver_sql("UPDATE payment_reversals SET amount=1 WHERE id=?", (reversal.id,))


@pytest.mark.parametrize("allocation_check", [False, True])
def test_halfway_real_invoice_ddl_failure_rolls_back_schema_rows_triggers_and_retains_private_previous(legacy, tmp_path, allocation_check):
    path, engine, *_ = legacy
    if not allocation_check:
        additive_booking_allocation_without_check(engine)
    before = state(path)
    seen = []
    def fail(_, __, statement, ___, ____, _____):
        if 'ALTER TABLE _alembic_tmp_payments RENAME TO payments' in statement:
            seen.append(statement)
            raise RuntimeError("PRIVATE SYNTHETIC ROW MUST NEVER BE PRINTED")
    event.listen(Engine, "after_cursor_execute", fail)
    backup = tmp_path / "FAILED-PREVIOUS.sqlite"
    try:
        with pytest.raises(tool.InvoiceUpgradeError, match="upgrade_failed") as error:
            tool.upgrade_legacy_sqlite(path, backup, offline=True)
    finally:
        event.remove(Engine, "after_cursor_execute", fail)
    assert seen and "PRIVATE" not in str(error.value)
    assert state(path) == before and state(backup) == before


@pytest.mark.parametrize("invalid", [-0.01, 100.31, float("inf"), "invalid-counter"])
def test_missing_budget_check_rejects_invalid_source_counters_before_any_ddl(legacy, tmp_path, invalid):
    path, engine, _, _, bank_id, *_ = legacy
    additive_booking_allocation_without_check(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE bookings SET allocated_amount=? WHERE id=?", (invalid, bank_id))
    before = state(path)
    ddl = []
    def observe(_, __, statement, ___, ____, _____):
        if statement.lstrip().upper().startswith(("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ")):
            ddl.append(statement)
    backup = tmp_path / "INVALID-BUDGET-PREVIOUS.sqlite"
    event.listen(Engine, "before_cursor_execute", observe)
    try:
        with pytest.raises(tool.InvoiceUpgradeError, match="allocation_invalid"):
            tool.upgrade_legacy_sqlite(path, backup, offline=True)
    finally:
        event.remove(Engine, "before_cursor_execute", observe)
    assert not ddl and state(path) == before and state(backup) == before


def test_cli_invalid_budget_has_typed_review_guidance_without_exposing_source_rows(legacy, tmp_path, capsys):
    path, engine, _, _, bank_id, *_ = legacy
    additive_booking_allocation_without_check(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE bookings SET allocated_amount=-0.01 WHERE id=?", (bank_id,))
    before = state(path)
    backup = tmp_path / "CLI-INVALID-PREVIOUS.sqlite"
    assert tool.main(["--database", str(path), "--backup-output", str(backup), "--offline"]) == 2
    output = capsys.readouterr()
    assert "Belege und Zuordnungen prüfen" in output.err and "Keine Schemaänderung" in output.err
    assert str(path) not in output.err and bank_id not in output.err and "-0.01" not in output.err
    assert state(path) == before and state(backup) == before


@pytest.mark.parametrize("foreign_check", ["unknown_budget", "missing_nonzero", "unknown_nonzero"])
def test_missing_budget_check_requires_known_amount_check_and_never_replaces_foreign_checks(legacy, tmp_path, foreign_check):
    path, engine, *_ = legacy
    additive_booking_allocation_without_check(engine)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.rollback()
        connection.exec_driver_sql("BEGIN EXCLUSIVE")
        triggers = list(connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='bookings'"))
        for name, _ in triggers:
            connection.exec_driver_sql('DROP TRIGGER "' + name.replace('"', '""') + '"')
        with Operations.context(MigrationContext.configure(connection)):
            with op.batch_alter_table("bookings") as batch:
                if foreign_check == "unknown_budget":
                    batch.create_check_constraint("ck_bookings_allocation", "allocated_amount >= -1")
                else:
                    batch.drop_constraint("ck_bookings_amount_nonzero", type_="check")
                    if foreign_check == "unknown_nonzero":
                        batch.create_check_constraint("ck_bookings_amount_nonzero", "amount != 0 AND amount != 1234567")
        for _, sql in triggers:
            connection.exec_driver_sql(sql)
        connection.commit()
    before = state(path)
    with pytest.raises(tool.InvoiceUpgradeError, match="schema_unsupported"):
        tool.upgrade_legacy_sqlite(path, tmp_path / "FOREIGN-BUDGET-PREVIOUS.sqlite", offline=True)
    assert state(path) == before


def test_preservation_check_rejects_unrelated_business_mutation_after_real_ddl(legacy, tmp_path, monkeypatch):
    path, _, *_ = legacy
    before = state(path)
    migration = import_module("backend.db.migrations.versions.w1a2b3c4d5e6_invoice_payment_receipts")
    actual = migration.upgrade
    def corrupt():
        actual()
        migration.op.get_bind().exec_driver_sql("UPDATE sentinel SET visits=100")
    monkeypatch.setattr(migration, "upgrade", corrupt)
    with pytest.raises(tool.InvoiceUpgradeError, match="preservation_failed"):
        tool.upgrade_legacy_sqlite(path, tmp_path / "REJECTED-PREVIOUS.sqlite", offline=True)
    assert state(path) == before


def test_writers_versioned_database_no_overwrite_and_unknown_check_are_recoverable(legacy, tmp_path, monkeypatch):
    path, engine, *_ = legacy
    before = state(path)
    backup = tmp_path / "PREVIOUS.sqlite"
    with pytest.raises(tool.InvoiceUpgradeError, match="offline_required"):
        tool.upgrade_legacy_sqlite(path, backup)
    assert not backup.exists() and state(path) == before
    backup.write_bytes(b"NEVER OVERWRITE")
    with pytest.raises(tool.InvoiceUpgradeError, match="snapshot_exists"):
        tool.upgrade_legacy_sqlite(path, backup, offline=True)
    assert backup.read_bytes() == b"NEVER OVERWRITE"
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY)")
        db.exec_driver_sql("INSERT INTO alembic_version VALUES ('v1a2b3c4d5e6')")
    versioned = state(path)
    with pytest.raises(tool.InvoiceUpgradeError, match="database_versioned"):
        tool.upgrade_legacy_sqlite(path, tmp_path / "VERSIONED.sqlite", offline=True)
    assert state(path) == versioned and not (tmp_path / "VERSIONED.sqlite").exists()
    with engine.begin() as db:
        db.exec_driver_sql("DROP TABLE alembic_version")
    # Pretend the inspector finds an unfamiliar check. Never replace it on a guess.
    monkeypatch.setattr(tool, "_check_definition", lambda *args: "custom_unrecognized_check")
    with pytest.raises(tool.InvoiceUpgradeError, match="schema_unsupported"):
        tool.upgrade_legacy_sqlite(path, tmp_path / "UNKNOWN-PREVIOUS.sqlite", offline=True)
    assert state(path) == before


def test_actual_independent_writer_after_snapshot_aborts_before_ddl(legacy, tmp_path, monkeypatch):
    path, _, *_ = legacy
    before = state(path)
    actual = tool.boundary.protected_new_file
    @contextmanager
    def interleave(destination):
        with actual(destination) as stream:
            yield stream
        with sqlite3.connect(path) as db:
            db.execute("UPDATE sentinel SET visits=7")
    monkeypatch.setattr(tool.boundary, "protected_new_file", interleave)
    backup = tmp_path / "RACED-PREVIOUS.sqlite"
    with pytest.raises(tool.InvoiceUpgradeError, match="database_changed"):
        tool.upgrade_legacy_sqlite(path, backup, offline=True)
    assert state(backup) == before
    after_schema, after_rows = state(path)
    assert after_schema == before[0] and after_rows["sentinel"] == [(1, 7)]
    assert {table: rows for table, rows in after_rows.items() if table != "sentinel"} == {
        table: rows for table, rows in before[1].items() if table != "sentinel"}


def test_exclusive_upgrade_lock_rejects_an_independent_writer_until_publication(legacy, tmp_path):
    path, _, *_ = legacy
    blocked = []
    def competing_writer(_, __, statement, ___, ____, _____):
        if statement == "BEGIN EXCLUSIVE":
            with sqlite3.connect(path, timeout=0) as competitor:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    competitor.execute("UPDATE sentinel SET visits=99")
                blocked.append(True)
    event.listen(Engine, "after_cursor_execute", competing_writer)
    try:
        tool.upgrade_legacy_sqlite(path, tmp_path / "LOCKED-PREVIOUS.sqlite", offline=True)
    finally:
        event.remove(Engine, "after_cursor_execute", competing_writer)
    assert blocked == [True]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT visits FROM sentinel").fetchone() == (0,)


def test_real_versioned_w1_migration_retains_additive_inline_invoice_fk_restrict(tmp_path, monkeypatch):
    config, engine = migrate(tmp_path, monkeypatch)
    try:
        command.upgrade(config, "v1a2b3c4d5e6")
        with engine.begin() as connection:
            ensure_invoice_payment_columns(connection)
            connection.exec_driver_sql("CREATE TABLE retained_invoice_sentinel(value TEXT PRIMARY KEY)")
            connection.exec_driver_sql("INSERT INTO retained_invoice_sentinel VALUES ('Synthetic unchanged')")
            connection.exec_driver_sql("CREATE TRIGGER retained_invoice_trigger BEFORE DELETE ON retained_invoice_sentinel BEGIN SELECT invoice_id FROM payments LIMIT 1; END")
            before = connection.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name='retained_invoice_trigger'").scalar()
        command.upgrade(config, "w1a2b3c4d5e6")
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "w1a2b3c4d5e6"
            assert any(row[2] == "invoices" and row[3] == "invoice_id" and row[6] == "RESTRICT"
                       for row in connection.exec_driver_sql("PRAGMA foreign_key_list(payments)"))
            assert connection.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name='retained_invoice_trigger'").scalar() == before
            assert connection.exec_driver_sql("SELECT value FROM retained_invoice_sentinel").scalar() == "Synthetic unchanged"
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").first() is None
    finally:
        engine.dispose()


def test_cli_success_and_typed_retry_message_no_sensitive_diagnostics(legacy, tmp_path, capsys, monkeypatch):
    path, _, *_ = legacy
    assert tool.main(["--database", str(path), "--backup-output", str(tmp_path / "CLI-PREVIOUS.sqlite"), "--offline"]) == 0
    assert "keine Alembic-Version gesetzt" in capsys.readouterr().out
    def fail(*args, **kwargs):
        raise tool.InvoiceUpgradeError("database_busy")
    monkeypatch.setattr(tool, "upgrade_legacy_sqlite", fail)
    assert tool.main(["--database", str(path), "--backup-output", str(tmp_path / "CLI-RETRY.sqlite"), "--offline"]) == 2
    output = capsys.readouterr()
    assert "Schreiber stoppen" in output.err and str(path) not in output.err


def test_old_check_still_refuses_invoice_receipt_before_offline_upgrade(legacy):
    path, engine, invoice_id, _, bank_id, *_ = legacy
    with engine.begin() as connection:
        ensure_invoice_payment_columns(connection)
    before = state(path)
    with Session(engine) as db, pytest.raises(FinancialConsistencyError, match="Offline"):
        SQLAlchemyStore(db).record_payment("invoice", invoice_id, PaymentCreate(idempotency_key="not-upgraded",
            amount=Decimal("40.10"), booking_id=bank_id, payment_date=date(2026, 9, 7)))
    assert state(path) == before
