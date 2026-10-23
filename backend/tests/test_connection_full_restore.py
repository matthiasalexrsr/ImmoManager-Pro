"""Portable synthetic full backup of encrypted private connection state and all its proofs.

This exercises the product backup archive (not only the offline family copier).
The original key file and all authenticated result blocks must survive, and
recovered state must be verifiable using only the restored keyring.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

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
from backend.services import full_backup, secret_box
from backend.services.integrations import connection_storage as storage
from backend.services.integrations.connection_archive import verify_connection_state
from backend.services.integrations.connection_types import SourceObservation
from backend.tests import test_connection_framework as cases
from backend.tests import test_operations_backup as backup_cases

clean = cases.clean
fixture = cases.fixture
installation = backup_cases.installation

MODELS = (IntegrationConnectionORM, IntegrationConnectionSecretORM, IntegrationConnectionMappingORM,
          IntegrationActionRunORM, IntegrationSourceBlockORM, IntegrationConnectionEventORM,
          IntegrationActionAttemptORM, IntegrationRunCursorORM)


def test_complete_application_backup_restores_connections_private_keys_original_results_and_receipts(
        fixture: SimpleNamespace, installation: SimpleNamespace, tmp_path: Path):
    fixture.box = installation.box
    fixture.service.box = installation.box
    source = {"external_key": "fixture-property", "unknown_extension": {"deep": [1, "ü"]}}
    connection = cases.new_connection(fixture)
    fixture.service.observe(
        connection["id"],
        SourceObservation(idempotency_key=str(uuid4()), source_kind="property",
                          external_key="external-fixture", source_sha256=storage.digest(source), raw=source),
        fixture.owner.id,
    )
    run = cases.dispatch(fixture, connection, cases.prepare(fixture, connection))
    assert run["state"] == "completed" and run["result_bytes"] > 0

    engine = create_engine(f"sqlite:///{installation.db.as_posix()}")
    try:
        from backend.dependencies import store
        with storage.work(store, fixture.owner.id) as unit, engine.begin() as destination:
            for model in MODELS:
                records = ([storage.values(row) for row in storage.memory(unit, model).values()]
                           if unit.db is None else
                           [dict(row) for row in unit.db.execute(select(cast(Table, model.__table__))).mappings()])
                if records:
                    destination.execute(cast(Table, model.__table__).insert(), records)
        with engine.connect() as db:
            pre = verify_connection_state(db, installation.box.keys())
            assert pre["legacy_id_only_records"] == 0
            assert pre["verified_result_bytes"] == run["result_bytes"]
        archived = full_backup.create_full_backup("manual", installation.sources)
        backup = installation.sources.root / archived["archive"]
        assert full_backup.verify_archive(backup, expected_sha256=archived["sha256"])["ok"]
        probe = full_backup.restore_probe(sources=installation.sources)
        assert probe["ok"]
        restored = tmp_path / "portable-restored"
        published = full_backup.restore_archive(backup, restored)
        assert published["revision"]
        assert (restored / "secrets" / "keyring.json").read_bytes() == installation.box.key_file.read_bytes()
        # The restored database is wholly separate from the source and the app
        # is not started or allowed to run its schedulers or external providers.
        recovered_engine = create_engine(f"sqlite:///{(restored / 'immo_manager.db').as_posix()}")
        try:
            keys = secret_box.SecretBox(restored / "secrets" / "keyring.json").keys()
            with recovered_engine.connect() as db:
                after = verify_connection_state(db, keys)
            assert after["table_counts"] == pre["table_counts"]
            assert after["verified_result_bytes"] == pre["verified_result_bytes"]
            assert after["key_ids"] == pre["key_ids"]
            assert after["legacy_id_only_records"] == 0
        finally:
            recovered_engine.dispose()
    finally:
        engine.dispose()



def test_portable_probe_and_publication_refuse_a_complete_but_cryptographically_corrupt_archive(
        installation: SimpleNamespace, tmp_path: Path):
    """ZIP SHA and SQLite integrity are not proof that private ciphertext opens."""
    from datetime import datetime

    import pytest

    moment = datetime(2026, 10, 16)
    identifier = "synthetic-corrupt-connection"
    original = installation.box.seal('{"synthetic":true}', f"connection/{identifier}/config")
    damaged = original[:-12] + ("A" if original[-12] != "A" else "B") + original[-11:]
    engine = create_engine(f"sqlite:///{installation.db.as_posix()}")
    try:
        with engine.begin() as db:
            db.execute(cast(Table, IntegrationConnectionORM.__table__).insert(), {
                "id": identifier, "provider_id": "contract-wizard", "name": "Nur beschädigter Prüffall",
                "enabled": False, "is_default": False, "archived": False, "revision": 1,
                "config_token": damaged, "secret_refs": {}, "legacy_source_hash": None,
                "created_by": "synthetic-actor", "created_at": moment, "updated_at": moment,
            })
        saved = full_backup.create_full_backup("manual", installation.sources)
        archive = installation.sources.root / saved["archive"]
        # Manifest and file digests are perfectly consistent even though an
        # encrypted payload was damaged before the archive was created.
        assert full_backup.verify_archive(archive)["ok"]
        with pytest.raises(full_backup.BackupError, match="Geschützte Verbindungsnachweise"):
            full_backup.restore_probe(sources=installation.sources)
        fresh = tmp_path / "must-not-publish"
        with pytest.raises(full_backup.BackupError, match="Geschützte Verbindungsnachweise"):
            full_backup.restore_archive(archive, fresh)
        assert not (fresh / "immo_manager.db").exists()
        with engine.connect() as db:
            row = db.execute(select(IntegrationConnectionORM.config_token)
                             .where(IntegrationConnectionORM.id == identifier)).scalar_one()
            assert row == damaged  # source is never silently repaired
    finally:
        engine.dispose()



def test_full_restore_marks_unacknowledged_external_action_unknown_and_never_reissues_it(
        fixture: SimpleNamespace, installation: SimpleNamespace, tmp_path: Path, monkeypatch):
    import pytest
    from fastapi import HTTPException

    # The sole external writer is a synthetic callback whose count is the
    # independent replay oracle. Only the durable acknowledgement is lost.
    fixture.box = installation.box
    fixture.service.box = installation.box
    connection = cases.new_connection(fixture)
    run = cases.prepare(fixture, connection, "send", {"text": "synthetic-only"})
    def lose_acknowledgement(*_args, **_kwargs):
        raise OSError("the synthetic receiver acknowledgement was lost")
    monkeypatch.setattr(fixture.service, "_finish", lose_acknowledgement)
    with pytest.raises(HTTPException) as lost:
        cases.dispatch(fixture, connection, run)
    assert lost.value.status_code == 503
    assert len(fixture.provider.calls) == 1

    from backend.dependencies import store
    source_engine = create_engine(f"sqlite:///{installation.db.as_posix()}")
    try:
        with storage.work(store, fixture.owner.id) as unit, source_engine.begin() as dest:
            for model in MODELS:
                records = ([storage.values(row) for row in storage.memory(unit, model).values()]
                           if unit.db is None else
                           [dict(row) for row in unit.db.execute(select(cast(Table, model.__table__))).mappings()])
                if records:
                    dest.execute(cast(Table, model.__table__).insert(), records)
        event = full_backup.create_full_backup("manual", installation.sources)
        archive = installation.sources.root / event["archive"]
        probe = full_backup.restore_probe(sources=installation.sources)
        assert probe["ok"] and probe["checks"]["private_connections"]["present"]
        assert probe["checks"]["private_connections"]["restored_unconfirmed"] == 0  # read-only probe

        target = tmp_path / "restored-after-external-attempt"
        result = full_backup.restore_archive(archive, target)
        assert result["revision"]
        from backend.db.integration_connection_models import IntegrationActionRunORM
        engine = create_engine(f"sqlite:///{(target / 'immo_manager.db').as_posix()}")
        try:
            with engine.connect() as db:
                assert db.scalar(select(IntegrationActionRunORM.state).where(
                    IntegrationActionRunORM.id == run["id"])) == "unknown"
                verified = verify_connection_state(
                    db, secret_box.SecretBox(target / "secrets" / "keyring.json").keys())
            assert verified["present"] and verified["legacy_id_only_records"] == 0
        finally:
            engine.dispose()
        assert len(fixture.provider.calls) == 1
    finally:
        source_engine.dispose()
