import os
import runpy
from pathlib import Path

from backend import __main__ as launcher
from backend import runtime_origins


def test_sqlite_url_uses_absolute_forward_slashes(tmp_path):
    db_path = tmp_path / "immo_manager.db"

    url = launcher._sqlite_url(str(db_path))

    assert url.startswith("sqlite:///")
    assert "\\" not in url


def test_configure_runtime_environment_creates_persistent_defaults(tmp_path, monkeypatch):
    for key in [
        "DATA_DIR",
        "UPLOADS_DIR",
        "BACKUP_DIR",
        "DATABASE_URL",
        "LOG_FILE",
        "INTEGRATION_STATE_FILE",
        "ALLOW_INMEMORY_FALLBACK",
        "SQLITE_PERSISTENT_STORE",
        "JWT_SECRET_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(launcher, "IS_FROZEN", False)

    data_dir = launcher._configure_runtime_environment(str(tmp_path))

    assert data_dir == os.path.abspath(str(tmp_path))
    assert (tmp_path / "uploads").is_dir()
    assert (tmp_path / "backups").is_dir()
    assert (tmp_path / "logs").is_dir()
    assert os.environ["DATABASE_URL"].startswith("sqlite:///")
    assert os.environ["JWT_SECRET_KEY"] != "dev-secret-key-change-in-production"
    assert (tmp_path / ".env").is_file()


def test_packageless_frozen_entry_reloads_existing_config_and_keeps_explicit_overrides(tmp_path, monkeypatch):
    # Frozen executables run this source as a script, so importing it as
    # backend.__main__ would miss relative-import failures on the second start.
    namespace = runpy.run_path(str(Path(launcher.__file__)), run_name='frozen_launcher_probe')
    configure = namespace['_configure_runtime_environment']
    assert not configure.__globals__['__package__']
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    monkeypatch.setitem(configure.__globals__, 'IS_FROZEN', True)
    monkeypatch.setitem(configure.__globals__, '_exe_dir', lambda: str(bundle))
    monkeypatch.setattr(runtime_origins, 'ENV_FILE_ORIGINS', {})
    keys = ('DATA_DIR', 'UPLOADS_DIR', 'BACKUP_DIR', 'DATABASE_URL', 'LOG_FILE', 'INTEGRATION_STATE_FILE',
            'ALLOW_INMEMORY_FALLBACK', 'SQLITE_PERSISTENT_STORE', 'JWT_SECRET_KEY', 'CORS_ORIGINS',
            'ENVIRONMENT', 'CONTRACT_WIZARD_REQUIRED')
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('IMMO_TESTVERSION', 'false')
    directory = tmp_path / 'Bestand mit Umlaut Ä'
    configure(str(directory))
    original_key = os.environ['JWT_SECRET_KEY']
    original_database = os.environ['DATABASE_URL']
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    explicit_log = str(tmp_path / 'explicit.log')
    monkeypatch.setenv('LOG_FILE', explicit_log)
    assert configure(str(directory)) == str(directory.resolve())
    assert os.environ['JWT_SECRET_KEY'] == original_key
    assert os.environ['DATABASE_URL'] == original_database
    assert os.environ['LOG_FILE'] == explicit_log
    assert runtime_origins.ENV_FILE_ORIGINS['jwt_secret_key'] == str((directory / '.env').resolve())
