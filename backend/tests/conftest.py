import base64
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("ENCRYPTION_KEY", base64.urlsafe_b64encode(b"synthetic-account-key".ljust(32, b"0")).decode("ascii"))
os.environ.setdefault("ENCRYPTION_INDEX_KEY", base64.urlsafe_b64encode(b"synthetic-index-key".ljust(32, b"0")).decode("ascii"))

# Select the backend before application imports initialize its database.
_backend = os.environ.get("TEST_STORE_BACKEND", "memory")
_test_database_directory: Path | None = None
if _backend == "sql":
    os.environ.setdefault("SQLITE_PERSISTENT_STORE", "true")
    os.environ.setdefault("ALLOW_INMEMORY_FALLBACK", "false")
    # Each process owns its directory. Never delete another run's database,
    # including when the caller explicitly supplies DATABASE_URL.
    if "DATABASE_URL" not in os.environ:
        _test_database_directory = Path(tempfile.mkdtemp(prefix="immomanager-tests-"))
        _database = _test_database_directory / "test.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{_database.as_posix()}"
else:
    os.environ.setdefault("SQLITE_PERSISTENT_STORE", "false")
    os.environ.setdefault("ALLOW_INMEMORY_FALLBACK", "true")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_unconfigure():
    """Close application connections before removing only our owned directory."""
    if _test_database_directory is None:
        return
    dependencies = sys.modules.get("backend.dependencies")
    if dependencies is not None:
        dependencies.cleanup_session()
    database_module = sys.modules.get("backend.db.session")
    if database_module is not None:
        database_module.engine.dispose()
    shutil.rmtree(_test_database_directory, ignore_errors=True)
