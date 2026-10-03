"""Fresh-process image import cannot borrow the running installation."""

import subprocess
import sys
from pathlib import Path


def test_fresh_image_import_requires_no_runtime_or_connection_factory():
    script = r'''
import importlib.abc
import sqlite3
import sys
import time

import sqlalchemy
import sqlalchemy.engine.create
import sqlalchemy.orm

blocked = {
    "backend.config", "backend.settings", "backend.auth", "backend.dependencies",
    "backend.storage", "backend.db.session", "backend.services.integrations.factory",
    "backend.services.integrations.history_store", "backend.services.integrations.runtime",
}
assert not blocked.intersection(sys.modules)

class RuntimeBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in blocked:
            raise AssertionError("unexpected runtime image dependency: " + fullname)
        return None

def no_factory(*args, **kwargs):
    raise AssertionError("unexpected image connection factory")

selected = sqlite3.connect(":memory:")
selected.execute("PRAGMA query_only=ON")
selected.execute("PRAGMA trusted_schema=OFF")
selected.execute("BEGIN")
sqlite3.connect = no_factory
sqlalchemy.create_engine = no_factory
sqlalchemy.engine.create.create_engine = no_factory
sqlalchemy.orm.sessionmaker = no_factory
sqlalchemy.orm.Session.__init__ = no_factory
sys.meta_path.insert(0, RuntimeBlocker())

from backend.services.integrations.history_types import HistoryLimits
from backend.services.providers.teha_receive_image import (
    TehaImageLimits, validate_teha_receive_image,
)
before = selected.total_changes
try:
    result = validate_teha_receive_image(
        selected, image_keys=None, history_limits=HistoryLimits(),
        image_limits=TehaImageLimits(2, 8192, 65536, 65536),
        deadline=time.monotonic() + 5,
    )
    assert not result.family_present
    assert not result.command_digest_reconstructed
    assert selected.total_changes == before and selected.in_transaction
    assert selected.execute("PRAGMA query_only").fetchone() == (1,)
    assert not blocked.intersection(sys.modules)
finally:
    selected.close()
print("selected-image fresh import boundary verified")
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "selected-image fresh import boundary verified"
