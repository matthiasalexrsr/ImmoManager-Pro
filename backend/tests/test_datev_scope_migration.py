"""DATEV Core reads share authoritative portfolio scopes and frozen migrations."""

from datetime import datetime, timezone

import pytest
from alembic import command as migration
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import inspect, select

from backend import auth
from backend.db.credit_models import CreditReceiptORM  # noqa: F401 register the full import graph before create_all
from backend.db.datev_models import DatevExportORM, DatevProfileORM
from backend.db.orm_models import CategoryORM
from backend.services import datev_export as service
from backend.services import portfolio_scope
from backend.services.data_transfer import TransferError, export_store_data, import_store_data
from backend.storage import NotFoundError
from backend.tests import test_billing_migration_guards as migration_tests
from backend.tests import test_datev_export as export_tests

active = export_tests.active
migration_database = migration_tests.migration_database


def actual_scope(monkeypatch):
    scope = portfolio_scope.AccessScope("synthetic-scoped", "buchhaltung", False, ("p",))
    user = {"id": scope.user_id, "role": scope.role, "is_active": True,
            "portfolio_access": "selected", "portfolio_ids": ["p"]}
    monkeypatch.setattr(service, "scope_helpers", lambda: portfolio_scope)
    monkeypatch.setattr(auth, "get_user_by_id", lambda _: user)
    return scope, user


def test_actual_core_snapshot_profile_and_journal_cannot_cross_portfolio_scope(active, monkeypatch):
    store, engine = active
    version = service.create_profile(store, export_tests.command(), "actor")
    with engine.begin() as db:
        db.execute(CategoryORM.__table__.insert(), dict(id="foreign-c", portfolio_id="foreign", name="Foreign", category_type="income"))
    export_tests.insert(engine, [export_tests.booking(),
        export_tests.booking(1) | {"account_id": "foreign-a", "category_id": "foreign-c"}])
    scope, _ = actual_scope(monkeypatch)
    with portfolio_scope.scope_context(scope):
        assert [row["id"] for row in service.options(store, "p")["accounts"]] == ["a"]
        receipt = service.create_preview(store, export_tests.preview(version), "actor")
        assert receipt["rows"] == 1 and receipt["samples"][0]["id"] == export_tests.booking()["id"]
        assert service.list_exports(store, "p")["total"] == 1
        with pytest.raises(NotFoundError):
            service.list_profiles(store, "foreign")
    with portfolio_scope.scope_context(portfolio_scope.AccessScope("other", "buchhaltung", False, ("foreign",))):
        with pytest.raises(HTTPException) as error:
            service.profile_row(store, version["id"])
        assert error.value.status_code == 404
        with pytest.raises(HTTPException) as error:
            service.export_row(store, receipt["id"])
        assert error.value.status_code == 404
        assert service.list_exports(store, "foreign")["items"] == []


def test_revoked_scope_during_second_source_page_aborts_before_publication(active, monkeypatch, tmp_path):
    store, engine = active
    version = service.create_profile(store, export_tests.command(), "actor")
    export_tests.insert(engine, [export_tests.booking(index) for index in range(1005)])
    scope, user = actual_scope(monkeypatch)
    original = service.entries

    def revoke(*args):
        for index, entry in enumerate(original(*args)):
            yield entry
            if index == 999:
                user["portfolio_ids"] = []

    monkeypatch.setattr(service, "entries", revoke)
    with portfolio_scope.scope_context(scope), pytest.raises(HTTPException) as error:
        service.compile_export(store, export_tests.preview(version), version["id"], "synthetic-export",
            datetime.now(timezone.utc).replace(microsecond=0), parent=tmp_path)
    assert error.value.status_code == 403
    assert not any(path.name.startswith("immomanager") for path in tmp_path.iterdir())
    assert store.db.scalar(select(DatevExportORM.id)) is None


def test_business_json_replace_refuses_datev_journal_before_any_mutation(active):
    store, engine = active
    version = service.create_profile(store, export_tests.command(), "actor")
    snapshot = export_store_data(store, "synthetic-test")
    with pytest.raises(TransferError, match="datev_profiles"):
        import_store_data(store, snapshot, replace_existing=True)
    assert service.profile_row(store, version["id"]).sha256 == version["sha256"]
    assert store.get_account("a").portfolio_id == "p"


def test_actual_fresh_alembic_chain_has_datev_columns_and_empty_roundtrip(migration_database):
    config, database = migration_database
    directory = ScriptDirectory.from_config(config)
    assert len(directory.get_heads()) == 1
    assert "p1a2b3c4d5e6" in {revision.revision for revision in directory.walk_revisions()}
    assert directory.get_revision("p1a2b3c4d5e6").down_revision == "o1a2b3c4d5e6"
    migration.upgrade(config, "p1a2b3c4d5e6")
    from sqlalchemy import create_engine
    engine = create_engine("sqlite:///" + database.as_posix())
    try:
        schema = inspect(engine)
        for model in (DatevProfileORM, DatevExportORM):
            actual = {column["name"] for column in schema.get_columns(model.__tablename__)}
            assert actual == set(model.__table__.c.keys())
            assert schema.get_foreign_keys(model.__tablename__)
        structure = migration_tests._structure(database)
        migration.downgrade(config, "o1a2b3c4d5e6")
        migration.upgrade(config, "p1a2b3c4d5e6")
        assert migration_tests._structure(database) == structure
    finally:
        engine.dispose()


def test_populated_mapping_downgrade_refuses_before_ddl(migration_database):
    config, database = migration_database
    migration.upgrade(config, "p1a2b3c4d5e6")
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(database)) as db:
        db.execute("INSERT INTO portfolios (id, name, currency, timezone, status, created_at, updated_at) VALUES ('p', 'Synthetic', 'EUR', 'Europe/Berlin', 'active', '2026-01-01', '2026-01-01')")
        db.execute("INSERT INTO datev_profiles VALUES ('version','p',NULL,'actor:key','actor','{}',?, '2026-01-01')", ("a" * 64,))
        db.commit()
    before = migration_tests._state(database)
    with pytest.raises(RuntimeError, match="downgrade would erase audit evidence"):
        migration.downgrade(config, "o1a2b3c4d5e6")
    assert migration_tests._state(database) == before
