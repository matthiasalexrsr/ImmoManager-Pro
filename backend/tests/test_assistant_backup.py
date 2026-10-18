"""Offline AI archive inventory/ownership/bytes and full portable restore proofs."""

import base64
import hashlib
import json
import zipfile
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import MetaData, Table, create_engine, select, text, update

from backend.services import assistant_backup as proof
from backend.services import full_backup, secret_box
from backend.tests.test_operations_backup import installation as installation

OWNER = "staff"
IDS = {"assistant_conversations": "conversation-fixture", "assistant_runs": "run-fixture",
       "assistant_messages": "message-fixture", "assistant_attachments": "attachment-fixture",
       "assistant_proposals": "proposal-fixture"}
ORIGINAL = b"Synthetic selected document\x00\xff"


def seed(connection, box, *, state="running"):
    metadata = MetaData()
    tables = {name: Table(name, metadata, autoload_with=connection) for name in proof.TABLES}
    key = "assistant-private/files/" + hashlib.sha256(OWNER.encode()).hexdigest() + "/" + "a" * 32
    payloads = {
        "assistant_conversations": {"title": "Private conversation", "active_run_id": IDS["assistant_runs"], "_contexts": []},
        "assistant_runs": {"attachment_ids": [IDS["assistant_attachments"]], "_proposal_ids": [IDS["assistant_proposals"]],
                           "retry_of": None, "_lease": "old-worker", "response": "Preserved partial answer"},
        "assistant_messages": {"role": "user", "content": "Private request", "run_id": IDS["assistant_runs"], "attachment_ids": [IDS["assistant_attachments"]]},
        "assistant_attachments": {"_storage_key": key, "byte_length": len(ORIGINAL), "sha256": hashlib.sha256(ORIGINAL).hexdigest(), "name": "original.txt"},
        "assistant_proposals": {"run_id": IDS["assistant_runs"], "payload": {"kind": "note"}, "decision": None},
    }
    for name in ("assistant_conversations", "assistant_attachments", "assistant_runs", "assistant_messages", "assistant_proposals"):
        row = dict(id=IDS[name], owner_id=OWNER, revision=1, state=state if name == "assistant_runs" else "active",
                   created_at=datetime(2026, 10, 18), updated_at=datetime(2026, 10, 18))
        if name != "assistant_conversations":
            row["conversation_id"] = IDS["assistant_conversations"]
        row["payload_token"] = box.seal(json.dumps(payloads[name]), proof._context(name, row))
        connection.execute(tables[name].insert(), row)
    return SimpleNamespace(key=key, payloads=payloads, tables=tables, box=box)


@pytest.fixture
def isolated(tmp_path):
    path = tmp_path / "private.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    box = secret_box.SecretBox(tmp_path / "keys.json")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users(id TEXT PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO users VALUES ('staff'), ('other')")
        for name in proof.TABLES:
            child = ",conversation_id TEXT NOT NULL" if name != "assistant_conversations" else ""
            connection.exec_driver_sql(f"CREATE TABLE {name}(id TEXT PRIMARY KEY,owner_id TEXT,revision INTEGER,state TEXT,payload_token TEXT,created_at DATETIME,updated_at DATETIME{child})")
        fixture = seed(connection, box)
    uploads = tmp_path / "uploads"
    original = uploads / fixture.key
    original.parent.mkdir(parents=True)
    original.write_bytes(ORIGINAL)
    yield SimpleNamespace(path=path, engine=engine, uploads=uploads, **fixture.__dict__)
    engine.dispose()


def rewrite(fixture, name, data=None, **metadata):
    with fixture.engine.begin() as connection:
        table = fixture.tables[name]
        row = dict(connection.execute(select(table)).mappings().one())
        row.update(metadata)
        if data is not None:
            metadata["payload_token"] = fixture.box.seal(json.dumps(data), proof._context(name, row))
        connection.execute(update(table).values(**metadata))


def test_saved_task_completion_survives_later_normal_deletion(isolated):
    with isolated.engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE tasks(id TEXT PRIMARY KEY,title TEXT)')
        connection.exec_driver_sql('CREATE TABLE workspace_drafts(id TEXT PRIMARY KEY,owner_user_id TEXT)')
        connection.exec_driver_sql("INSERT INTO tasks VALUES ('saved-task','Human confirmed')")
        connection.exec_driver_sql("INSERT INTO workspace_drafts VALUES ('saved-draft','staff')")
    record = {'kind': 'task', 'id': 'saved-task', 'href': '/tasks?focus_id=saved-task', 'title': 'Human confirmed'}
    saved = {**isolated.payloads['assistant_proposals'], 'payload': {'kind': 'task'},
             'record': record, 'completion': {'actor_id': OWNER},
             'handoff': {'draft_id': 'saved-draft', 'record': record}}
    rewrite(isolated, 'assistant_proposals', saved, state='saved')
    with isolated.engine.connect() as connection:
        assert proof.verify(connection, isolated.box.keys(), uploads=isolated.uploads)['rows'] == 5
    with isolated.engine.begin() as connection:
        connection.exec_driver_sql("DELETE FROM tasks WHERE id='saved-task'")
    with isolated.engine.connect() as connection:
        assert proof.verify(connection, isolated.box.keys(), uploads=isolated.uploads)['missing_saved_records'] == 1
    saved['completion']['actor_id'] = 'other'
    rewrite(isolated, 'assistant_proposals', saved, state='saved')
    with isolated.engine.connect() as connection, pytest.raises(proof.AssistantBackupError):
        proof.verify(connection, isolated.box.keys(), uploads=isolated.uploads)


def test_final_invoice_private_receipt_survives_actual_full_backup_and_restore(installation, tmp_path, monkeypatch):
    from uuid import uuid4

    from sqlalchemy.orm import Session, sessionmaker

    from backend import auth
    from backend.assistant_models import ConversationCreate, ProposalApply, ProposalPreview, RunCreate
    from backend.models import PropertyCreate
    from backend.repositories import SQLAlchemyStore
    from backend.services import (
        assistant,
        assistant_context,
        assistant_handoff,
        assistant_runner,
        document_versions,
        file_storage,
    )
    from backend.services.integrations import connection_storage
    from backend.services.portable_runtime import inventory

    engine = create_engine(installation.sources.database_url)
    monkeypatch.setattr(auth, '_user_store', auth.SQLUserStore(sessionmaker(bind=engine)))
    auth.update_user(OWNER, {'portfolio_access': 'selected', 'portfolio_ids': ['pf1']})
    monkeypatch.setattr(secret_box, 'default_secret_box', lambda: installation.box)
    monkeypatch.setattr(connection_storage, 'default_secret_box', lambda: installation.box)
    monkeypatch.setattr(file_storage, '_storage', file_storage.LocalStorage(installation.sources.uploads_dir))
    monkeypatch.setattr(assistant, 'wake', lambda *args: None)
    original = b'Netto 100,00 EUR; MwSt 19,00 EUR; Gesamt 119,00 EUR; unveraenderliches Original'
    try:
        with Session(engine) as session:
            target = SQLAlchemyStore(session)
            prop = target.create_property(PropertyCreate(portfolio_id='pf1', name='Receipt property', property_type='residential'))
            chat = assistant.create_conversation(target, OWNER, ConversationCreate(idempotency_key=str(uuid4())))
            uploaded = assistant.add_attachment(target, OWNER, chat['id'], original, 'Receipt.txt')
            selection = {'property_ids': [prop.id]}
            bundle = assistant_context.build_context(target, selection, OWNER)
            source = assistant_handoff.attachment_evidence(target, OWNER, uploaded['id'])
            values = {'supplier': 'Testbetrieb', 'invoice_date': '2026-10-18', 'net_amount': '100.00',
                      'vat_rate': '19.00', 'vat_amount': '19.00', 'gross_amount': '119.00', 'property_id': prop.id}
            proposed = {'kind': 'invoice', 'anchor': {'kind': 'property', 'id': prop.id}, 'values': values,
                        'evidence': [{key: row[key] for key in ('kind', 'id', 'revision', 'sha256')}
                                     for row in [*bundle['sources'], source]]}
            run = assistant.submit(target, OWNER, chat['id'], RunCreate(expected_revision=chat['revision'],
                idempotency_key=str(uuid4()), content='Original pruefen', context=selection, attachment_ids=[uploaded['id']]))
            assistant_runner.run(target, run['id'], OWNER,
                execute=lambda *args: {'text': 'Manueller Testvorschlag', 'proposals': [proposed]})
            proposal = assistant.list_records(target, OWNER, assistant.Proposal, conversation_id=chat['id'])['items'][0]
            review = assistant.proposal_preview(target, OWNER, proposal['id'], ProposalPreview(expected_revision=proposal['revision']))['review']
            prepared = assistant.decide_proposal(target, OWNER, proposal['id'], ProposalApply(expected_revision=proposal['revision'],
                idempotency_key=str(uuid4()), review_hash=review['review_hash']))['proposal']
            final = assistant_handoff.save_proposal(target, OWNER, proposal['id'], assistant_handoff.ProposalSave(
                expected_revision=prepared['revision'], idempotency_key=str(uuid4()), values=values))
            document_id = final['record']['document_id']
        references, _ = inventory(installation.db)
        assert not any(key.startswith('assistant-archive/') for key in references)
        with engine.connect() as connection:
            proof.verify(connection, installation.box.keys(), uploads=installation.sources.uploads_dir)
        installation.sources.passphrase = 'synthetic-private-receipt-only'
        event = full_backup.create_full_backup(sources=installation.sources)
        saved = installation.sources.root / event['archive']
        assert full_backup.restore_probe(saved, installation.sources)['ok']
        restored = tmp_path / 'restored-receipt'
        result = full_backup.restore_archive(saved, restored, passphrase=installation.sources.passphrase)
        assert result['readiness'] == 'data_verified'
        recovered = create_engine('sqlite:///' + (restored / 'immo_manager.db').as_posix())
        try:
            monkeypatch.setattr(auth, '_user_store', auth.SQLUserStore(sessionmaker(bind=recovered)))
            restored_box = secret_box.SecretBox(restored / 'secrets/keyring.json')
            monkeypatch.setattr(secret_box, 'default_secret_box', lambda: restored_box)
            monkeypatch.setattr(connection_storage, 'default_secret_box', lambda: restored_box)
            with Session(recovered) as session, document_versions.work(SQLAlchemyStore(session), OWNER) as unit:
                version = document_versions.head(unit, document_id)
                assert version is not None and document_versions.original_bytes(unit, version) == original
            with recovered.connect() as connection:
                checked = proof.verify(connection, restored_box.keys(), uploads=restored / 'uploads')
                assert checked['rows'] >= 4 and not checked.get('missing_saved_records')
        finally:
            recovered.dispose()
    finally:
        engine.dispose()


def test_snapshot_inventory_decrypts_hidden_remote_key_without_runtime_keyring(isolated, monkeypatch):
    monkeypatch.setattr(secret_box, "default_secret_box", lambda: pytest.fail("Ambient keys must not be consulted"))
    assert proof.references(isolated.path, isolated.box.keys()) == {isolated.key}
    with isolated.engine.connect() as connection:
        result = proof.verify(connection, isolated.box.keys(), uploads=isolated.uploads)
    assert result["rows"] == 5 and result["attachments"] == 1
    assert result["table_counts"] == {name: 1 for name in proof.TABLES}
    with pytest.raises(proof.AssistantBackupError):
        proof.references(isolated.path, [])


@pytest.mark.parametrize("family", ["assistant_conversations", "assistant_messages", "assistant_runs", "assistant_attachments", "assistant_proposals"])
def test_payload_envelope_cannot_be_rebound_to_other_owner(isolated, family):
    rewrite(isolated, family, owner_id="other")
    with isolated.engine.connect() as connection, pytest.raises(proof.AssistantBackupError):
        proof.verify(connection, isolated.box.keys(), uploads=isolated.uploads)


def test_cross_conversation_run_reference_is_rejected(isolated):
    rewrite(isolated, "assistant_messages", {"run_id": "missing-private-run"})
    with isolated.engine.connect() as connection, pytest.raises(proof.AssistantBackupError):
        proof.verify(connection, isolated.box.keys(), uploads=isolated.uploads)


def test_file_changed_after_archive_manifest_verification_is_rejected(isolated):
    (isolated.uploads / isolated.key).write_bytes(b"changed original")
    with isolated.engine.connect() as connection, pytest.raises(proof.AssistantBackupError, match="attachment_original_changed"):
        proof.verify(connection, isolated.box.keys(), uploads=isolated.uploads)


@pytest.mark.parametrize("key", ["../../outside", "assistant-private/files/" + "f" * 64 + "/" + "a" * 32])
def test_attachment_locator_stays_in_its_exact_owner_namespace(isolated, key):
    rewrite(isolated, "assistant_attachments", {**isolated.payloads["assistant_attachments"], "_storage_key": key})
    with isolated.engine.connect() as connection, pytest.raises(proof.AssistantBackupError):
        proof.verify(connection, isolated.box.keys(), uploads=isolated.uploads)


@pytest.mark.parametrize("state", ["queued", "running"])
def test_restore_blocks_active_runs_and_is_idempotent_without_provider_actions(isolated, state):
    rewrite(isolated, "assistant_runs", state=state)
    with isolated.engine.begin() as connection:
        result = proof.verify(connection, isolated.box.keys(), uploads=isolated.uploads, normalize=True)
        assert result["restored_unknown"] == 1
    with isolated.engine.begin() as connection:
        again = proof.verify(connection, isolated.box.keys(), uploads=isolated.uploads, normalize=True)
        assert again["restored_unknown"] == 0
        run = dict(connection.execute(select(isolated.tables["assistant_runs"])).mappings().one())
        data = proof._open(isolated.box.keys(), run["payload_token"], proof._context("assistant_runs", run))
        assert run["state"] == "unknown" and run["revision"] == 2 and "_lease" not in data
        assert data["response"] == "Preserved partial answer" and data["error"]["code"] == "restore_interrupted"
        conversation = dict(connection.execute(select(isolated.tables["assistant_conversations"])).mappings().one())
        assert proof._open(isolated.box.keys(), conversation["payload_token"], proof._context("assistant_conversations", conversation))["active_run_id"] is None


def vault_file(uploads, box, *, actor=OWNER, path_actor=None):
    identity = hashlib.sha256(actor.encode()).hexdigest()
    data = {"version": 1, "files": {"auth.json": base64.b64encode(b'{"token":"synthetic-private-credential"}').decode()}, "public": {"connected": True}}
    token = box.seal(json.dumps(data), "assistant-account:v1:" + identity + ":codex")
    path_hash = hashlib.sha256((path_actor or actor).encode()).hexdigest()
    path = uploads / proof.VAULT_PREFIX / path_hash / "codex.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "sealed": token}), encoding="utf-8")
    return path


def test_vault_original_is_owner_context_bound_and_requires_its_archived_key(isolated):
    vault_file(isolated.uploads, isolated.box)
    captured, ids = proof.capture_vaults(isolated.uploads, isolated.box.keys())
    assert len(captured) == 1 and ids == {isolated.box.active_key_id()}
    assert b"synthetic-private-credential" not in next(iter(captured.values()))
    with pytest.raises(proof.AssistantBackupError):
        proof.capture_vaults(isolated.uploads, [])
    vault_file(isolated.uploads, isolated.box, path_actor="other")
    with pytest.raises(proof.AssistantBackupError):
        proof.capture_vaults(isolated.uploads, isolated.box.keys())


def test_partial_assistant_family_is_not_silently_skipped(isolated):
    with isolated.engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE assistant_proposals")
    with isolated.engine.connect() as connection, pytest.raises(proof.AssistantBackupError, match="partial_assistant_schema"):
        proof.verify(connection, isolated.box.keys(), uploads=isolated.uploads)


def test_completed_run_keeps_original_envelope_and_revision(isolated):
    rewrite(isolated, "assistant_runs", state="completed")
    with isolated.engine.begin() as connection:
        original = connection.execute(select(isolated.tables["assistant_runs"])).mappings().one()
        assert proof.verify(connection, isolated.box.keys(), uploads=isolated.uploads, normalize=True)["restored_unknown"] == 0
        recovered = connection.execute(select(isolated.tables["assistant_runs"])).mappings().one()
        assert dict(original) == dict(recovered)


def test_restore_proof_rejects_referenced_private_draft_owned_by_another_actor(isolated):
    with isolated.engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE workspace_drafts(id TEXT PRIMARY KEY,owner_user_id TEXT)")
        connection.exec_driver_sql("INSERT INTO workspace_drafts VALUES('foreign-draft','other')")
    rewrite(isolated, "assistant_proposals", {"run_id": IDS["assistant_runs"], "handoff": {"draft_id": "foreign-draft"}})
    with isolated.engine.connect() as connection, pytest.raises(proof.AssistantBackupError, match="assistant_draft_owner_mismatch"):
        proof.verify(connection, isolated.box.keys(), uploads=isolated.uploads)


def test_full_backup_restores_remote_attachment_vault_and_quarantines_running_snapshot(installation, tmp_path, monkeypatch):
    fixture = installation
    engine = create_engine(f"sqlite:///{fixture.db.as_posix()}")
    try:
        with engine.begin() as connection:
            selected = seed(connection, fixture.box)
        vault = vault_file(fixture.sources.uploads_dir, fixture.box)
        from backend.services.file_storage import S3Storage
        from backend.tests.test_platform_storage_restore import S3Protocol
        calls = []
        class Remote(S3Protocol):
            def get_object(self, *, Bucket, Key):
                calls.append(Key)
                return super().get_object(Bucket=Bucket, Key=Key)
        remote = Remote()
        remote.objects[selected.key] = ORIGINAL
        fixture.sources.file_storage = S3Storage(bucket="fixture", client=remote)
        legacy = fixture.sources.uploads_dir / selected.key
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"stale local cache must not replace authoritative S3 original")
        runtime = fixture.data / "assistant-runtime" / "do-not-copy"
        runtime.mkdir(parents=True)
        (runtime / "auth.json").write_bytes(b"synthetic-plaintext-runtime")
        monkeypatch.setattr(secret_box, "default_secret_box", lambda: pytest.fail("No live key fallback"))
        saved = full_backup.create_full_backup(sources=fixture.sources)
        archive = fixture.sources.root / saved["archive"]
        with zipfile.ZipFile(archive) as zipped:
            assert zipped.read("uploads/" + selected.key) == ORIGINAL
            assert zipped.read("uploads/" + vault.relative_to(fixture.sources.uploads_dir).as_posix()) == vault.read_bytes()
            assert not any("assistant-runtime" in name for name in zipped.namelist())
            assert selected.key in json.loads(zipped.read("manifest.json"))["attachments"]["references"]
        assert calls == [selected.key]
        probe = full_backup.restore_probe(archive, fixture.sources)
        assert probe["checks"]["private_connections"]["assistant"]["rows"] == 5
        assert probe["checks"]["private_connections"]["assistant"]["vaults"] == 1
        fresh = tmp_path / "fresh-assistant"
        assert full_backup.restore_archive(archive, fresh)["readiness"] == "data_verified"
        recovered = create_engine(f"sqlite:///{(fresh / 'immo_manager.db').as_posix()}")
        try:
            with recovered.connect() as connection:
                assert connection.execute(text("SELECT state FROM assistant_runs")).scalar_one() == "unknown"
                restored = proof.verify(connection, fixture.box.keys(), uploads=fresh / "uploads")
                assert restored["rows"] == 5 and restored["vaults"] == 1
        finally:
            recovered.dispose()
        with engine.connect() as connection:
            assert connection.execute(text("SELECT state FROM assistant_runs")).scalar_one() == "running"
    finally:
        engine.dispose()


def test_full_backup_uses_attachment_identity_from_database_snapshot(installation, monkeypatch):
    fixture = installation
    engine = create_engine(f"sqlite:///{fixture.db.as_posix()}")
    with engine.begin() as connection:
        selected = seed(connection, fixture.box)
    copier = full_backup.sqlite_online_copy
    live_key = selected.key[:-32] + "b" * 32

    def copy_then_change_live(source, target):
        copier(source, target)
        if source == fixture.db:
            with engine.begin() as connection:
                table = selected.tables["assistant_attachments"]
                row = dict(connection.execute(select(table)).mappings().one())
                changed = {**selected.payloads["assistant_attachments"], "_storage_key": live_key}
                token = fixture.box.seal(json.dumps(changed), proof._context("assistant_attachments", row))
                connection.execute(update(table).values(payload_token=token))

    monkeypatch.setattr(full_backup, "sqlite_online_copy", copy_then_change_live)
    fixture.sources.file_storage = SimpleNamespace(get=lambda key: ORIGINAL if key == selected.key else None)
    try:
        event = full_backup.create_full_backup(sources=fixture.sources)
        with zipfile.ZipFile(fixture.sources.root / event["archive"]) as zipped:
            manifest = json.loads(zipped.read("manifest.json"))
            assert selected.key in manifest["attachments"]["references"] and live_key not in manifest["attachments"]["references"]
            assert zipped.read("uploads/" + selected.key) == ORIGINAL
    finally:
        engine.dispose()


def test_vault_only_environment_key_is_archived_and_needed_even_without_assistant_rows(installation, tmp_path):
    env_key = secret_box.new_key_material()
    vault_box = secret_box.SecretBox(tmp_path / "unused-env-keyring.json", env_keys=env_key)
    vault_file(installation.sources.uploads_dir, vault_box)
    installation.sources.env_secret_keys = env_key
    installation.sources.runtime_bytes = json.dumps({"secret_keys": "", "file_storage_backend": "local"}).encode()
    installation.sources.passphrase = "synthetic-backup-passphrase"
    event = full_backup.create_full_backup(sources=installation.sources)
    archive = installation.sources.root / event["archive"]
    with zipfile.ZipFile(archive) as zipped:
        manifest = json.loads(zipped.read("manifest.json"))
        assert vault_box.active_key_id() in manifest["secrets"]["needed_key_ids"]
        assert env_key.encode() not in zipped.read("manifest.json")
    fresh = tmp_path / "env-vault-restored"
    full_backup.restore_archive(archive, fresh, passphrase=installation.sources.passphrase)
    archived = json.loads((fresh / "runtime.from-backup.json").read_text(encoding="utf-8"))
    keys = secret_box.parse_env_keys(archived["secret_keys"])
    assert proof.capture_vaults(fresh / "uploads", keys)[1] == {vault_box.active_key_id()}


def test_consistent_manifest_does_not_hide_corrupted_assistant_original(installation, tmp_path):
    engine = create_engine(f"sqlite:///{installation.db.as_posix()}")
    try:
        with engine.begin() as connection:
            selected = seed(connection, installation.box)
    finally:
        engine.dispose()
    installation.sources.file_storage = SimpleNamespace(get=lambda key: ORIGINAL if key == selected.key else None)
    event = full_backup.create_full_backup(sources=installation.sources)
    with zipfile.ZipFile(installation.sources.root / event["archive"]) as zipped:
        entries = {name: zipped.read(name) for name in zipped.namelist()}
    original_path = "uploads/" + selected.key
    entries[original_path] = b"corrupted but internally manifested upload"
    manifest = json.loads(entries["manifest.json"])
    for entry in manifest["files"]:
        if entry["path"] == original_path:
            entry.update(size=len(entries[original_path]), sha256=hashlib.sha256(entries[original_path]).hexdigest())
    entries["manifest.json"] = json.dumps(manifest).encode()
    damaged = tmp_path / "internally-consistent-but-damaged.zip"
    with zipfile.ZipFile(damaged, "w") as zipped:
        for name, raw in entries.items():
            zipped.writestr(name, raw)
    assert full_backup.verify_archive(damaged)["ok"]
    fresh = tmp_path / "must-not-publish"
    with pytest.raises(full_backup.BackupError, match="KI-Gespräche"):
        full_backup.restore_archive(damaged, fresh)
    assert not fresh.exists()


@pytest.mark.parametrize("storage_kind", ["local", "remote"])
def test_backup_creation_refuses_changed_attachment_bytes_and_preserves_good_archive(installation, storage_kind):
    engine = create_engine(f"sqlite:///{installation.db.as_posix()}")
    try:
        with engine.begin() as connection:
            selected = seed(connection, installation.box)
    finally:
        engine.dispose()
    remote = {selected.key: ORIGINAL}
    local = installation.sources.uploads_dir / selected.key
    if storage_kind == "remote":
        installation.sources.file_storage = SimpleNamespace(get=lambda key: remote.get(key))
    else:
        local.parent.mkdir(parents=True)
        local.write_bytes(ORIGINAL)
    saved = full_backup.create_full_backup(sources=installation.sources)
    good = installation.sources.root / saved["archive"]
    if storage_kind == "remote":
        remote[selected.key] = b"changed remote original"
    else:
        local.write_bytes(b"changed local original")
    installation.sources.keep_daily = installation.sources.keep_monthly = installation.sources.keep_pre_upgrade = 0
    with pytest.raises(full_backup.BackupError, match="KI-Anhangoriginal"):
        full_backup.create_full_backup(sources=installation.sources)
    assert list(installation.sources.root.glob("*.zip")) == [good]
    assert full_backup.verify_archive(good)["ok"]
