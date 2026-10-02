"""Fresh real migration, additive local startup, preserved revocation on downgrade."""

from types import SimpleNamespace

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.db.session_models import (
    AuthRefreshORM,
    AuthSessionORM,
    ensure_session_schema,
    invalidate_restored_sessions,
)
from backend.services import auth_sessions as service
from backend.tests import test_billing_migration_guards as migration_tests

migration_database = migration_tests.migration_database


def test_fresh_complete_chain_session_columns_empty_roundtrip_and_additive_bootstrap(migration_database):
    config, path = migration_database
    assert ScriptDirectory.from_config(config).get_revision("t1a2b3c4d5e6").down_revision == "s1a2b3c4d5e6"
    command.upgrade(config, "t1a2b3c4d5e6")
    engine = create_engine("sqlite:///" + path.as_posix())
    try:
        for model in (AuthSessionORM, AuthRefreshORM):
            assert set(model.__table__.c.keys()) == {column["name"] for column in inspect(engine).get_columns(model.__tablename__)}
        before = migration_tests._structure(path)
        with engine.begin() as db:
            ensure_session_schema(db)
            ensure_session_schema(db)
        command.downgrade(config, "s1a2b3c4d5e6")
        command.upgrade(config, "t1a2b3c4d5e6")
        assert migration_tests._structure(path) == before
    finally:
        engine.dispose()


@pytest.fixture
def migrated_security(migration_database, monkeypatch):
    config, path = migration_database
    command.upgrade(config, "t1a2b3c4d5e6")
    engine = create_engine("sqlite:///" + path.as_posix())
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    monkeypatch.setattr(auth, "_token_blacklist", set())
    monkeypatch.setattr(auth, "_blacklist_expiry", {})
    owner = auth.register_user("synthetic", "synthetic@example.test", "Synthetic", "Strong123", "eigentuemer")
    yield SimpleNamespace(config=config, path=path, engine=engine, factory=factory, owner=owner)
    engine.dispose()


def test_populated_downgrade_preserves_consumed_refresh_protection_before_any_ddl(migrated_security):
    box = migrated_security
    first = service.login_pair(box.owner.id)
    service.rotate(first.refresh_token)
    before = migration_tests._state(box.path)
    with pytest.raises(RuntimeError, match="replay/revocation protection"):
        command.downgrade(box.config, "s1a2b3c4d5e6")
    assert migration_tests._state(box.path) == before
    with pytest.raises(HTTPException) as replay:
        service.rotate(first.refresh_token)
    assert replay.value.status_code == 401


def test_offline_restore_hook_revokes_snapshot_families_keeps_consumed_receipts(migrated_security):
    box = migrated_security
    original = service.login_pair(box.owner.id)
    current = service.rotate(original.refresh_token)
    with box.factory() as db:
        before = db.execute(select(AuthRefreshORM.__table__)).all()
    with box.engine.begin() as db:
        assert invalidate_restored_sessions(db) == 1
        assert invalidate_restored_sessions(db) == 0
    with box.factory() as db:
        assert db.execute(select(AuthRefreshORM.__table__)).all() == before
        assert db.scalar(select(AuthSessionORM.revoke_reason)) == "database_restore"
    with pytest.raises(HTTPException) as invalid:
        auth.decode_token(current.access_token)
    assert invalid.value.status_code == 401
