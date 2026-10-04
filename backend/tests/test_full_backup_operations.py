"""Native encrypted automation using real Uvicorn, SQLite writes and fresh restore."""

import os
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.backup_operations import runner
from backend.backup_operations.journal import Journal
from backend.backup_operations.plan import BackupOperationError, BackupPlan, Installation
from backend.backup_operations.runtime import control, selected_runtime, stop_owned_runtime
from backend.backup_operations.state import passphrase, private_directory, save_plan
from backend.tests import test_full_recovery as recovery_fixtures
from scripts.private_server_backup import protected_new_file

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 3, 10, tzinfo=timezone.utc)
plan = recovery_fixtures.plan
runtime_template = recovery_fixtures.runtime_template

SYNTHETIC_APP = '''
import argparse, sqlite3, threading
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from backend.backup_operations.plan import Installation
from backend.backup_operations.runner import _sqlite_plan
from backend.backup_operations.runtime import ManagedRuntime
import sys
parser = argparse.ArgumentParser()
parser.add_argument('--data-dir', required=True)
parser.add_argument('--host', required=True)
parser.add_argument('--port', required=True, type=int)
parser.add_argument('--no-browser', action='store_true')
args = parser.parse_args()
root = Path.cwd()
data = Path(args.data_dir)
with ManagedRuntime(data, app_root=root, host=args.host, port=args.port) as managed:
    selected = _sqlite_plan(Installation(backend='sqlite', data_dir=data, app_root=root, python=Path(sys.executable).resolve()))
    managed.bind_configuration(selected.configuration)
    halted = threading.Event()
    def writer():
        with sqlite3.connect(selected.database) as db:
            db.execute('CREATE TABLE IF NOT EXISTS backup_test_ticks(id INTEGER PRIMARY KEY)')
            db.commit()
            while not halted.wait(0.025):
                db.execute('INSERT INTO backup_test_ticks DEFAULT VALUES')
                db.commit()
    @asynccontextmanager
    async def lifespan(_):
        thread = threading.Thread(target=writer)
        thread.start()
        try:
            yield
        finally:
            halted.set()
            thread.join(timeout=10)
            assert not thread.is_alive()
    managed.run(FastAPI(lifespan=lifespan), log_level='error', access_log=False)
'''


def ready(installation, process=None):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            record = selected_runtime(installation)
            if control(record)["state"] == "ready":
                return record
        except BackupOperationError:
            pass
        if process is not None and process.poll() is not None:
            pytest.fail("Synthetic managed application exited: " + process.stderr.read().decode(errors="replace"))
        time.sleep(0.05)
    pytest.fail("Synthetic managed application was not ready")


@pytest.fixture
def managed_plan(plan, tmp_path):
    app_root = tmp_path / "synthetic-app"
    package = app_root / "backend"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("import sys\nsys.path.append(" + repr(str(ROOT)) + ")\n__path__.append(" + repr(str(ROOT / "backend")) + ")\n")
    (package / "__main__.py").write_text(SYNTHETIC_APP)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    installation = Installation(backend="sqlite", app_root=app_root, python=Path(sys.executable).resolve(), data_dir=plan.database.parent)
    directory = private_directory(tmp_path / "plans")
    key = directory / "passphrase.txt"
    with protected_new_file(key) as handle:
        handle.write(b"Synthetic full operations passphrase")
    configured = BackupPlan(installation=installation, destination=tmp_path / "primary", second_destination=tmp_path / "replica",
                           key_files={"initial": key}, runtime_timeout_seconds=45)
    save_plan(directory, configured)
    process = subprocess.Popen([sys.executable, "-m", "backend", "--data-dir", str(installation.data_dir),
        "--host", "127.0.0.1", "--port", str(port), "--no-browser"], cwd=app_root, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    ready(installation, process)
    try:
        yield directory, configured, process, plan
    finally:
        try:
            record = selected_runtime(installation)
            if control(record)["state"] == "ready":
                with stop_owned_runtime(installation, record, timeout=45):
                    pass
        except BackupOperationError:
            pass
        if process.poll() is None:
            process.terminate()  # Only this test's directly created Popen handle.
        process.wait(timeout=10)


def test_real_backup_resume_replica_monthly_portless_restore_and_copy_retry(managed_plan, monkeypatch):
    directory, configured, process, source = managed_plan
    original = selected_runtime(configured.installation)
    real_publish = runner._publish_new
    fail = True
    def publish(partial, target):
        if fail:
            raise OSError("synthetic secondary disk unavailable")
        return real_publish(partial, target)
    monkeypatch.setattr(runner, "_publish_new", publish)
    first = runner.run_once(directory, now=NOW)
    assert first["state"] == "attention" and first["error"] == "backup_storage_unavailable"
    process.wait(timeout=5)
    after_backup = ready(configured.installation)
    assert after_backup["instance"] != original["instance"]
    with Journal(directory) as journal:
        pending = next(journal.unfinished())
        assert "resume" not in pending["document"] and "digest" in pending["document"]
        archive = Path(pending["document"]["archive"])
        assert archive.exists() and passphrase(configured).encode() not in archive.read_bytes()
        assert b"synthetic-integration-secret" not in archive.read_bytes()
    fail = False
    resumed_instance = after_backup["instance"]
    result = runner.run_once(directory, now=NOW + timedelta(minutes=16))
    assert result["state"] == "ok"
    assert ready(configured.installation)["instance"] == resumed_instance  # Copy retry caused no second downtime.
    with Journal(directory) as journal:
        backup, probe = journal.latest("backup"), journal.latest("probe")
        document = backup["document"]
        assert document["replicated"] is True
        assert runner.digest(Path(document["secondary"])) == runner.digest(archive)
        report = probe["document"]["probe_report"]
        assert report["portless"] and report["signing_key_rotated"]
        assert report["existing_installation_changed"] is False
        assert report["database_tables"] > 30
        assert not list(journal.unfinished())
    # Real restored byte/row proof, including uploads and the stopped writer image.
    from backend.services.full_recovery import restore_full_backup
    target = directory.parent / "verified-restore"
    restore_full_backup(archive, target, passphrase(configured))
    assert (target / "uploads" / "proof.bin").read_bytes() == (source.uploads / "proof.bin").read_bytes()
    with sqlite3.connect(target / "database.sqlite3") as database:
        assert database.execute("SELECT count(*) FROM backup_test_ticks").fetchone()[0] > 0
        assert database.execute("SELECT count(*) FROM payment_reversals").fetchone()[0] == 1
    (configured.key_files["initial"]).unlink()
    before = ready(configured.installation)["instance"]
    failure = runner.run_once(directory, now=NOW + timedelta(days=1))
    assert failure["error"] == "backup_key_missing_or_unreadable"
    assert ready(configured.installation)["instance"] == before


def test_killed_offline_worker_durable_resume_even_when_plan_is_disabled(managed_plan):
    directory, configured, process, _ = managed_plan
    old = selected_runtime(configured.installation)
    child = r'''
import os, sys
from pathlib import Path
from datetime import datetime, timezone
from backend.backup_operations.journal import Journal
from backend.backup_operations.runtime import selected_runtime, stop_owned_runtime
from backend.backup_operations.state import load_plan, plan_lock
directory=Path(sys.argv[1])
with plan_lock(directory):
    plan=load_plan(directory)
    with Journal(directory) as journal:
        run=journal.new(plan,'backup','2026-10-03',datetime.now(timezone.utc))
        run['document']['resume']=selected_runtime(plan.installation)
        journal.save(run)
        lease=stop_owned_runtime(plan.installation,run['document']['resume'],timeout=45)
        os._exit(19)
'''
    killed = subprocess.run([sys.executable, "-c", child, str(directory)], cwd=ROOT, timeout=60, capture_output=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert killed.returncode == 19, killed.stderr.decode(errors="replace")
    process.wait(timeout=5)
    save_plan(directory, configured.model_copy(update={"revision": 2, "enabled": False}), expected_revision=1)
    assert runner.run_once(directory, now=NOW)["state"] == "ok"
    assert ready(configured.installation)["instance"] != old["instance"]
    with Journal(directory) as journal:
        pending = next(journal.unfinished())
        assert "resume" not in pending["document"] and "digest" not in pending["document"]


def test_retention_protects_latest_restored_and_refuses_same_bytes_replacement(tmp_path):
    directory = private_directory(tmp_path / "plans")
    configured = BackupPlan(installation=Installation(backend="sqlite", app_root=tmp_path, python=Path(sys.executable), data_dir=tmp_path),
        destination=tmp_path, key_files={"initial": tmp_path / "unused"}, retention_days=1)
    with Journal(directory) as journal:
        backups = []
        for offset in range(3):
            run = journal.new(configured, "backup", f"2026-09-{offset + 1:02}", NOW - timedelta(days=10 - offset))
            with protected_new_file(Path(run["document"]["archive"])) as output:
                output.write(b"synthetic owned archive " + str(offset).encode())
            runner.remember_archive(run["document"])
            run["status"] = "complete"
            journal.save(run)
            backups.append(run)
        probe = journal.new(configured, "probe", "2026-09", NOW - timedelta(days=5))
        probe["document"]["backup_id"] = backups[0]["id"]
        probe["status"] = "complete"
        journal.save(probe)
        replaceable = Path(backups[1]["document"]["archive"])
        replaced = replaceable.with_suffix(".foreign")
        with protected_new_file(replaced) as output:
            output.write(replaceable.read_bytes())
        os.replace(replaced, replaceable)
        with pytest.raises(BackupOperationError, match="retention_archive_changed"):
            runner._retention(configured, journal, NOW)
        assert all(Path(run["document"]["archive"]).exists() for run in backups)


def test_replica_retry_refuses_replaced_staging_identity_without_removing_foreign_file(tmp_path):
    directory = private_directory(tmp_path / "plans")
    replica = private_directory(tmp_path / "replicas")
    configured = BackupPlan(installation=Installation(backend="sqlite", app_root=tmp_path, python=Path(sys.executable), data_dir=tmp_path),
        destination=tmp_path, second_destination=replica, key_files={"initial": tmp_path / "unused"})
    with Journal(directory) as journal:
        run = journal.new(configured, "backup", "2026-10-03", NOW)
        document = run["document"]
        with protected_new_file(Path(document["archive"])) as output:
            output.write(b"synthetic complete encrypted bytes")
        runner.remember_archive(document)
        partial = replica / ("." + Path(document["secondary"]).name + ".synthetic.partial")
        with protected_new_file(partial) as output:
            output.write(b"incomplete original staging")
        document["replica_partial"] = {"path": str(partial), "identity": runner.file_identity(partial)}
        journal.save(run)
        foreign = replica / "foreign-replacement"
        with protected_new_file(foreign) as output:
            output.write(b"foreign file must survive")
        os.replace(foreign, partial)
        with pytest.raises(BackupOperationError, match="secondary_staging_identity_changed"):
            runner._replicate(document, journal, run)
        assert partial.read_bytes() == b"foreign file must survive"
        assert not Path(document["secondary"]).exists()
