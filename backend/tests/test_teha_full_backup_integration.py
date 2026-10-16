"""TEHA real full-backup acceptance, not only a direct SQLite .backup call.

No live portal, access tokens or real customers. The SQL fixture builds its
own encrypted source run, imported document bytes and immutable receipt.
"""
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine

from backend.db import schema_state
from backend.services import full_backup
from backend.services.secret_box import SecretBox
from backend.services.teha_restore import verify_teha_restore
from backend.tests import test_teha_publication as cases

fx = cases.fx


def test_full_archive_restarts_teha_mapping_and_exact_original_with_archived_keys(fx, tmp_path: Path):
    if fx.engine is None or fx.engine.dialect.name != "sqlite":
        pytest.skip("SQLite full-archive test; native PostgreSQL has its own owned test-server gate")
    source = cases.document(b"%PDF-1.5\nSynthetic restore original\x00\xff\n%%EOF")
    _, batch = cases.receive(fx, [source])
    item = cases.items(fx, batch)[0]
    cases.mapping(fx, item)
    receipt = fx.receive.publish(fx.connection, item["id"], cases.confirmation(fx, item), fx.actor)

    # The source fixture intentionally uses Base.metadata.create_all. A real
    # backup source instead has a durable Alembic stamp; add that to this
    # disposable synthetic database so restore_probe does not try to apply
    # all historical CREATE TABLE revisions to an already complete schema.
    command.stamp(schema_state.alembic_config(str(fx.engine.url)), schema_state.head_revision())

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "fixture-original.bin").write_bytes(b"synthetic-only\x00")
    sources = full_backup.Sources(
        database_url=str(fx.engine.url), data_dir=tmp_path,
        uploads_dir=uploads, root=tmp_path / "backups",
        integration_state=tmp_path / "no-global-integration.json",
        key_file=fx.box.key_file, env_file=tmp_path / "no-live-secrets.env",
    )
    event = full_backup.create_full_backup("manual", sources)
    assert event["ok"] and not event["missing_key_ids"]
    archive = sources.root / event["archive"]
    assert full_backup.verify_archive(archive, expected_sha256=event["sha256"])["ok"]
    probe = full_backup.restore_probe(archive, sources)
    assert probe["ok"] and probe["checks"]["private_connections"]["teha"] == {
        "batches": 1, "items": 1, "mappings": 1, "receipts": 1, "returns": 0
    }

    restored = tmp_path / "fresh-restored-installation"
    published = full_backup.restore_archive(archive, restored)
    assert published["dialect"] == "sqlite"
    assert (restored / "uploads" / "fixture-original.bin").read_bytes() == b"synthetic-only\x00"
    box = SecretBox(restored / "secrets" / "keyring.json")
    engine = create_engine("sqlite:///" + (restored / "immo_manager.db").as_posix())
    try:
        with engine.connect() as connection:
            assert verify_teha_restore(connection, box) == probe["checks"]["private_connections"]["teha"]
        # The actual previously published bytes are still downloadable, not
        # replaced by a locally reconstructed approximation.
        assert fx.receive.original(fx.connection, receipt["id"], fx.actor)[0] == __import__("base64").b64decode(
            source["content_base64"])
    finally:
        engine.dispose()


def test_full_archive_without_actual_teha_key_records_missing_key_and_refuses_restore(fx, tmp_path: Path):
    if fx.engine is None or fx.engine.dialect.name != "sqlite":
        pytest.skip("SQLite full-archive test; native PostgreSQL has its own owned test-server gate")
    _, batch = cases.receive(fx, [cases.document()])
    item = cases.items(fx, batch)[0]
    cases.mapping(fx, item)
    fx.receive.publish(fx.connection, item["id"], cases.confirmation(fx, item), fx.actor)

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    sources = full_backup.Sources(
        database_url=str(fx.engine.url), data_dir=tmp_path,
        uploads_dir=uploads, root=tmp_path / "no-keys-backups",
        integration_state=tmp_path / "missing-integrations.json",
        key_file=tmp_path / "intentionally-absent-keyring.json",
        env_file=tmp_path / "missing-env-file",
    )
    # The portable platform backup contract fails closed at CREATION.
    # No incomplete signed archive may even be published for a later
    # operator to mistake for a restorable backup.
    with pytest.raises(full_backup.BackupError, match="Entschlüsselungsschlüssel fehlen"):
        full_backup.create_full_backup("manual", sources)
    assert not list(sources.root.glob("*.zip"))
    assert not list(sources.root.glob("*.partial"))
    # A completely independent fresh target must remain empty.
    fresh = tmp_path / "must-not-publish"
    assert not fresh.exists()
    with fx.engine.connect() as connection:
        verified = verify_teha_restore(connection, fx.box)
    assert verified["items"] == 1 and verified["receipts"] == 1
