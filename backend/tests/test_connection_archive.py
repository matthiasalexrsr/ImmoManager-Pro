"""Offline private connection proof: explicit archive keys, all rows, no runtime authority."""

import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import Table, create_engine, select

from backend.db.integration_attempt_models import IntegrationActionAttemptORM, IntegrationRunCursorORM
from backend.db.integration_connection_models import (
    IntegrationActionRunORM,
    IntegrationConnectionEventORM,
    IntegrationConnectionMappingORM,
    IntegrationConnectionORM,
    IntegrationConnectionSecretORM,
    IntegrationSourceBlockORM,
)
from backend.db.orm_models import Base
from backend.dependencies import store
from backend.services import secret_box
from backend.services.integrations import connection_storage as storage
from backend.services.integrations.connection_archive import (
    ConnectionArchiveError,
    mark_restored_connections_unconfirmed,
    verify_connection_state,
)
from backend.services.integrations.connection_types import SourceObservation
from backend.tests import test_connection_framework as cases

clean = cases.clean
fixture = cases.fixture
dispatch = cases.dispatch
new_connection = cases.new_connection
prepare = cases.prepare

def db_table(model: Any) -> Table:
    return cast(Table, model.__table__)


MODELS = (IntegrationConnectionORM, IntegrationConnectionSecretORM, IntegrationConnectionMappingORM,
          IntegrationActionRunORM, IntegrationSourceBlockORM, IntegrationConnectionEventORM,
          IntegrationActionAttemptORM, IntegrationRunCursorORM)


def offline_copy(fixture, path: Path):
    """Copy only synthetic private family rows into a fresh standalone archive DB."""
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    tables = [db_table(model) for model in MODELS]
    Base.metadata.create_all(engine, tables=tables)
    with storage.work(store, fixture.owner.id) as unit, engine.begin() as destination:
        for model in MODELS:
            if unit.db is None:
                values = [storage.values(item) for item in storage.memory(unit, model).values()]
            else:
                values = [dict(item) for item in unit.db.execute(select(db_table(model))).mappings()]
            if values:
                destination.execute(db_table(model).insert(), values)
    return engine


def seed(fixture):
    connection = new_connection(fixture)
    source = {"external_label": "Unbekanntes Originalfeld", "deep": {"value": 123}}
    fixture.service.observe(connection["id"], SourceObservation(idempotency_key=str(uuid4()), source_kind="property",
        external_key="external-property-1", source_sha256=storage.digest(source), raw=source), fixture.owner.id)
    completed = dispatch(fixture, connection, prepare(fixture, connection))
    return connection, completed


def test_complete_archive_is_verified_read_only_with_only_explicit_archived_keys(fixture, tmp_path, monkeypatch):
    _connection, run = seed(fixture)
    path = tmp_path / "private-archive.sqlite3"
    engine = offline_copy(fixture, path)
    archived_keys = fixture.box.keys()
    before = path.read_bytes()
    def forbidden(*_args, **_kwargs):
        raise AssertionError("An offline verifier must not consult live auth, default keys or provider transport")
    monkeypatch.setattr(secret_box, "default_secret_box", forbidden)
    monkeypatch.setattr(fixture.provider, "run", forbidden)
    try:
        with engine.connect() as connection:
            report = verify_connection_state(connection, archived_keys)
        assert report["present"] and report["rows"] >= 7
        assert report["table_counts"]["integration_action_attempts"] == 1
        assert report["verified_result_bytes"] == run["result_bytes"]
        assert report["legacy_id_only_records"] == 0
        assert path.read_bytes() == before
    finally:
        engine.dispose()


def test_wrong_or_missing_archive_key_is_a_hard_failure_without_any_modification(fixture, tmp_path):
    seed(fixture)
    path = tmp_path / "wrong-key.sqlite3"
    engine = offline_copy(fixture, path)
    other = secret_box.SecretBox(tmp_path / "unrelated-key.json")
    other.seal("synthetic", "test")
    before = path.read_bytes()
    try:
        for keys in ([], other.keys()):
            with engine.connect() as connection, pytest.raises(ConnectionArchiveError) as error:
                verify_connection_state(connection, keys)
            assert error.value.code == "private_key_or_ciphertext"
            assert path.read_bytes() == before
    finally:
        engine.dispose()


def test_restore_interruption_normalization_is_transactional_idempotent_and_never_replays_a_provider(fixture, tmp_path):
    connection = new_connection(fixture)
    run = prepare(fixture, connection, "send", {"text": "Unbestätigter Transport"})
    def fail_finish(*_args):
        raise OSError("synthetic crash before result persistence")
    fixture.service._finish = fail_finish
    with pytest.raises(HTTPException) as error:
        dispatch(fixture, connection, run)
    assert error.value.status_code == 503
    assert len(fixture.provider.calls) == 1
    path = tmp_path / "interrupted.sqlite3"
    engine = offline_copy(fixture, path)
    keys = fixture.box.keys()
    try:
        with engine.connect() as target:
            transaction = target.begin()
            assert mark_restored_connections_unconfirmed(target, keys) == 1
            assert target.scalar(select(IntegrationActionRunORM.state)) == "unknown"
            transaction.rollback()
        with engine.connect() as target:
            assert target.scalar(select(IntegrationActionRunORM.state)) == "executing"
        with engine.begin() as target:
            assert mark_restored_connections_unconfirmed(target, keys) == 1
            assert mark_restored_connections_unconfirmed(target, keys) == 0
        with engine.connect() as target:
            report = verify_connection_state(target, keys)
            saved = target.execute(select(IntegrationActionRunORM.__table__)).mappings().one()
            assert saved["state"] == "unknown" and saved["lease_token"] is None and saved["attempts"] == 1
            assert report["legacy_id_only_records"] == 0
        assert len(fixture.provider.calls) == 1
    finally:
        engine.dispose()


def test_metadata_or_unaccounted_ciphertext_corruption_fails_before_restore_publication(fixture, tmp_path):
    seed(fixture)
    path = tmp_path / "tampered.sqlite3"
    engine = offline_copy(fixture, path)
    keys = fixture.box.keys()
    try:
        with engine.begin() as target:
            first = target.execute(select(IntegrationSourceBlockORM.__table__)).mappings().first()
            assert first is not None
            target.execute(db_table(IntegrationSourceBlockORM).update().where(IntegrationSourceBlockORM.id == first["id"])
                           .values(created_at=first["created_at"] + timedelta(seconds=1)))
        with engine.connect() as target, pytest.raises(ConnectionArchiveError) as error:
            verify_connection_state(target, keys)
        assert error.value.code == "result_block_identity"
        with engine.begin() as target:
            target.execute(db_table(IntegrationSourceBlockORM).update().where(IntegrationSourceBlockORM.id == first["id"])
                           .values(created_at=first["created_at"]))
            target.execute(db_table(IntegrationSourceBlockORM).insert().values(**{**dict(first), "id": str(uuid4()), "category": "unaccounted"}))
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with engine.begin() as target, pytest.raises(ConnectionArchiveError):
            mark_restored_connections_unconfirmed(target, keys)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    finally:
        engine.dispose()


def test_event_identity_cannot_be_swapped_even_if_its_encrypted_details_are_unchanged(fixture, tmp_path):
    seed(fixture)
    engine = offline_copy(fixture, tmp_path / "event-identity.sqlite3")
    try:
        with engine.begin() as target:
            item = target.execute(select(IntegrationConnectionEventORM.__table__)).mappings().first()
            assert item is not None
            target.execute(db_table(IntegrationConnectionEventORM).update().where(IntegrationConnectionEventORM.id == item["id"])
                           .values(actor_id="another-actor"))
        with engine.connect() as target, pytest.raises(ConnectionArchiveError) as error:
            verify_connection_state(target, fixture.box.keys())
        assert error.value.code == "event_identity"
    finally:
        engine.dispose()


def test_absent_family_needs_no_keys_and_partial_family_never_passes(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'absent.sqlite3').as_posix()}")
    try:
        with engine.connect() as target:
            assert verify_connection_state(target, [])["present"] is False
        db_table(IntegrationConnectionORM).create(engine)
        with engine.connect() as target, pytest.raises(ConnectionArchiveError) as error:
            verify_connection_state(target, [])
        assert error.value.code == "partial_connection_schema"
    finally:
        engine.dispose()
