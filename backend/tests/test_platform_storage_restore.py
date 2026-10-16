"""Independent protocol, cross-worker quota and portable archive regressions."""

import json
import sqlite3
import zipfile
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import Table, create_engine
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.db.access_models import RegistrationQuotaORM
from backend.services import file_storage, full_backup, portable_runtime
from backend.services.private_file_response import private_bytes
from backend.tests import test_operations_backup as backup_cases

# A fixture imported under a separate module name stays visible to pytest
# without shadowing test parameters or triggering Ruff's F811 redefinition.
installation = backup_cases.installation


class ProtocolError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


class S3Protocol:
    """Protocol fixture verifies actual SDK argument/stream contract, no browser S3 URL."""

    def __init__(self):
        self.objects = {}
        self.fail = False

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata, IfNoneMatch):
        assert Bucket == "fixture" and ContentType == "application/pdf"
        assert IfNoneMatch == "*" and len(Metadata["sha256"]) == 64
        if Key in self.objects:
            raise ProtocolError("PreconditionFailed")
        self.objects[Key] = Body

    def get_object(self, *, Bucket, Key):
        assert Bucket == "fixture"
        if self.fail:
            raise ProtocolError("AccessDenied")
        if Key not in self.objects:
            raise ProtocolError("NoSuchKey")
        return {"Body": BytesIO(self.objects[Key])}


def test_s3_protocol_bytes_errors_and_private_ranges():
    client = S3Protocol()
    storage = file_storage.S3Storage(bucket="fixture", client=client)
    original = b"%PDF\x00\xff0123456789"
    assert storage.save("documents/a.pdf", BytesIO(original), "application/pdf") == "/uploads/documents/a.pdf"
    assert storage.get("documents/a.pdf") == original
    storage.save("documents/a.pdf", BytesIO(original), "application/pdf")
    with pytest.raises(file_storage.StorageUnavailable):
        storage.save("documents/a.pdf", BytesIO(b"changed"), "application/pdf")
    assert storage.get("missing.pdf") is None
    response = private_bytes(original, media_type="application/pdf", range_header="bytes=4-7")
    assert response.status_code == 206 and response.body == b"\x00\xff01"
    assert response.headers["content-range"] == "bytes 4-7/16"
    assert private_bytes(original, media_type="application/pdf", range_header="bytes=99-").status_code == 416
    client.fail = True
    with pytest.raises(file_storage.StorageUnavailable):
        storage.get("documents/a.pdf")
    for key in ("../a", "a/../b", "/a", "C:/a", "a\\b"):
        with pytest.raises(ValueError):
            storage.get(key)


def test_registration_reserves_global_quota_across_independent_sessions(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'quota.db'}", connect_args={"timeout": 20})
    cast(Table, RegistrationQuotaORM.__table__).create(engine)
    monkeypatch.setattr(auth, "_auth_session_factory", sessionmaker(bind=engine))
    import os
    import subprocess
    import sys

    code = """import json, sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend import auth
engine = create_engine(sys.argv[1], connect_args={"timeout": 20})
auth._auth_session_factory = sessionmaker(bind=engine)
sys.stdin.read()
print(json.dumps([auth.reserve_registration_attempt("192.0.2.1") for _ in range(7)]))
engine.dispose()
"""
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(engine.url)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=dict(os.environ),
        )
        for _ in range(2)
    ]
    for worker in workers:
        assert worker.stdin is not None
        worker.stdin.close()
    results = []
    for worker in workers:
        worker.wait(timeout=45)
        assert worker.stderr is not None and worker.stdout is not None
        assert worker.returncode == 0, worker.stderr.read()
        results.extend(json.loads(worker.stdout.read()))
    assert results.count(False) == 5 and results.count(True) == 9
    # A separate engine/session factory sees the exact same persisted budget.
    other = create_engine(f"sqlite:///{tmp_path / 'quota.db'}")
    monkeypatch.setattr(auth, "_auth_session_factory", sessionmaker(bind=other))
    assert auth.reserve_registration_attempt("192.0.2.1") is True
    assert auth.reserve_registration_attempt("192.0.2.2") is False
    other.dispose()
    engine.dispose()


def test_remote_reference_is_included_and_restored_without_provider(installation, tmp_path):
    fixture = installation
    client = S3Protocol()
    client.objects["documents/remote.pdf"] = b"original\x00remote\xff"
    fixture.sources.file_storage = file_storage.S3Storage(bucket="fixture", client=client)
    with sqlite3.connect(fixture.db) as conn:
        conn.execute("CREATE TABLE synthetic_references (file_url TEXT)")
        conn.execute("INSERT INTO synthetic_references VALUES (?)", ("/uploads/documents/remote.pdf",))
    fixture.sources.passphrase = "fixture-only-passphrase"
    fixture.sources.runtime_bytes = json.dumps(
        {"jwt_secret_key": "synthetic", "secret_keys": "", "file_storage_backend": "s3", "s3_secret_key": "do-not-log"}
    ).encode()
    event = full_backup.create_full_backup(sources=fixture.sources)
    archive = fixture.sources.root / event["archive"]
    with zipfile.ZipFile(archive) as zf:
        assert zf.read("uploads/documents/remote.pdf") == b"original\x00remote\xff"
        assert b"do-not-log" not in zf.read("manifest.json")
        assert portable_runtime.RUNTIME not in zf.namelist()
    target = tmp_path / "fresh"
    result = full_backup.restore_archive(archive, target, passphrase=fixture.sources.passphrase)
    assert result["readiness"] == "data_verified" and result["application_gate"] == "not_run"
    assert (target / "uploads/documents/remote.pdf").read_bytes() == b"original\x00remote\xff"
    assert 'FILE_STORAGE_BACKEND="local"' in (target / ".env").read_text()
    assert "do-not-log" not in (target / ".env").read_text()
    assert full_backup.restore_probe(archive, fixture.sources, passphrase="")["ok"] is False


def test_missing_referenced_original_refuses_success(installation):
    with sqlite3.connect(installation.db) as conn:
        conn.execute("CREATE TABLE synthetic_references (file_url TEXT)")
        conn.execute("INSERT INTO synthetic_references VALUES ('/uploads/documents/missing.pdf')")
    with pytest.raises(full_backup.BackupError, match="Original fehlt"):
        full_backup.create_full_backup(sources=installation.sources)
    assert not list(installation.sources.root.glob("*.zip"))


def test_standalone_restore_logs_into_actual_app_in_clean_child(installation, tmp_path):
    import hashlib

    from tools.platform_restore_gate import restore_and_gate

    fixture = installation
    with sqlite3.connect(fixture.db) as conn:
        conn.execute(
            "UPDATE users SET hashed_password=?, role='eigentuemer' WHERE id='staff'",
            (auth.hash_password("Synthetic123"),),
        )
        conn.execute(
            "INSERT INTO user_portfolio_access(user_id,mode,origin,updated_at) VALUES ('staff','all','owner_assignment','2026-01-01')"
        )
    fixture.sources.passphrase = "synthetic-portable-passphrase"
    fixture.sources.runtime_bytes = json.dumps(
        {
            "jwt_secret_key": "synthetic-portable-jwt-" * 3,
            "environment": "development",
            "secret_keys": "",
            "file_storage_backend": "local",
        }
    ).encode()
    event = full_backup.create_full_backup(sources=fixture.sources)
    original = fixture.sources.uploads_dir / "documents/vertrag.pdf"
    # The production restore gate deliberately refuses arbitrary destinations.
    # Use a unique, never reused path inside this checkout's artifacts folder;
    # the source installation and its independently-created backup stay apart.
    restored = Path(__file__).resolve().parents[2] / "artifacts" / "platform-tests" / ("fresh-" + uuid4().hex)
    restored.parent.mkdir(parents=True, exist_ok=True)
    result = restore_and_gate(
        fixture.sources.root / event["archive"],
        restored,
        {
            "passphrase": fixture.sources.passphrase,
            "username": "staff",
            "password": "Synthetic123",
            "originals": {"documents/vertrag.pdf": hashlib.sha256(original.read_bytes()).hexdigest()},
        },
    )
    assert result["ok"] and result["readiness"] == "application_verified"
    assert result["browser"] == "not_run" and result["originals"] == 1


def test_storage_binding_preserves_legacy_local_and_refuses_wrong_bucket(tmp_path):
    from backend.db.access_models import StorageBindingORM

    engine = create_engine(f"sqlite:///{tmp_path / 'bindings.db'}")
    cast(Table, StorageBindingORM.__table__).create(engine)
    factory = sessionmaker(bind=engine)
    local = file_storage.LocalStorage(tmp_path / "local")
    local.save("legacy.pdf", BytesIO(b"old-original"))
    protocol = S3Protocol()
    remote = file_storage.S3Storage(bucket="fixture", client=protocol, bindings_factory=factory, legacy_local=local)
    assert remote.get("legacy.pdf") == b"old-original"
    remote.save("new.pdf", BytesIO(b"new-original"), "application/pdf")
    assert remote.get("new.pdf") == b"new-original"
    protocol.objects["new.pdf"] = b"tampered"
    with pytest.raises(file_storage.StorageUnavailable, match="Speicherbindung"):
        remote.get("new.pdf")
    wrong = file_storage.S3Storage(bucket="wrong", client=protocol, bindings_factory=factory, legacy_local=local)
    with pytest.raises(file_storage.StorageUnavailable, match="anderen Speicher"):
        wrong.get("new.pdf")
    with pytest.raises(ValueError, match="Originalbytes"):
        local.save("legacy.pdf", BytesIO(b"replacement"))
    engine.dispose()


def test_declared_plugin_code_is_byte_preserved_in_portable_archive(installation, tmp_path):
    import hashlib

    root = tmp_path / "packages/portable_fixture"
    root.mkdir(parents=True)
    source = b"# retained trusted plugin source\n"
    (root / "__init__.py").write_bytes(source)
    declaration = {
        "name": "portable_fixture",
        "version": "1.0.0",
        "files": {"__init__.py": hashlib.sha256(source).hexdigest()},
    }
    (root / "immomanager-plugin.json").write_text(json.dumps(declaration), encoding="utf-8")
    installation.sources.plugin_dirs = [str(root.parent)]
    event = full_backup.create_full_backup(sources=installation.sources)
    target = tmp_path / "plugin-restored"
    full_backup.restore_archive(installation.sources.root / event["archive"], target)
    assert (target / "plugins/portable_fixture/__init__.py").read_bytes() == source
