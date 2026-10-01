"""Offline CLI refusal paths and runtime-directory wiring; no real update runs."""

import socket
from types import SimpleNamespace

import pytest

from backend import __main__ as launcher
from backend import config, maintenance, updater
from backend.tests.test_updater import isolated_update as shared_update_fixture

isolated_update = shared_update_fixture


def test_offline_flag_is_required_before_any_runtime_changes(tmp_path):
    with pytest.raises(SystemExit) as error:
        maintenance.main(["--data-dir", str(tmp_path)])
    assert error.value.code == 2
    assert list(tmp_path.iterdir()) == []


def test_listening_application_prevents_offline_update(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "_configure_runtime_environment", lambda directory: pytest.fail("Live update must not write runtime configuration"))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert maintenance.main(["--offline", "--data-dir", str(tmp_path), "--port", str(port)]) == 1
    assert list(tmp_path.iterdir()) == []


def test_nonexistent_data_directory_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(maintenance, "_listener_running", lambda port: False)
    assert maintenance.main(["--offline", "--data-dir", str(tmp_path / "missing")]) == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("success", [False, True])
def test_cli_loads_existing_runtime_and_propagates_update_result_without_actual_network_or_git(isolated_update, monkeypatch, capsys, success):
    calls = []
    runtime = isolated_update["runtime"]
    settings = SimpleNamespace(data_dir=str(runtime), backup_dir=str(isolated_update["backups"]),
                               update_repo_url="https://github.com/example/project", update_allow_in_production=False)
    monkeypatch.setattr(maintenance, "_listener_running", lambda port: False)
    monkeypatch.setattr(launcher, "_configure_runtime_environment", lambda directory: calls.append(("runtime", directory)))
    monkeypatch.setattr(config, "Settings", lambda **kwargs: settings)
    monkeypatch.setattr(config, "settings", config.settings)
    monkeypatch.setattr(updater, "settings", updater.settings)
    def update(target_version, offline):
        calls.append(("update", target_version, offline))
        assert updater._UPDATE_DIR == runtime / ".updates"
        assert updater._BACKUP_DIR == isolated_update["backups"]
        assert updater.settings.update_allow_in_production
        return {"success": success, "message": "verified result"}
    monkeypatch.setattr(updater, "apply_update", update)
    status = maintenance.main(["--offline", "--data-dir", str(runtime), "--target-version", "1.2.0"])
    assert status == (0 if success else 1)
    assert calls == [("runtime", str(runtime.resolve())), ("update", "1.2.0", True)]
    assert "verified result" in capsys.readouterr().out


def test_selected_installation_configuration_overrides_inherited_foreign_environment(isolated_update, monkeypatch):
    runtime = isolated_update["runtime"]
    selected_database = "sqlite:///" + isolated_update["database"].as_posix()
    (runtime / ".env").write_text(f"DATABASE_URL={selected_database}\nJWT_SECRET_KEY=synthetic-selected-installation-key\n", encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(runtime.parent / "foreign-installation"))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///foreign.db")
    monkeypatch.setenv("JWT_SECRET_KEY", "synthetic-foreign-key")
    monkeypatch.setattr(maintenance, "_listener_running", lambda port: False)
    monkeypatch.setattr(launcher, "_configure_runtime_environment", lambda directory: None)
    monkeypatch.setattr(config, "settings", config.settings)
    monkeypatch.setattr(updater, "settings", updater.settings)
    def update(target_version, offline):
        assert updater.settings.data_dir == str(runtime.resolve())
        assert updater.settings.database_url == selected_database
        assert updater.settings.jwt_secret_key == "synthetic-selected-installation-key"
        return {"success": True}
    monkeypatch.setattr(updater, "apply_update", update)
    assert maintenance.main(["--offline", "--data-dir", str(runtime)]) == 0
