"""Owned file/process restore, concurrency and restart probes."""
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine

from backend.db import schema_state
from backend.routers import admin_runtime
from backend.services import full_backup, sqlite_backup
from backend.services.filesystem_paths import filesystem_path


def _child_environment() -> dict[str, str]:
    """Own child imports must not depend on pytest's cwd or inherited search path."""
    project = Path(__file__).resolve(strict=True).parents[2]
    if not (project / "backend" / "__init__.py").is_file():
        raise RuntimeError("The process test's absolute project import root is missing")
    return {**os.environ, "PYTHONPATH": str(project)}


def _stop_child(process: subprocess.Popen) -> None:
    """Stop only the child owned by this test, with a bounded kill fallback."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def test_missing_copy_source_never_creates_an_empty_database(tmp_path):
    source, target = tmp_path / "missing.db", tmp_path / "target.db"
    with pytest.raises((FileNotFoundError, ValueError)):
        sqlite_backup.copy_database(source, target)
    assert not source.exists() and not target.exists()


def test_corrupt_copy_source_never_publishes_a_destination(tmp_path):
    source, target = tmp_path / "bad.db", tmp_path / "target.db"
    source.write_bytes(b"not a database")
    with pytest.raises((ValueError, sqlite3.Error)):
        sqlite_backup.copy_database(source, target)
    assert not target.exists()


def test_copy_of_a_database_onto_itself_is_rejected_without_hanging(tmp_path):
    source = tmp_path / "own.db"
    ready = tmp_path / "copy-import-ready"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE marker(value TEXT)")
    command = """from pathlib import Path
import sys,json
from backend.services.sqlite_backup import copy_database
Path(sys.argv[2]).write_text('copy imports ready')
try:
 copy_database(Path(sys.argv[1]),Path(sys.argv[1]))
except ValueError:
 print(json.dumps({'rejected':True}))
else:
 raise SystemExit(2)
"""
    process = subprocess.Popen([sys.executable, "-X", "utf8", "-c", command, str(source), str(ready)],
        cwd=tmp_path, env=_child_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert process.stdout is not None and process.stderr is not None
    try:
        # Bound interpreter/import startup separately; the actual copy operation
        # retains the existing five-second hang guard after the ready signal.
        deadline = time.monotonic() + 25
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if not ready.exists():
            _stop_child(process)
            output, errors = process.communicate(timeout=10)
            pytest.fail("Own copy process did not reach its 25-second import-ready checkpoint; "
                        f"exit={process.returncode}; stdout={output[-2000:]}; stderr={errors[-2000:]}")
        output, errors = process.communicate(timeout=5)
        assert process.returncode == 0 and json.loads(output)["rejected"], errors
    finally:
        _stop_child(process)
        process.stdout.close()
        process.stderr.close()


def test_live_full_backup_cannot_be_stolen_after_six_hours(tmp_path):
    with full_backup._Lock(tmp_path):
        old = time.time() - 7 * 3600
        os.utime(tmp_path / ".lock", (old, old))
        with pytest.raises(full_backup.BackupError):
            with full_backup._Lock(tmp_path):
                pytest.fail("Live lock stolen")


def test_process_crash_releases_the_kernel_backup_lock(tmp_path):
    ready = tmp_path / "owned-lock-ready"
    command = """from pathlib import Path
import sys,time
from backend.services.full_backup import _Lock
with _Lock(Path(sys.argv[1])):
 (Path(sys.argv[1])/'owned-lock-ready').write_text('owned-lock-ready')
 print('owned-lock-ready',flush=True)
 time.sleep(30)
"""
    process = subprocess.Popen([sys.executable, "-X", "utf8", "-c", command, str(tmp_path)],
        cwd=tmp_path, env=_child_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert process.stdout is not None and process.stderr is not None
    try:
        deadline = time.monotonic() + 25
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if not ready.exists():
            _stop_child(process)
            output, errors = process.communicate(timeout=10)
            pytest.fail("Own lock process did not reach its 25-second ready checkpoint; "
                        f"exit={process.returncode}; stdout={output[-2000:]}; stderr={errors[-2000:]}")
        _stop_child(process)
        output, errors = process.communicate(timeout=10)
        assert "owned-lock-ready" in output, errors
        with full_backup._Lock(tmp_path):
            pass
    finally:
        _stop_child(process)
        process.stdout.close()
        process.stderr.close()


def test_legacy_sqlite_http_restore_refuses_live_database_changes(tmp_path, monkeypatch):
    live, backups = tmp_path / "live.db", tmp_path / "backups"
    backups.mkdir()
    engine = create_engine("sqlite:///" + live.as_posix())
    schema_state.initialise_empty(engine)
    engine.dispose()
    sqlite_backup.copy_database(live, backups / "backup_old.db")
    monkeypatch.setattr(admin_runtime, "_BACKUP_DIR", backups)
    monkeypatch.setattr(admin_runtime, "_live_sqlite_path", lambda: live)
    before = live.read_bytes()
    with pytest.raises(HTTPException) as error:
        admin_runtime.restore_backup("backup_old.db")
    assert error.value.status_code == 409 and "offline" in error.value.detail.lower()
    assert live.read_bytes() == before


@pytest.mark.parametrize("filename", ["missing.db", "old.sqlite", "not-present.bin"])
def test_raw_restore_refuses_before_opening_the_source(filename, monkeypatch):
    monkeypatch.setattr(admin_runtime, "_resolve_backup_path", lambda _: pytest.fail("raw file touched"))
    with pytest.raises(HTTPException) as error:
        admin_runtime.restore_backup(filename)
    assert error.value.status_code == 409


def test_long_sqlite_paths_preserve_readonly_copy_and_schema_inspection(tmp_path):
    # A real path beyond classic MAX_PATH, with URI-special and Unicode bytes.
    directory = tmp_path
    while len(str(directory)) < 280:
        directory /= "synthetic-path-" + "x" * 30
    filesystem_path(directory).mkdir(parents=True)
    database = directory / "Prüfung # ? %.db"
    if os.name == "nt":
        # '?' is a Win32 wildcard even in an extended path: exercise it in URI
        # encoding on POSIX and use the remaining legal special characters here.
        database = directory / "Prüfung # %.db"
    with sqlite3.connect(filesystem_path(database)) as connection:
        connection.execute("CREATE TABLE synthetic_marker(value TEXT)")
        connection.execute("INSERT INTO synthetic_marker VALUES ('owned long path')")
    before = filesystem_path(database).read_bytes()
    for path in (database, filesystem_path(database)):
        with sqlite3.connect(sqlite_backup.readonly_uri(path), uri=True) as connection:
            assert connection.execute("SELECT value FROM synthetic_marker").fetchone() == ("owned long path",)
            with pytest.raises(sqlite3.OperationalError):
                connection.execute("INSERT INTO synthetic_marker VALUES ('forbidden')")
        engine = create_engine(sqlite_backup.file_url(path))
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT value FROM synthetic_marker").scalar() == "owned long path"
        engine.dispose()
        status, application_tables = schema_state.inspect_sqlite_file(path)
        assert status.state == schema_state.UNVERSIONED and not application_tables
        assert full_backup._sqlite_facts(path, full_check=True)["row_counts"] == {"synthetic_marker": 1}
    target = directory / "copy.db"
    sqlite_backup.copy_database(database, target)
    with sqlite3.connect(sqlite_backup.readonly_uri(target), uri=True) as connection:
        assert connection.execute("SELECT value FROM synthetic_marker").fetchone() == ("owned long path",)
    assert filesystem_path(database).read_bytes() == before


def test_interrupted_source_transaction_is_fenced_in_a_fresh_process(tmp_path):
    state = tmp_path / "updates"
    state.mkdir()
    (state / "transaction.json").write_text(json.dumps({"phase": "applying"}))
    command = """from pathlib import Path
import json,sys
from backend import updater
updater._UPDATE_DIR=Path(sys.argv[1])
updater._LOCK_FILE=updater._UPDATE_DIR/'update.lock'
assert updater.writes_blocked()
print(json.dumps({'fresh_process_fenced':True}))
"""
    result = subprocess.run([sys.executable, "-X", "utf8", "-c", command, str(state)],
        cwd=tmp_path, env=_child_environment(), capture_output=True, text=True, timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0 and json.loads(result.stdout)["fresh_process_fenced"]
