"""An actual additive migration retains legacy scope and refuses widening rollback."""

import sqlite3
from contextlib import closing

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.tests import test_billing_migration_guards as migration_tests
from backend.tests.test_billing_migration_guards import _state, _structure

migration_database = migration_tests.migration_database

BEFORE = "n1a2b3c4d5e6"
ACCESS = "o1a2b3c4d5e6"


def _legacy_user(database):
    with closing(sqlite3.connect(database)) as db:
        db.execute(
            "INSERT INTO users (id, username, email, full_name, hashed_password, role, is_active, created_at, updated_at) "
            "VALUES ('legacy', 'legacy', 'legacy@example.test', 'Historical manager', 'synthetic-hash', 'verwalter', 1, '2026-01-01', '2026-01-01')"
        )
        db.execute(
            "INSERT INTO portfolios (id, name, currency, timezone, status, created_at, updated_at) VALUES ('folio', 'Historical portfolio', 'EUR', 'Europe/Berlin', 'active', '2026-01-01', '2026-01-01')"
        )
        db.commit()


def test_full_chain_and_legacy_all_scope_can_roundtrip_empty_grants(migration_database):
    config, database = migration_database
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1
    assert ScriptDirectory.from_config(config).get_revision(ACCESS).down_revision == BEFORE
    command.upgrade(config, BEFORE)
    _legacy_user(database)
    users_before = _state(database)[1]["users"]
    command.upgrade(config, ACCESS)
    assert _state(database)[1]["users"] == users_before
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT user_id, mode, origin FROM user_portfolio_access").fetchall() == [
            ("legacy", "all", "legacy_all")
        ]
    structure = _structure(database)
    command.downgrade(config, BEFORE)
    command.upgrade(config, ACCESS)
    assert _structure(database) == structure
    assert _state(database)[1]["users"] == users_before


def test_startup_create_all_compatibility_backfills_legacy_once_and_missing_future_rows_fail_closed(migration_database, monkeypatch):
    config, database = migration_database
    command.upgrade(config, BEFORE)
    _legacy_user(database)
    engine = create_engine("sqlite:///" + database.as_posix())
    try:
        from backend.db import session as application_database
        monkeypatch.setattr(application_database, "engine", engine)
        application_database.create_tables()
        users = auth.SQLUserStore(sessionmaker(bind=engine))
        assert users.get_by_id("legacy")["portfolio_access"] == "all"
        application_database.create_tables()
        with closing(sqlite3.connect(database)) as db:
            assert db.execute("SELECT COUNT(*) FROM user_portfolio_access").fetchone() == (1,)
            db.execute("DELETE FROM user_portfolio_access WHERE user_id='legacy'")
            db.commit()
        application_database.create_tables()
        assert users.get_by_id("legacy")["portfolio_access"] == "selected"
        assert users.get_by_id("legacy")["portfolio_ids"] == []
    finally:
        engine.dispose()


@pytest.mark.parametrize("evidence", ["selected", "user", "resource", "upload"])
def test_restricted_scope_or_resource_binding_refuses_before_any_ddl(migration_database, evidence):
    config, database = migration_database
    command.upgrade(config, BEFORE)
    _legacy_user(database)
    command.upgrade(config, ACCESS)
    with closing(sqlite3.connect(database)) as db:
        if evidence == "selected":
            db.execute("UPDATE user_portfolio_access SET mode='selected' WHERE user_id='legacy'")
        elif evidence == "user":
            db.execute("INSERT INTO user_portfolio_grants VALUES ('legacy', 'folio')")
        elif evidence == "resource":
            db.execute("INSERT INTO resource_portfolio_grants VALUES ('tenants', 'historical-tenant', 'folio')")
        else:
            db.execute("INSERT INTO upload_portfolio_grants VALUES ('documents/historical.pdf', 'folio', 'legacy')")
        db.commit()
    before = _state(database)
    with pytest.raises(RuntimeError, match="downgrade would widen access"):
        command.downgrade(config, BEFORE)
    assert _state(database) == before
