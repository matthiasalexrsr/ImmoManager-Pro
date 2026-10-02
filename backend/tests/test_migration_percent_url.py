"""The actual migration runner preserves percent-encoded URL characters."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_actual_chain_preserves_percent_characters_in_database_url(tmp_path):
    path = tmp_path / "database%3Doptions%40credentials.sqlite"
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=120,
        env={**os.environ, "DATABASE_URL": "sqlite:///" + path.as_posix()})
    assert result.returncode == 0, result.stderr
    assert path.is_file()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
