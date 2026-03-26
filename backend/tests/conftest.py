import os
import sys
import tempfile
from pathlib import Path

# Select store backend for tests.  Set TEST_STORE_BACKEND=sql to exercise
# the SQLAlchemy persistence path (default: in-memory store).
_backend = os.environ.get("TEST_STORE_BACKEND", "memory")
if _backend == "sql":
    os.environ.setdefault("SQLITE_PERSISTENT_STORE", "true")
    os.environ.setdefault("ALLOW_INMEMORY_FALLBACK", "false")
    # Use a temporary file-based SQLite DB so all connections share one DB
    _tmpdb = os.path.join(tempfile.gettempdir(), "immo_test.db")
    if os.path.exists(_tmpdb):
        os.remove(_tmpdb)
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmpdb}")
else:
    os.environ.setdefault("SQLITE_PERSISTENT_STORE", "false")
    os.environ.setdefault("ALLOW_INMEMORY_FALLBACK", "true")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
