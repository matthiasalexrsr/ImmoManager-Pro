"""Tests for dependency wiring and backend selection."""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_sqlite_url_uses_sqlalchemy_store():
    """Verify that SQLite URL with persistent_store=True uses SQLAlchemyStore.

    Runs in a subprocess to avoid polluting module-level store references
    used by other tests.
    """
    result = subprocess.run(
        [
            sys.executable, "-c",
            "import os; "
            "os.environ['SQLITE_PERSISTENT_STORE'] = 'true'; "
            "os.environ['DATABASE_URL'] = 'sqlite:///:memory:'; "
            "from backend import dependencies as deps; "
            "assert deps._scoped_session is not None, 'scoped_session should be set'; "
            "assert deps.store.__class__.__name__ == 'SQLAlchemyStore', "
            "f'Expected SQLAlchemyStore, got {deps.store.__class__.__name__}'; "
            "db_gen = deps.get_db(); db = next(db_gen); "
            "assert db is not None; db_gen.close(); "
            "print('OK')",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Subprocess failed: {result.stderr}"
    assert "OK" in result.stdout
