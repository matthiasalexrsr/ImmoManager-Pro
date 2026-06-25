import os

from backend import __main__ as launcher


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
