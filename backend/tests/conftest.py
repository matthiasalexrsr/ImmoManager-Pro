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
    # Never remove or reset caller-owned databases. Independent test processes
    # get independent fixtures; retain them for debugging after a failure.
    if not os.environ.get("DATABASE_URL"):
        _tmpdir = Path(tempfile.mkdtemp(prefix="immo-tests-"))
        os.environ["DATABASE_URL"] = f"sqlite:///{(_tmpdir / 'test.db').as_posix()}"
else:
    os.environ.setdefault("SQLITE_PERSISTENT_STORE", "false")
    os.environ.setdefault("ALLOW_INMEMORY_FALLBACK", "true")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
