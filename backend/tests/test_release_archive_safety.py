"""Corrupt/untrusted backup envelopes must fail before extraction or allocation."""
import errno
import hashlib
import json
import os
import sqlite3
import zipfile
from collections import namedtuple

import pytest

from backend.services import full_backup as backup


def archive(tmp_path, extra=None, transform=None):
    files = {backup.DB_SQLITE: b"synthetic database bytes", **(extra or {})}
    manifest = {
        "format": backup.FORMAT, "format_version": 1,
        "database": {"path": backup.DB_SQLITE, "dialect": "sqlite", "revision": None, "row_counts": {}},
        "uploads": {"files": 0, "bytes": 0},
        "secrets": {"protection": "none", "protected_files": [], "missing_key_ids": []},
        "files": [{"path": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                  for name, raw in files.items()],
    }
    if transform:
        manifest = transform(manifest)
    path = tmp_path / "own.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, raw in files.items():
            zf.writestr(name, raw)
        zf.writestr("manifest.json", json.dumps(manifest))
    return path


@pytest.mark.parametrize("change", [
    lambda m: None, lambda m: [], lambda m: {**m, "files": None},
    lambda m: {**m, "database": []}, lambda m: {**m, "format_version": True},
    lambda m: {**m, "format_version": -1},
    lambda m: {**m, "files": [{**m["files"][0], "size": True}]},
    lambda m: {**m, "files": [m["files"][0], m["files"][0]]},
])
def test_invalid_manifest_is_a_controlled_rejection(tmp_path, change):
    report = backup.verify_archive(archive(tmp_path, transform=change))
    assert report["ok"] is False and report["problems"]


@pytest.mark.parametrize("name", [
    "installation/.env", "installation/secrets/keyring.json", "unlisted-root/config.json",
    "uploads/file.pdf:stream", "uploads/CON.txt", "uploads/name. ", "uploads/a/./b",
])
def test_unsupported_or_aliased_restore_path_is_refused(tmp_path, name):
    report = backup.verify_archive(archive(tmp_path, {name: b"synthetic"}))
    assert report["ok"] is False


def test_case_aliases_cannot_overwrite_one_another_on_windows(tmp_path):
    path = archive(tmp_path, {"uploads/A.pdf": b"first", "uploads/a.pdf": b"second"})
    assert backup.verify_archive(path)["ok"] is False


def test_manifest_budget_is_checked_before_read(tmp_path, monkeypatch):
    path = archive(tmp_path)
    monkeypatch.setattr(backup, "_MAX_MANIFEST_BYTES", 32, raising=False)
    original = zipfile.ZipFile.read
    called = []

    def read(zf, name, *args, **kwargs):
        called.append(name)
        return original(zf, name, *args, **kwargs)
    monkeypatch.setattr(zipfile.ZipFile, "read", read)
    report = backup.verify_archive(path)
    assert report["ok"] is False and "manifest.json" not in called


def test_expansion_budget_is_checked_before_payload_read(tmp_path, monkeypatch):
    path = archive(tmp_path)
    monkeypatch.setattr(backup, "_MAX_EXPANDED_BYTES", 16, raising=False)
    original = zipfile.ZipFile.open
    payload_read = []

    def open_file(zf, name, *args, **kwargs):
        if name == backup.DB_SQLITE:
            payload_read.append(name)
        return original(zf, name, *args, **kwargs)
    monkeypatch.setattr(zipfile.ZipFile, "open", open_file)
    report = backup.verify_archive(path)
    assert report["ok"] is False and not payload_read


def test_private_configuration_budget_is_checked_before_full_json_reads(tmp_path, monkeypatch):
    path = archive(tmp_path, {backup.ENV: b"x" * 64})
    monkeypatch.setattr(backup, "_MAX_CONFIG_BYTES", 32)
    original = zipfile.ZipFile.open
    opened = []

    def open_file(zf, name, *args, **kwargs):
        opened.append(name)
        return original(zf, name, *args, **kwargs)
    monkeypatch.setattr(zipfile.ZipFile, "open", open_file)
    report = backup.verify_archive(path)
    assert not report["ok"] and backup.ENV not in opened


def test_insufficient_target_space_fails_before_extracting_and_preserves_source(tmp_path, monkeypatch):
    path = archive(tmp_path)
    original = path.read_bytes()
    target = tmp_path / "new-profile"
    DiskUsage = namedtuple("DiskUsage", "total used free")
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda _: DiskUsage(100, 99, 1))
    with pytest.raises(backup.BackupError, match="freier Speicher"):
        backup.restore_archive(path, target)
    assert path.read_bytes() == original and not target.exists()
    assert not list(tmp_path.glob(".*.restore-*"))


def test_disk_write_failure_never_publishes_a_startable_partial_profile(tmp_path, monkeypatch):
    path = archive(tmp_path)
    original = path.read_bytes()
    existing = tmp_path / "existing-profile"
    existing.mkdir()
    (existing / "preserve.txt").write_bytes(b"untouched existing data")
    target = tmp_path / "new-profile"
    real_fdopen = backup.os.fdopen

    class FullDisk:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def write(self, raw):
            self.handle.write(raw[:3])
            self.handle.flush()
            raise OSError(errno.ENOSPC, "synthetic disk full")

    monkeypatch.setattr(backup.os, "fdopen", lambda fd, *a, **kw: FullDisk(real_fdopen(fd, *a, **kw)))
    with pytest.raises(backup.BackupError, match="Dateisystemfehler"):
        backup.restore_archive(path, target)
    assert path.read_bytes() == original and not target.exists()
    assert (existing / "preserve.txt").read_bytes() == b"untouched existing data"
    assert not list(tmp_path.glob(".*.restore-*"))


def test_changed_archive_between_verify_and_extract_is_refused(tmp_path):
    path = archive(tmp_path)
    digest = backup.verify_archive(path)["sha256"]
    with path.open("ab") as handle:
        handle.write(b"synthetic change after verification")
    target = tmp_path / "staging"
    target.mkdir()
    with pytest.raises(backup.BackupError, match="nach der Prüfung verändert"):
        backup._extract(path, target, backup._Pulse(None), expected_sha256=digest)
    assert not list(target.iterdir())


@pytest.mark.parametrize("kind", ["foreign", "newer"])
def test_sqlite_archive_is_checked_before_a_profile_is_published(tmp_path, kind):
    database = tmp_path / "owned-input.db"
    with sqlite3.connect(database) as connection:
        if kind == "foreign":
            connection.execute("CREATE TABLE unrelated(value TEXT)")
            counts, revision = {"unrelated": 0}, None
        else:
            connection.execute("CREATE TABLE portfolios(id TEXT)")
            connection.execute("CREATE TABLE alembic_version(version_num TEXT)")
            connection.execute("INSERT INTO alembic_version VALUES ('ffffffffffff')")
            counts, revision = {"portfolios": 0, "alembic_version": 1}, "ffffffffffff"

    def metadata(manifest):
        manifest["database"].update(row_counts=counts, revision=revision)
        return manifest
    path = archive(tmp_path, {backup.DB_SQLITE: database.read_bytes()}, metadata)
    target = tmp_path / "new-profile"
    with pytest.raises(backup.BackupError, match="keine ImmoManager|neueren Programmversion"):
        backup.restore_archive(path, target)
    assert not target.exists() and not list(tmp_path.glob(".*.restore-*"))


def test_second_target_never_overwrites_or_deletes_an_existing_partial(tmp_path):
    path = archive(tmp_path)
    second = tmp_path / "second-target"
    second.mkdir()
    partial = second / (path.name + ".partial")
    partial.write_bytes(b"preexisting owned file")
    with pytest.raises(FileExistsError):
        backup._copy_verified(path, backup.sha256_file(path), second, backup._Pulse(None))
    assert partial.read_bytes() == b"preexisting owned file"
    assert not (second / path.name).exists()


def test_sidecar_replacement_does_not_follow_a_hard_link(tmp_path):
    source = tmp_path / "owned.zip"
    victim = tmp_path / "preserve.txt"
    victim.write_bytes(b"untouched independent file")
    sidecar = source.with_name(source.name + ".sha256")
    os.link(victim, sidecar)
    backup._write_sidecar(source, "a" * 64)
    assert victim.read_bytes() == b"untouched independent file"
    assert sidecar.read_text().startswith("a" * 64)
