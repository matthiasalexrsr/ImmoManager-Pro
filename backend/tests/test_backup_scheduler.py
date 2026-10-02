"""Real private SQLite/CLI snapshots; task creation is always mocked."""

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from scripts import backup_scheduler as scheduler

FIXED_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path / "Private installation with spaces"
    root.mkdir()
    database = root / "selected database.db"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO evidence (value) VALUES ('committed fixture')")
    (root / ".env").write_text(f'DATABASE_URL="sqlite:///{database.as_posix()}"\nBACKUP_DIR="selected snapshots"\nJWT_SECRET_KEY=synthetic-secret-must-not-print\n', encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "foreign installation"))
    monkeypatch.setenv("DATABASE_URL", "postgresql://foreign:synthetic-ambient-password@example.invalid/foreign")
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "foreign snapshots"))
    return scheduler.configuration(root)


def table_values(database):
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        return [row[0] for row in connection.execute("SELECT value FROM evidence ORDER BY id")]


def test_wal_snapshot_includes_committed_pages_and_excludes_open_transaction(installation):
    writer = sqlite3.connect(installation.database)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO evidence (value) VALUES ('committed WAL fixture')")
        writer.commit()
        assert Path(str(installation.database) + "-wal").stat().st_size > 0
        writer.execute("INSERT INTO evidence (value) VALUES ('uncommitted fixture')")
        snapshot = scheduler.run_backup(installation, now=FIXED_NOW)
        assert table_values(snapshot) == ["committed fixture", "committed WAL fixture"]
        assert scheduler.OWN_SNAPSHOT.fullmatch(snapshot.name)
        assert snapshot.name.startswith("database_snapshot_20261001_120000_")
        assert list(installation.backups.iterdir()) == [snapshot]
    finally:
        writer.rollback()
        writer.close()


def test_simultaneous_timestamp_snapshots_have_distinct_complete_files(installation):
    first = scheduler.run_backup(installation, now=FIXED_NOW)
    second = scheduler.run_backup(installation, now=FIXED_NOW)
    assert first != second
    assert table_values(first) == table_values(second) == ["committed fixture"]
    assert set(installation.backups.iterdir()) == {first, second}


def test_exclusive_writer_hits_bounded_deadline_and_leaves_no_published_or_temporary_file(installation):
    import time
    writer = sqlite3.connect(installation.database)
    try:
        writer.execute("BEGIN EXCLUSIVE")
        writer.execute("UPDATE evidence SET value='not yet committed'")
        started = time.monotonic()
        with pytest.raises(scheduler.SnapshotError, match="Zeitlimit"):
            scheduler.run_backup(installation, timeout=0.1)
        assert time.monotonic() - started < 2
        assert list(installation.backups.iterdir()) == []
    finally:
        writer.rollback()
        writer.close()
    assert table_values(installation.database) == ["committed fixture"]


def test_corrupt_source_never_falls_back_to_raw_copy_or_api_and_preserves_old_snapshot(installation):
    old = scheduler.run_backup(installation, now=FIXED_NOW)
    before = old.read_bytes()
    installation.database.write_bytes(b"not a SQLite database")
    with pytest.raises(sqlite3.DatabaseError):
        scheduler.run_backup(installation)
    assert list(installation.backups.iterdir()) == [old]
    assert old.read_bytes() == before


def test_partial_backup_and_integrity_failures_remove_owned_temporary_file(installation, monkeypatch):
    real_connect = sqlite3.connect

    class InterruptedSource:
        def backup(self, target, **kwargs):
            target.execute("CREATE TABLE partial_evidence (value TEXT)")
            target.commit()
            raise sqlite3.OperationalError("injected partial backup failure")

        def close(self):
            pass

    monkeypatch.setattr(scheduler.sqlite3, "connect", lambda database, **kwargs: InterruptedSource() if str(database).startswith(installation.database.as_uri()) else real_connect(database, **kwargs))
    with pytest.raises(sqlite3.OperationalError):
        scheduler.run_backup(installation)
    assert list(installation.backups.iterdir()) == []

    monkeypatch.setattr(scheduler.sqlite3, "connect", real_connect)
    real_link = scheduler.os.link
    publication = []
    monkeypatch.setattr(scheduler.os, "link", lambda source, destination: publication.append((source, destination)))

    class FailedVerification:
        def set_progress_handler(self, handler, instructions):
            pass

        def execute(self, statement):
            return self

        def fetchall(self):
            return [("injected integrity failure",)]

        def close(self):
            pass

    monkeypatch.setattr(scheduler.sqlite3, "connect", lambda database, **kwargs: FailedVerification() if str(database).endswith(".tmp?mode=ro") else real_connect(database, **kwargs))
    with pytest.raises(scheduler.SnapshotError, match="Integritätsprüfung"):
        scheduler.run_backup(installation)
    assert publication == []
    assert list(installation.backups.iterdir()) == []
    monkeypatch.setattr(scheduler.os, "link", real_link)


def test_publication_never_overwrites_an_existing_snapshot(installation, monkeypatch):
    monkeypatch.setattr(scheduler, "uuid4", lambda: UUID(int=1))
    first = scheduler.run_backup(installation, now=FIXED_NOW)
    before = first.read_bytes()
    with closing(sqlite3.connect(installation.database)) as connection, connection:
        connection.execute("INSERT INTO evidence (value) VALUES ('later fixture')")
    with pytest.raises(FileExistsError):
        scheduler.run_backup(installation, now=FIXED_NOW)
    assert first.read_bytes() == before
    assert table_values(first) == ["committed fixture"]
    assert list(installation.backups.iterdir()) == [first]


def test_publication_filesystem_failure_leaves_old_snapshots_and_cleans_partial_output(installation, monkeypatch):
    old = scheduler.run_backup(installation)
    monkeypatch.setattr(scheduler.os, "link", lambda *args: (_ for _ in ()).throw(OSError("injected publication failure")))
    with pytest.raises(OSError):
        scheduler.run_backup(installation)
    assert table_values(old) == ["committed fixture"]
    assert list(installation.backups.iterdir()) == [old]


def test_deadline_exceeded_during_flush_does_not_publish_complete_but_late_snapshot(installation, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(scheduler.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(scheduler.os, "fsync", lambda descriptor: clock.__setitem__(0, 2.0))
    with pytest.raises(scheduler.SnapshotError, match="Zeitlimit"):
        scheduler.run_backup(installation, timeout=1)
    assert list(installation.backups.iterdir()) == []


def test_explicit_installation_reads_own_quoted_env_and_overrides_foreign_environment(installation, tmp_path):
    assert installation.data_dir.name == "Private installation with spaces"
    assert installation.database == installation.data_dir / "selected database.db"
    assert installation.backups == installation.data_dir / "selected snapshots"
    (installation.data_dir / ".env").unlink()
    default = scheduler.configuration(installation.data_dir)
    assert default.database == installation.data_dir / "immo_manager.db"
    assert default.backups == installation.data_dir / "backups"
    assert not (tmp_path / "foreign snapshots").exists()


@pytest.mark.parametrize("url", ["postgresql://synthetic-user:synthetic-password@example.invalid/db", "sqlite:///:memory:", "sqlite://", "sqlite:///file:temporary?mode=memory&cache=shared", "sqlite:///selected.db?mode=ro"])
def test_unsupported_configured_database_fails_without_fallback_or_credentials(installation, url, capsys):
    (installation.data_dir / ".env").write_text(f"DATABASE_URL={url}\n", encoding="utf-8")
    assert scheduler.main(["run", "--data-dir", str(installation.data_dir)]) == 1
    output = capsys.readouterr()
    assert "Snapshot erstellt" not in output.out
    assert "synthetic-password" not in output.err
    assert "synthetic-user" not in output.err
    assert "example.invalid" not in output.err
    assert not installation.backups.exists()


def test_missing_configured_database_does_not_create_source_or_backup_folder(installation, capsys):
    installation.database.unlink()
    assert scheduler.main(["run", "--data-dir", str(installation.data_dir)]) == 1
    assert not installation.database.exists()
    assert not installation.backups.exists()
    assert "Kein anderes Backup" in capsys.readouterr().err


def test_cleanup_only_removes_owned_old_regular_snapshots_and_preserves_archives(installation):
    installation.backups.mkdir()
    old_names = ["database_snapshot_20260801_020000_" + "1" * 32 + ".db", "backup_20260801_020000.db"]
    protected_names = ["database_snapshot_20260925_020000_" + "2" * 32 + ".db", "backup_manual.db", "backup_20260801_020000.zip", "full_recovery_20260801.enc", ".database_snapshot_own.tmp", "unrelated.db"]
    for name in old_names + protected_names:
        path = installation.backups / name
        path.write_bytes(b"owned synthetic fixture")
        age = 5 if name.startswith("database_snapshot_20260925") else 60
        modified = (FIXED_NOW - timedelta(days=age)).timestamp()
        os.utime(path, (modified, modified))
    directory = installation.backups / ("database_snapshot_20260801_020000_" + "3" * 32 + ".db")
    directory.mkdir()
    assert scheduler.cleanup(installation, now=FIXED_NOW) == 2
    assert set(path.name for path in installation.backups.iterdir()) == set(protected_names + [directory.name])


def test_cleanup_skips_symlink_and_keeps_its_external_target(installation, tmp_path):
    installation.backups.mkdir()
    outside = tmp_path / "external-user-file.db"
    outside.write_bytes(b"never delete this synthetic external file")
    old = (FIXED_NOW - timedelta(days=60)).timestamp()
    os.utime(outside, (old, old))
    link = installation.backups / ("database_snapshot_20260801_020000_" + "4" * 32 + ".db")
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Windows symlink creation requires Developer Mode or privilege")
    assert scheduler.cleanup(installation, now=FIXED_NOW) == 0
    assert link.is_symlink()
    assert outside.read_bytes() == b"never delete this synthetic external file"


def test_cleanup_preserves_configured_database_even_if_it_has_an_old_snapshot_name(installation):
    installation.backups.mkdir()
    active = installation.backups / ("database_snapshot_20260801_020000_" + "5" * 32 + ".db")
    installation.database.rename(active)
    old = (FIXED_NOW - timedelta(days=60)).timestamp()
    os.utime(active, (old, old))
    selected = scheduler.SnapshotPaths(installation.data_dir, active, installation.backups)
    assert scheduler.cleanup(selected, now=FIXED_NOW) == 0
    assert table_values(active) == ["committed fixture"]


@pytest.mark.parametrize("command", ["schedule", "unschedule"])
@pytest.mark.parametrize("failure", [FileNotFoundError("no schtasks"), subprocess.CalledProcessError(7, "schtasks", output="synthetic-user-secret"), subprocess.TimeoutExpired("schtasks", 30)])
def test_task_command_failures_return_nonzero_and_never_claim_success(installation, monkeypatch, capsys, command, failure):
    monkeypatch.setattr(scheduler.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(failure))
    assert scheduler.main([command, "--data-dir", str(installation.data_dir)]) == 1
    captured = capsys.readouterr()
    assert "erstellt" not in captured.out and "entfernt" not in captured.out
    assert "synthetic-user-secret" not in captured.err
    assert captured.err


def test_task_command_captures_project_interpreter_and_quoted_explicit_installation(installation, monkeypatch, tmp_path):
    project = tmp_path / "Project with spaces"
    interpreter = project / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    interpreter.parent.mkdir(parents=True)
    interpreter.write_bytes(b"synthetic executable fixture, never run")
    monkeypatch.setattr(scheduler, "ROOT", project)
    calls = []
    monkeypatch.setattr(scheduler.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))
    assert scheduler.main(["schedule", "--data-dir", str(installation.data_dir), "--timeout", "42"]) == 0
    command, options = calls[0]
    task_command = command[command.index("/tr") + 1]
    assert task_command == subprocess.list2cmdline([str(interpreter.resolve()), str(Path(scheduler.__file__).resolve()), "run", "--data-dir", str(installation.data_dir), "--timeout", "42.0"])
    assert options == {"check": True, "capture_output": True, "text": True, "timeout": 30}
    assert command[command.index("/st") + 1] == "02:00"
    assert not installation.backups.exists()


def test_schedule_refuses_environment_only_configuration_that_task_cannot_reproduce(installation, monkeypatch, capsys):
    foreign_paths = scheduler.SnapshotPaths(installation.data_dir, installation.database, installation.data_dir / "environment only backup folder")
    monkeypatch.setattr(scheduler.subprocess, "run", lambda *args, **kwargs: pytest.fail("Unreproducible task must not be created"))
    with pytest.raises(scheduler.SnapshotError, match="reproduzierbar"):
        scheduler.schedule(foreign_paths)


def test_cli_executes_real_snapshot_and_info_labels_scope_without_secrets(installation):
    script = Path(scheduler.__file__).resolve()
    result = subprocess.run([sys.executable, str(script), "run", "--data-dir", str(installation.data_dir)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "DATABASE-ONLY" in result.stdout
    assert "keine Anhänge" in result.stdout
    assert "synthetic-secret" not in result.stdout
    snapshots = list(installation.backups.glob("*.db"))
    assert len(snapshots) == 1 and table_values(snapshots[0]) == ["committed fixture"]
    info = subprocess.run([sys.executable, str(script), "info", "--data-dir", str(installation.data_dir)], capture_output=True, text=True, timeout=10)
    assert info.returncode == 0
    assert "DATABASE-ONLY" in info.stdout
    assert "backend.recovery backup --offline" in info.stdout
    assert "synthetic-secret" not in info.stdout
    assert "synthetic-ambient-password" not in info.stdout


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf", "3601", "not-a-number"])
def test_cli_rejects_invalid_timeout_before_any_snapshot_writes(installation, timeout):
    with pytest.raises(SystemExit) as error:
        scheduler.main(["run", "--data-dir", str(installation.data_dir), "--timeout", timeout])
    assert error.value.code == 2
    assert not installation.backups.exists()
