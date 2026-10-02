"""Source-gone immutable journals; actual Memory and SQLite publication paths."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from sqlalchemy import create_engine

from backend.db.document_version_models import DocumentVersionChunkORM, DocumentVersionORM
from backend.db.orm_models import Base
from backend.models import ContractCreate, DocumentCreate, DocumentPatch, TenantCreate
from backend.services import document_versions as versions
from backend.services.document_version_types import RestoreCommand
from backend.services.document_version_validation import verify_document_versions
from backend.services.full_recovery import create_full_backup, restore_full_backup
from backend.services.recovery_archive import RecoveryError, decrypt_zip, encrypted_zip
from backend.services.recovery_sessions import SessionRestoreError, secure_sqlite_restore
from backend.services.recovery_validation import rebase_file_references, validate_file_references
from backend.tests.test_document_versions import active, archive, command  # noqa: F401 — actual store fixture
from backend.tests.test_full_recovery import (  # noqa: F401 — synthetic full installation
    PASSPHRASE,
    plan,
    runtime_template,
)

ROOT = Path(__file__).resolve().parents[2]


def _image(box, tmp_path):
    image = tmp_path / "immutable-recovery.sqlite"
    if box.engine is not None:
        with closing(sqlite3.connect(box.engine.url.database)) as source, closing(sqlite3.connect(image)) as target:
            source.backup(target)
        return image
    engine = create_engine("sqlite:///" + image.as_posix())
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as db:
            # Preserve actual Memory commands/rows in an owned offline image;
            # a generic JSON business transfer deliberately cannot do this.
            for collection in ("portfolios", "properties", "units", "tenants", "contracts", "documents"):
                table = Base.metadata.tables[collection]
                for row in box.store.__dict__[collection].values():
                    data = row.model_dump(mode="python")
                    db.execute(table.insert().values(**{key: data[key] for key in table.c.keys() if key in data}))
            for model in (DocumentVersionORM, DocumentVersionChunkORM):
                for row in box.store.__dict__.get(model.__tablename__, {}).values():
                    db.execute(model.__table__.insert().values(**{column.name: getattr(row, column.name) for column in model.__table__.columns}))
    finally:
        engine.dispose()
    return image


def _mutate(image, sql, parameters=()):
    with closing(sqlite3.connect(image)) as db:
        guards = db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name IN ('document_versions','document_version_chunks')").fetchall()
        for name, _ in guards:
            db.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
        db.execute("PRAGMA ignore_check_constraints=ON")
        db.execute(sql, parameters)
        for _, guard in guards:
            db.execute(guard)
        db.commit()


def test_actual_archival_chain_sourcegone_and_repeated_absolute_rebase(active, tmp_path):  # noqa: F811 — imported fixture
    box = active
    # Original publication contains NULL property/unit in the snapshot and
    # non-NULL resolved subject fields. This is a supported legacy source.
    tenant = box.store.create_tenant(TenantCreate(full_name="Recovery subject"))
    contract = box.store.create_contract(ContractCreate(tenant_id=tenant.id, property_id=box.prop.id,
        unit_id=box.unit.id, contract_number="Recovery document", start_date="2047-01-01", status="draft"))
    original_path = box.storage.base_dir / "documents" / "original.txt"
    box.store._patch_entity("document", box.document.id, DocumentPatch(property_id=None, unit_id=None,
        contract_id=contract.id, file_url=str(original_path)))
    first, _ = archive(box)
    second = versions.publish(box.store, box.document.id, command(box, "changed"), "actor", source=BytesIO(b"Reviewed replacement"), upload_name="later.txt")
    last = versions.publish(box.store, box.document.id,
        RestoreCommand(**command(box, "restore").model_dump(), source_version_id=first["id"]), "actor", restore=True)
    assert last["number"] == 3 and last["restored_from_id"] == first["id"]
    image = _image(box, tmp_path)
    box.storage.delete("documents/original.txt")
    with closing(sqlite3.connect(image)) as db:
        assert verify_document_versions(db) == 3
        old_snapshot = db.execute("SELECT metadata_snapshot FROM document_versions WHERE id=?", (first["id"],)).fetchone()[0]
        assert json.loads(old_snapshot)["property_id"] is None and json.loads(old_snapshot)["unit_id"] is None
    report = validate_file_references(image, str(box.storage.base_dir), expected_upload_files=set())
    assert report.local_references == 1 and report.local_files == frozenset()
    destination = tmp_path / "restored-uploads"
    assert rebase_file_references(image, str(box.storage.base_dir), destination, expected_upload_files=set()) == 1
    assert validate_file_references(image, str(destination), expected_upload_files=set()).local_references == 1
    with closing(sqlite3.connect(image)) as db:
        assert db.execute("SELECT file_url FROM documents WHERE id=?", (box.document.id,)).fetchone()[0] == str(destination / "documents" / "original.txt")
        assert db.execute("SELECT metadata_snapshot FROM document_versions WHERE id=?", (first["id"],)).fetchone()[0] == old_snapshot
        assert verify_document_versions(db) == 3
        assert db.execute("SELECT predecessor_id FROM document_versions WHERE id=?", (last["id"],)).fetchone()[0] == second["id"]


@pytest.mark.parametrize("change", ["bytes", "oversized", "position", "chunk_portfolio", "size", "hash",
    "snapshot_id", "snapshot_contract", "snapshot_property", "operation", "number", "predecessor", "subject", "source_empty"])
def test_corrupt_bytes_manifest_and_subject_are_rejected_before_rebase_or_family_mutation(active, tmp_path, change):  # noqa: F811
    box = active
    first, _ = archive(box)
    image = _image(box, tmp_path)
    statements = {
        "bytes": ("UPDATE document_version_chunks SET data=? WHERE position=0", (b"Altered bytes",)),
        "oversized": ("UPDATE document_version_chunks SET data=zeroblob(65537) WHERE position=0", ()),
        "position": ("UPDATE document_version_chunks SET position=999 WHERE position=0", ()),
        "chunk_portfolio": ("UPDATE document_version_chunks SET portfolio_id=?", (box.foreign.id,)),
        "size": ("UPDATE document_versions SET size_bytes=size_bytes+1", ()),
        "hash": ("UPDATE document_versions SET sha256=?", ("0" * 64,)),
        "snapshot_id": ("UPDATE document_versions SET metadata_snapshot=json_set(metadata_snapshot,'$.id','foreign')", ()),
        "snapshot_contract": ("UPDATE document_versions SET metadata_snapshot=json_set(metadata_snapshot,'$.contract_id','foreign')", ()),
        "snapshot_property": ("UPDATE document_versions SET metadata_snapshot=json_set(metadata_snapshot,'$.property_id',?)", (box.other.id,)),
        "operation": ("UPDATE document_versions SET operation='upload'", ()),
        "number": ("UPDATE document_versions SET number=2", ()),
        "predecessor": ("UPDATE document_versions SET predecessor_id=id", ()),
        "subject": ("UPDATE document_versions SET property_id=?", (box.other.id,)),
        "source_empty": ("UPDATE documents SET file_url=''", ()),
    }
    _mutate(image, *statements[change])
    before = hashlib.sha256(image.read_bytes()).hexdigest()
    with pytest.raises(RecoveryError):
        rebase_file_references(image, str(box.storage.base_dir), tmp_path / "never-published", expected_upload_files=set())
    assert hashlib.sha256(image.read_bytes()).hexdigest() == before
    # This direct offline security boundary must fail before the callback even
    # when every source/session is in a caller-owned independent transaction.
    from unittest.mock import patch

    from backend.db import session_models
    with patch.object(session_models, "invalidate_restored_sessions", side_effect=AssertionError("Family mutation before document proof")):
        with pytest.raises(SessionRestoreError, match="restore_document_versions_invalid"):
            secure_sqlite_restore(image, {"JWT_SECRET_KEY": "synthetic-offline-key"}, deadline=time.monotonic() + 20)
    assert hashlib.sha256(image.read_bytes()).hexdigest() == before
    assert first["number"] == 1


def test_an_unrelated_cell_or_document_cannot_borrow_an_archived_original(active, tmp_path):  # noqa: F811
    box = active
    archive(box)
    image = _image(box, tmp_path)
    # Simulate another supported legacy source cell; the current Document ORM
    # does not contain this optional OCR column.
    _mutate(image, "ALTER TABLE documents ADD COLUMN ocr_url TEXT")
    _mutate(image, "UPDATE documents SET ocr_url=file_url WHERE id=?", (box.document.id,))
    box.storage.delete("documents/original.txt")
    with pytest.raises(RecoveryError, match="fehlt"):
        validate_file_references(image, str(box.storage.base_dir), expected_upload_files=set())
    _mutate(image, "UPDATE documents SET ocr_url=NULL WHERE id=?", (box.document.id,))
    _mutate(image, "UPDATE documents SET id='unrelated' WHERE id=?", (box.document.id,))
    with pytest.raises(RecoveryError):
        validate_file_references(image, str(box.storage.base_dir), expected_upload_files=set())


@pytest.mark.parametrize("change", ["missing_title", "numeric_title", "numeric_text", "invalid_date", "long_date", "null_timestamp", "journal_timestamp"])
def test_snapshot_that_live_document_read_cannot_parse_is_rejected_offline(active, tmp_path, change):  # noqa: F811
    box = active
    archive(box)
    image = _image(box, tmp_path)
    changes = {
        "missing_title": ("UPDATE document_versions SET metadata_snapshot=json_remove(metadata_snapshot,'$.title')", ()),
        "numeric_title": ("UPDATE document_versions SET metadata_snapshot=json_set(metadata_snapshot,'$.title',123)", ()),
        "numeric_text": ("UPDATE document_versions SET metadata_snapshot=json_set(metadata_snapshot,'$.ai_model',123)", ()),
        "invalid_date": ("UPDATE document_versions SET metadata_snapshot=json_set(metadata_snapshot,'$.document_date','2047-02-30')", ()),
        "long_date": ("UPDATE document_versions SET metadata_snapshot=json_set(metadata_snapshot,'$.updated_at',?)", ("2" * 100000,)),
        "null_timestamp": ("UPDATE document_versions SET metadata_snapshot=json_set(metadata_snapshot,'$.created_at',NULL)", ()),
        "journal_timestamp": ("UPDATE document_versions SET created_at='invalid-native-timestamp'", ()),
    }
    _mutate(image, *changes[change])
    before = image.read_bytes()
    with closing(sqlite3.connect(image)) as db:
        with pytest.raises(RecoveryError):
            verify_document_versions(db)
    with pytest.raises(SessionRestoreError, match="restore_document_versions_invalid"):
        secure_sqlite_restore(image, {"JWT_SECRET_KEY": "synthetic-offline-key"}, deadline=time.monotonic() + 20)
    assert image.read_bytes() == before


@pytest.mark.parametrize("change", ["foreign_document", "nonmatching_source", "future_source", "filename"])
def test_restored_copy_requires_same_document_and_exact_prior_source(active, tmp_path, change):  # noqa: F811
    box = active
    original, _ = archive(box)
    versions.publish(box.store, box.document.id, command(box, "later"), "actor", source=BytesIO(b"Different later bytes"), upload_name="later.txt")
    last = versions.publish(box.store, box.document.id,
        RestoreCommand(**command(box, "restore").model_dump(), source_version_id=original["id"]), "actor", restore=True)
    # An unrelated document has the same subjects, original URI, bytes, name
    # and media type: identity, rather than shared ownership, must decide.
    box.document = box.store.create_document(DocumentCreate(property_id=box.prop.id, unit_id=box.unit.id,
        title="Unrelated document", file_url="/uploads/documents/original.txt"))
    other, _ = archive(box, key="other-document")
    image = _image(box, tmp_path)
    statements = {
        "foreign_document": ("UPDATE document_versions SET restored_from_id=? WHERE id=?", (other["id"], last["id"])),
        "nonmatching_source": ("UPDATE document_versions SET restored_from_id=(SELECT id FROM document_versions WHERE document_id=? AND number=2) WHERE id=?", (original["document_id"], last["id"])),
        "future_source": ("UPDATE document_versions SET restored_from_id=id WHERE id=?", (last["id"],)),
        "filename": ("UPDATE document_versions SET filename='changed.txt' WHERE id=?", (last["id"],)),
    }
    _mutate(image, *statements[change])
    with closing(sqlite3.connect(image)) as db:
        with pytest.raises(RecoveryError):
            verify_document_versions(db)


@pytest.mark.parametrize("remaining", [None, "document_versions", "document_version_chunks"])
def test_pre_y1_requires_neither_table_and_partial_table_pair_is_rejected(tmp_path, remaining):
    image = tmp_path / "legacy.sqlite"
    with closing(sqlite3.connect(image)) as db:
        if remaining:
            db.execute("CREATE TABLE " + remaining + "(id TEXT)")
            db.commit()
            with pytest.raises(RecoveryError, match="unvollständig"):
                verify_document_versions(db)
        else:
            assert verify_document_versions(db) == 0


SEED = r'''
import hashlib,json
from io import BytesIO
from pathlib import Path
from backend.dependencies import store
from backend.config import settings
from backend.auth import authenticate_user
from backend.models import DocumentCreate
from backend.services import document_versions as v
from backend.services.document_version_types import OriginalCommand,VersionCommand,RestoreCommand
actor=authenticate_user('recovery-owner','SyntheticPassword123!')['id']
contract=store.list_contracts()[0]
original=b'SOURCE-GONE DOCUMENT ORIGINAL\x00\xff'*5000
path=Path(settings.uploads_dir)/'archived-original.bin'
path.write_bytes(original)
doc=store.create_document(DocumentCreate(title='Reviewed version recovery',contract_id=contract.id,file_url=str(path)))
def cmd(key):
    h=v.history(store,doc.id,actor)
    return dict(idempotency_key=key,expected_document_etag=h['document_etag'],expected_head_id=h['head']['id'] if h['head'] else None,comment='Explicit recovery evidence',confirmed=True)
preview=v.source_preview(store,doc.id,actor)
first=v.publish(store,doc.id,OriginalCommand(**cmd('archive'),expected_sha256=preview['sha256']),actor)
second=v.publish(store,doc.id,VersionCommand(**cmd('upload')),actor,source=BytesIO(b'Reviewed later version'),upload_name='later.txt')
last=v.publish(store,doc.id,RestoreCommand(**cmd('restore'),source_version_id=first['id']),actor,restore=True)
path.unlink()
print('DOCUMENT_VERSION_READY:'+json.dumps(dict(document_id=doc.id,first=first,second=second,last=last,sha256=hashlib.sha256(original).hexdigest(),size=len(original),original_path=str(path))))
'''


def _seed(backup_plan):
    environment = {**os.environ, **backup_plan.configuration, "PYTHONUTF8": "1", "AI_ENABLED": "false",
                   "OPERATIONAL_SCHEDULER_ENABLED": "false", "BACKUP_SCHEDULER_ENABLED": "false"}
    seeded = subprocess.run([sys.executable, "-c", SEED], cwd=ROOT, env=environment, capture_output=True, encoding="utf-8", timeout=90)
    assert seeded.returncode == 0, seeded.stderr
    return json.loads(next(line.removeprefix("DOCUMENT_VERSION_READY:") for line in seeded.stdout.splitlines() if line.startswith("DOCUMENT_VERSION_READY:")))


PROBE = r'''
import hashlib,json,sys
from pathlib import Path
from backend.services.full_recovery import load_recovered_environment
root=Path(sys.argv[1])
expected=json.loads(sys.argv[2])
load_recovered_environment(root)
from backend.app import app
from fastapi.testclient import TestClient
with TestClient(app) as client:
    login=client.post('/api/v1/auth/login',json={'username':'recovery-owner','password':'SyntheticPassword123!'})
    assert login.status_code==200,login.text
    headers={'Authorization':'Bearer '+login.json()['access_token']}
    path='/api/v1/documents/'+expected['document_id']+'/versions'
    history=client.get(path,headers=headers)
    assert history.status_code==200,history.text
    assert [item['id'] for item in history.json()['items']]==[expected[key]['id'] for key in ('last','second','first')]
    for key in ('first','second','last'):
        response=client.get(path+'/'+expected[key]['id']+'/download',headers=headers)
        assert response.status_code==200,response.text
        assert hashlib.sha256(response.content).hexdigest()==expected[key]['sha256']
        assert len(response.content)==expected[key]['size_bytes']
    assert not (root/'uploads'/'archived-original.bin').exists()
print('DOCUMENT_VERSION_RECOVERY_OK')
'''


def test_actual_complete_backup_sourcegone_restore_all_immutable_versions(plan, tmp_path):  # noqa: F811
    expected = _seed(plan)
    archive_file = tmp_path / "documents.immobak"
    create_full_backup(plan, archive_file, PASSPHRASE, offline=True)
    source = plan.database.parent.resolve()
    assert source.is_relative_to(tmp_path.resolve()) and source.name == "source"
    shutil.rmtree(source)
    destination = tmp_path / "recovered"
    restore_full_backup(archive_file, destination, PASSPHRASE)
    with closing(sqlite3.connect(destination / "database.sqlite3")) as db:
        assert verify_document_versions(db) == 3
        rows = db.execute("SELECT id,number,sha256,metadata_snapshot FROM document_versions ORDER BY number").fetchall()
        assert [row[0] for row in rows] == [expected[key]["id"] for key in ("first", "second", "last")]
        assert json.loads(rows[0][3])["file_url"] == expected["original_path"]
        assert db.execute("SELECT file_url FROM documents WHERE id=?", (expected["document_id"],)).fetchone()[0] == str(destination / "uploads" / "archived-original.bin")
        for name in ("first", "last"):
            digest, size = hashlib.sha256(), 0
            for (block,) in db.execute("SELECT data FROM document_version_chunks WHERE version_id=? ORDER BY position", (expected[name]["id"],)):
                digest.update(block)
                size += len(block)
            assert digest.hexdigest() == expected["sha256"] and size == expected["size"]
    assert validate_file_references(destination / "database.sqlite3", str(destination / "uploads"), expected_upload_files={"proof.bin"}).local_references == 2
    # A fresh application, fresh login and authenticated downloads use only the
    # recovered installation. No cached store/source file can satisfy this.
    probe = subprocess.run([sys.executable, "-c", PROBE, str(destination), json.dumps(expected)], cwd=ROOT,
        env={**os.environ, "JWT_SECRET_KEY": "deliberately-wrong-ambient-signer", "PYTHONUTF8": "1", "AI_ENABLED": "false"},
        capture_output=True, encoding="utf-8", timeout=90)
    assert probe.returncode == 0, probe.stderr
    assert "DOCUMENT_VERSION_RECOVERY_OK" in probe.stdout
    assert not source.exists()


def test_authenticated_corrupt_journal_never_publishes_target_or_rotates_credentials(plan, tmp_path, monkeypatch):  # noqa: F811
    _seed(plan)
    pristine = tmp_path / "pristine.immobak"
    create_full_backup(plan, pristine, PASSPHRASE, offline=True)
    plain = tmp_path / "test-only.zip"
    decrypt_zip(pristine, plain, PASSPHRASE, 64 * 1024**2)
    with ZipFile(plain) as archive:
        entries = {item.filename: archive.read(item.filename) for item in archive.infolist()}
    source_database = plan.database.read_bytes()
    source_environment = plan.runtime_env.read_bytes()
    from backend.services import recovery_sessions

    def forbidden_mutation(*_args, **_kwargs):
        pytest.fail("Corrupt originals reached session/signing-key mutation")
    monkeypatch.setattr(recovery_sessions, "secure_sqlite_restore", forbidden_mutation)
    for name, sql in (
        # Poison only the middle, non-current version: validation must include
        # the entire historical journal, beyond the original and current head.
        ("bytes", "UPDATE document_version_chunks SET data=zeroblob(length(data)) WHERE position=0 AND version_id=(SELECT id FROM document_versions WHERE number=2)"),
        ("subject", "UPDATE document_versions SET metadata_snapshot=json_set(metadata_snapshot,'$.id','unrelated')"),
    ):
        image = tmp_path / (name + ".sqlite")
        image.write_bytes(entries["database.sqlite3"])
        _mutate(image, sql)
        altered = image.read_bytes()
        manifest = json.loads(entries["manifest.json"])
        manifest["files"]["database.sqlite3"] = {"size": len(altered), "sha256": hashlib.sha256(altered).hexdigest()}
        # Re-authenticate the outer archive with correct byte hashes. The inner
        # manifest/subject proof must catch the invalid immutable document.
        package = tmp_path / (name + ".immobak")
        with encrypted_zip(package, PASSPHRASE) as archive:
            for entry, data in entries.items():
                archive.writestr(entry, altered if entry == "database.sqlite3" else
                    json.dumps(manifest).encode() if entry == "manifest.json" else data)
        destination = tmp_path / ("rejected-" + name)
        with pytest.raises(RecoveryError, match="Dokumentversionen"):
            restore_full_backup(package, destination, PASSPHRASE)
        assert not destination.exists()
        assert not list(tmp_path.glob(".immo-restore-*"))
    assert plan.database.read_bytes() == source_database
    assert plan.runtime_env.read_bytes() == source_environment


def test_actual_pre_y1_complete_backup_remains_restorable(plan, tmp_path):  # noqa: F811
    with closing(sqlite3.connect(plan.database)) as db:
        db.execute("DROP TABLE document_version_chunks")
        db.execute("DROP TABLE document_versions")
        db.commit()
    archive_file = tmp_path / "legacy.immobak"
    create_full_backup(plan, archive_file, PASSPHRASE, offline=True)
    destination = tmp_path / "legacy-restored"
    restore_full_backup(archive_file, destination, PASSPHRASE)
    with closing(sqlite3.connect(destination / "database.sqlite3")) as db:
        assert verify_document_versions(db) == 0
    assert (destination / "uploads" / "proof.bin").read_bytes() == (plan.uploads / "proof.bin").read_bytes()
