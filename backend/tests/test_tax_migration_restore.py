"""Assigned migration preserves current data; full backup restores exact tax bytes."""
import hashlib
import sqlite3
from contextlib import closing
from datetime import date

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from backend.db import schema_state
from backend.db.datev_models import DatevBlockORM
from backend.models import AccountCreate, BookingCreate, CategoryCreate, PortfolioCreate, PropertyCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import annual_tax_storage as annual
from backend.services import datev_export as datev
from backend.services import full_backup, secret_box
from backend.services.full_backup import Sources
from backend.services.tax_archive_validation import verify_tax_archive
from backend.tests.test_annual_tax_projection import preflight_command, profile_command, save_command
from backend.tests.test_tax_current_contracts import datev_profile, datev_request


def snapshot(path):
    with closing(sqlite3.connect(path)) as connection:
        names = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'")]
        return {name: connection.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall() for name in names}


def test_assigned_migration_preserves_every_existing_row_and_rejects_audit_downgrade(tmp_path):
    path = tmp_path / "migration.db"
    url = f"sqlite:///{path.as_posix()}"
    config = schema_state.alembic_config(url)
    command.upgrade(config, "d73f2b9a041c")
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("INSERT INTO portfolios(id, name, currency, timezone, status, created_at, updated_at) VALUES ('p', 'Ursprünglich', 'EUR', 'Europe/Berlin', 'active', '2026-01-01', '2026-01-01')")
    before = snapshot(path)
    command.upgrade(config, "e160a1b2c303")
    after = snapshot(path)
    assert all(after[name] == rows for name, rows in before.items())
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("INSERT INTO annual_tax_profiles(id, portfolio_id, tax_year, idempotency_key, actor_id, spec_json, sha256, created_at) VALUES ('review', 'p', 2026, 'actor:key', 'actor', '{}', 'unpublished-test', '2026-01-01')")
    protected = snapshot(path)
    with pytest.raises(RuntimeError, match="Downgrade"):
        command.downgrade(config, "d73f2b9a041c")
    assert snapshot(path) == protected


def test_tax_backup_restores_ciphertext_keys_original_bytes_and_money(tmp_path, monkeypatch):
    path = tmp_path / "source.db"
    url = f"sqlite:///{path.as_posix()}"
    # written through today's ORM below, so the source needs today's schema
    command.upgrade(schema_state.alembic_config(url), "head")
    box = secret_box.SecretBox(tmp_path / "synthetic-keyring.json")
    monkeypatch.setattr(annual, "default_secret_box", lambda: box)
    monkeypatch.setattr(datev, "default_secret_box", lambda: box)
    engine = create_engine(url)
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        portfolio = store.create_portfolio(PortfolioCreate(name="Synthetic source"))
        prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Synthetic property", property_type="residential"))
        account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Synthetic bank", account_type="bank"))
        rent = store.create_category(CategoryCreate(portfolio_id=portfolio.id, name="Miete", category_type="income"))
        costs = store.create_category(CategoryCreate(portfolio_id=portfolio.id, name="Kosten", category_type="expense"))
        fixture = store, engine, portfolio, [prop], [account], [rent, costs]
        for amount in ("100.01", "-0.01"):
            store.create_booking(BookingCreate.model_validate(dict(account_id=account.id, category_id=rent.id, property_id=prop.id,
                booking_date=date(2024, 6, 1), amount=amount, status="confirmed", payment_text="Synthetic")))
        version = annual.create_profile(store, profile_command(fixture), "actor")
        review = preflight_command(version)
        saved = annual.create_projection(store, save_command(review, annual.preflight(store, review)), "actor")
        assert saved["totals"]["income_cents"] == "10000"
        dversion = datev.create_profile(store, datev_profile(fixture), "actor")
        receipt = datev.create_preview(store, datev_request(dversion), "actor")
        original = datev.prepare_saved_download(store, receipt["id"])
        try:
            original_hash = hashlib.sha256(original.path.read_bytes()).hexdigest()
        finally:
            original.close()
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "original.bin").write_bytes(b"original\x00\xff\x10")
    sources = Sources(database_url=url, data_dir=tmp_path, uploads_dir=uploads,
        root=tmp_path / "backups", integration_state=tmp_path / "absent-integrations.json",
        key_file=box.key_file, env_file=tmp_path / "absent.env")
    event = full_backup.create_full_backup("manual", sources)
    probe = full_backup.restore_probe(sources.root / event["archive"], sources)
    assert probe["ok"] and probe["checks"]["secrets"]["tax_receipts_verified"] == 2
    restored = tmp_path / "restored"
    full_backup.restore_archive(sources.root / event["archive"], restored)
    assert (restored / "uploads" / "original.bin").read_bytes() == b"original\x00\xff\x10"
    restored_box = secret_box.SecretBox(restored / full_backup.KEYRING)
    restored_engine = create_engine(f"sqlite:///{(restored / 'immo_manager.db').as_posix()}")
    with restored_engine.connect() as connection:
        assert verify_tax_archive(connection, restored_box.open) == 2
    monkeypatch.setattr(datev, "default_secret_box", lambda: restored_box)
    with Session(restored_engine) as db:
        original = datev.prepare_saved_download(SQLAlchemyStore(db), receipt["id"])
        try:
            assert hashlib.sha256(original.path.read_bytes()).hexdigest() == original_hash
        finally:
            original.close()
        block = db.scalar(select(DatevBlockORM).where(DatevBlockORM.export_id == receipt["id"]))
        assert block is not None
        block.token = block.token[:-6] + "BROKEN"
        db.commit()
    with restored_engine.connect() as connection, pytest.raises(secret_box.SecretError):
        verify_tax_archive(connection, restored_box.open)
    # A structurally intact backup of tampered tax ciphertext must also fail
    # through the public restore path, even without a single bank-import row.
    # Its outer archive checksums are valid: this tests semantic authenticity.
    broken_sources = Sources(database_url=str(restored_engine.url), data_dir=restored,
        uploads_dir=restored / "uploads", root=tmp_path / "broken-backups",
        integration_state=tmp_path / "absent-integrations.json",
        key_file=restored_box.key_file, env_file=tmp_path / "absent.env")
    broken = full_backup.create_full_backup("manual", broken_sources)
    rejected = tmp_path / "must-not-publish"
    with pytest.raises(secret_box.SecretError):
        full_backup.restore_archive(broken_sources.root / broken["archive"], rejected)
    assert not (rejected / "immo_manager.db").exists()
    assert not (rejected / "uploads").exists()
    restored_engine.dispose()
    engine.dispose()


def test_create_all_adoption_has_identical_tax_tables(tmp_path):
    from backend.db.orm_models import Base
    path = tmp_path / "adopted.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    expected = {name: [c["name"] for c in inspect(engine).get_columns(name)] for name in Base.metadata.tables if name.startswith(("datev_", "annual_tax_"))}
    command.upgrade(schema_state.alembic_config(str(engine.url)), "e160a1b2c303")
    assert all([c["name"] for c in inspect(engine).get_columns(name)] == columns for name, columns in expected.items())
    engine.dispose()
