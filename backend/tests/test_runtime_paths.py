from pathlib import Path

from backend import paths


def test_runtime_dirs_follow_configured_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths.settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(paths.settings, "uploads_dir", "")
    monkeypatch.setattr(paths.settings, "backup_dir", "")

    assert paths.get_data_dir() == tmp_path.resolve()
    assert paths.get_uploads_dir() == tmp_path.resolve() / "uploads"
    assert paths.get_backup_dir() == tmp_path.resolve() / "backups"

    paths.ensure_runtime_dirs()

    assert (tmp_path / "uploads").is_dir()
    assert (tmp_path / "backups").is_dir()
    assert (tmp_path / "logs").is_dir()


def test_sqlite_url_for_path_uses_absolute_posix_path(tmp_path):
    db_path = tmp_path / "data" / "immo_manager.db"

    url = paths.sqlite_url_for_path(db_path)

    assert url.startswith("sqlite:///")
    assert Path(url.removeprefix("sqlite:///")).is_absolute()
