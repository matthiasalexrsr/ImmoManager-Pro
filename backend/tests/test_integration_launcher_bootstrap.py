"""Real owned CLI lifetime/bootstrap, stopped at the actual app import boundary."""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.backup_operations.runtime import runtime_directory
from backend.backup_operations.state import FileLease, private_directory
from backend.services.integrations.runtime_factory import configured_runtime_store
from backend.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
KEY = base64.urlsafe_b64encode(b"synthetic-launcher-key".ljust(32, b"0")).decode()
OTHER_KEY = base64.urlsafe_b64encode(b"synthetic-wrong-key".ljust(32, b"0")).decode()
PROBE = r'''
import json, os, runpy, sys
from pathlib import Path
class AppBoundary:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "backend.app":
            from backend.backup_operations.runtime import runtime_directory
            from backend.backup_operations.state import FileLease
            from backend.backup_operations.plan import BackupOperationError
            from backend.config import settings
            from backend.services.integrations.runtime_factory import configured_runtime_store
            from backend.services.integrations.config_store import ConfigStoreError
            try:
                with FileLease(runtime_directory(Path(settings.data_dir)) / "installation.lock"):
                    raise AssertionError("app reached without actual lifetime exclusion")
            except BackupOperationError as error:
                assert error.code == "installation_busy"
            state = configured_runtime_store(settings.model_dump(mode="json"))
            try:
                value = state.load()
                result = {"load": "authenticated", "unknown_preserved": value.get("unknown") == {"exact": "future field"}}
            except ConfigStoreError as error:
                result = {"load": error.code}
            print("APP_BOUNDARY " + json.dumps(result))
            raise SystemExit(73)
sys.meta_path.insert(0, AppBoundary())
sys.argv = ["backend", "--data-dir", os.environ["DATA_DIR"], "--no-browser", "--port", "0"]
if os.environ.get("EXPLICIT_INTEGRATION_INIT") == "yes":
    sys.argv.append("--initialize-integrations")
runpy.run_module("backend", run_name="__main__")
'''


def environment(directory, *, key=KEY):
    values = {
        "DATA_DIR": str(directory), "DATABASE_URL": "sqlite:///" + (directory / "never.db").as_posix(),
        "UPLOADS_DIR": str(directory / "uploads"), "BACKUP_DIR": str(directory / "backups"),
        "INTEGRATION_STATE_FILE": str(directory / "integrations.json"),
        "ENCRYPTION_KEY": key, "ENCRYPTION_INDEX_KEY": KEY,
        "JWT_SECRET_KEY": "synthetic-launcher-signing-key", "ENVIRONMENT": "development",
        "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
    }
    inherited = {name: value for name, value in os.environ.items() if name.lower() not in Settings.model_fields}
    return {**inherited, **values}


def launch(directory, *, initialize=False, key=KEY):
    values = environment(directory, key=key)
    values["EXPLICIT_INTEGRATION_INIT"] = "yes" if initialize else "no"
    result = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=values,
                            capture_output=True, text=True, timeout=30)
    # Any unexpected output may contain sensitive configuration diagnostics.
    assert result.returncode in {1, 73}, "Native launcher probe did not stop at its expected safe boundary"
    assert not (directory / "never.db").exists()
    assert not (directory / "logs" / "immomanager.log").exists()
    return result


def boundary(result):
    assert result.returncode == 73
    line = next(line for line in result.stdout.splitlines() if line.startswith("APP_BOUNDARY "))
    return json.loads(line.removeprefix("APP_BOUNDARY "))


def test_actual_explicit_cli_initializes_under_lifetime_then_repeats_without_replacing_unknowns(tmp_path):
    directory = tmp_path / "fresh"
    first = launch(directory, initialize=True)
    assert boundary(first)["load"] == "authenticated"
    path = directory / "integrations.json"
    assert json.loads(path.read_bytes())["format"] == "immomanager/integration-state-encrypted/v1"
    store = configured_runtime_store({name.lower(): value for name, value in environment(directory).items()})
    store.update(lambda current: {**current, "unknown": {"exact": "future field"}})
    original = path.read_bytes()
    assert boundary(launch(directory, initialize=True)) == {"load": "authenticated", "unknown_preserved": True}
    assert path.read_bytes() == original
    assert boundary(launch(directory))["load"] == "authenticated"
    assert path.read_bytes() == original


@pytest.mark.parametrize("content,code", [(None, "state_missing"), (b'{"unknown":{"exact":"future field"}}', "plaintext_state_requires_migration")])
def test_normal_actual_cli_preserves_missing_or_legacy_state_for_explicit_recovery(tmp_path, content, code):
    directory = tmp_path / "existing"
    directory.mkdir()
    path = directory / "integrations.json"
    if content is not None:
        path.write_bytes(content)
    assert boundary(launch(directory)) == {"load": code}
    assert path.read_bytes() == content if content is not None else not path.exists()


def test_requested_initialization_refuses_actual_legacy_file_before_app_with_nonzero_status(tmp_path):
    directory = tmp_path / "legacy"
    directory.mkdir()
    path = directory / "integrations.json"
    original = b'{"config":{"email":{"password":"synthetic-private-legacy-value"}}}'
    path.write_bytes(original)
    result = launch(directory, initialize=True)
    assert result.returncode == 1
    assert "APP_BOUNDARY" not in result.stdout
    assert "plaintext_state_requires_migration" in result.stdout
    assert "synthetic-private-legacy-value" not in result.stdout + result.stderr
    assert path.read_bytes() == original


def test_wrong_key_explicit_initialization_refuses_before_actual_app_without_replacing_ciphertext(tmp_path):
    directory = tmp_path / "wrong-key"
    assert boundary(launch(directory, initialize=True))["load"] == "authenticated"
    path = directory / "integrations.json"
    original = path.read_bytes()
    result = launch(directory, initialize=True, key=OTHER_KEY)
    assert result.returncode == 1
    assert "APP_BOUNDARY" not in result.stdout
    assert "encrypted_state_unreadable" in result.stdout
    assert path.read_bytes() == original


def test_actual_held_installation_blocks_explicit_bootstrap_before_configuration_or_state(tmp_path):
    directory = tmp_path / "held"
    directory.mkdir()
    with FileLease(private_directory(runtime_directory(directory)) / "installation.lock"):
        result = launch(directory, initialize=True)
    assert result.returncode == 1
    assert "APP_BOUNDARY" not in result.stdout
    assert "installation_busy" in result.stdout + result.stderr
    assert not (directory / ".env").exists()
    assert not (directory / "integrations.json").exists()
