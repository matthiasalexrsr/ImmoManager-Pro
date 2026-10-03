"""Native central entrypoints, using only owned synthetic installations."""

import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from backend import recovery
from backend.backup_operations.plan import BackupOperationError, Installation
from backend.backup_operations.process import ProcessWitness
from backend.backup_operations.runtime import (
    control,
    runtime_directory,
    selected_runtime,
    stop_owned_runtime,
    stopped_runtime_lease,
)
from backend.backup_operations.state import FileLease, private_directory
from backend.services.full_recovery import create_full_backup, restore_full_backup
from backend.services.recovery_archive import RecoveryError
from backend.tests.test_full_recovery import PASSPHRASE
from backend.tests.test_full_recovery import plan as plan
from backend.tests.test_full_recovery import runtime_template as runtime_template

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("module", ["backend.app", "backend.dependencies"])
def test_native_central_import_is_fenced_before_settings_sql_logs_and_workers(tmp_path, module):
    directory = tmp_path / "held-installation"
    directory.mkdir()
    environment = dict(os.environ, DATA_DIR=str(directory), DATABASE_URL="sqlite:///" + (directory / "never.db").as_posix(),
                       INTEGRATION_STATE_FILE=str(directory / "never-integrations.json"), PYTHONUTF8="1")
    script = '''
import importlib, sys
from backend.backup_operations.plan import BackupOperationError
class RefuseLateImport:
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"backend.config", "backend.auth", "backend.logging_config", "backend.db.session"}:
            raise AssertionError("writer/configuration reached before installation fence")
sys.meta_path.insert(0, RefuseLateImport())
try:
    importlib.import_module(sys.argv[1])
except BackupOperationError as error:
    assert error.code == "installation_busy"
    print("CENTRAL_IMPORT_FENCED")
else:
    raise AssertionError("held installation was opened")
'''
    with FileLease(private_directory(runtime_directory(directory)) / "installation.lock"):
        result = subprocess.run([sys.executable, "-c", script, module], cwd=ROOT, env=environment,
                                capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "CENTRAL_IMPORT_FENCED" in result.stdout
    assert not (directory / "never.db").exists()
    assert not (directory / "never-integrations.json").exists()
    assert not (directory / "logs").exists()


def test_manual_offline_backup_refuses_held_lifetime_before_plan_and_sql(plan, monkeypatch):
    before = plan.database.read_bytes()
    monkeypatch.setattr(recovery, "_plan", lambda *_: pytest.fail("plan reached while installation is active"))
    with FileLease(private_directory(runtime_directory(plan.database.parent)) / "installation.lock"):
        with pytest.raises(RecoveryError, match="Installation wird verwendet"):
            with recovery._offline_backup(SimpleNamespace(data_dir=plan.database.parent)):
                pytest.fail("held offline backup was admitted")
    assert plan.database.read_bytes() == before


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_actual_full_restored_recovery_run_is_managed_and_stops_before_lease_release(plan, tmp_path):
    archive, target = tmp_path / "managed.immobak", tmp_path / "restored"
    create_full_backup(plan, archive, PASSPHRASE, offline=True)
    restore_full_backup(archive, target, PASSPHRASE)
    port = _free_port()
    installation = Installation(backend="sqlite", app_root=ROOT, python=Path(sys.executable).resolve(), data_dir=target)
    from backend.settings import Settings
    environment = {key: value for key, value in os.environ.items() if key.lower() not in Settings.model_fields}
    environment["PYTHONUTF8"] = "1"
    log = tmp_path / "recovered-runtime.log"
    with log.open("wb") as output:
        process = subprocess.Popen([sys.executable, "-m", "backend.recovery", "run", "--data-dir", str(target),
                                    "--port", str(port)], cwd=ROOT, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        record = None
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pytest.fail("recovery-run exited before readiness: " + log.read_text(encoding="utf-8", errors="replace")[-4000:])
                try:
                    with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                        assert response.status == 200
                    record = selected_runtime(installation)
                    if control(record)["state"] == "ready":
                        break
                except (URLError, OSError):
                    pass
                time.sleep(0.1)
            assert record is not None and control(record)["state"] == "ready"
            assert record["data_dir"] == str(target)
            # On Windows a venv Python launcher can own a child interpreter;
            # the authenticated runtime records that actual process identity.
            with ProcessWitness(record["process"]["pid"], record["process"]["birth"]) as witness:
                assert not witness.wait(0)
            assert record["configuration_sha256"]
            lease = stop_owned_runtime(installation, record, timeout=30)
            try:
                assert process.wait(timeout=5) == 0
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", port))
                with sqlite3.connect(target / "database.sqlite3") as db:
                    assert db.execute("SELECT COUNT(*) FROM payment_reversals").fetchone()[0] == 1
                    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
                assert (target / "uploads" / "proof.bin").read_bytes() == (plan.uploads / "proof.bin").read_bytes()
            finally:
                lease.__exit__(None, None, None)
        finally:
            try:
                # A Windows venv launcher can exit before its actual child.
                # Always stop/check the authenticated owned lifetime first.
                try:
                    remaining = selected_runtime(installation)
                except BackupOperationError as error:
                    if error.code != "managed_runtime_not_registered_for_installation":
                        raise
                else:
                    try:
                        control(remaining)
                    except BackupOperationError as error:
                        if error.code != "managed_runtime_control_unavailable":
                            raise
                        cleanup_lease = stopped_runtime_lease(installation, remaining, timeout=15)
                    else:
                        cleanup_lease = stop_owned_runtime(installation, remaining, timeout=30)
                    cleanup_lease.__exit__(None, None, None)
            finally:
                if process.poll() is None:
                    # This is solely the exact launcher created by this test.
                    process.terminate()
                    process.wait(timeout=15)
