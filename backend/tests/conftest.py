import os
import sys
import tempfile
from pathlib import Path

import pytest

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

# Scheduled jobs would create tasks/notifications in the middle of unrelated tests.
os.environ.setdefault("JOB_SCHEDULER_ENABLED", "false")
os.environ.setdefault("BACKUP_SCHEDULE_ENABLED", "false")

# Integration settings and the secret key file of this test process, never the checkout's.
_runtime = Path(tempfile.mkdtemp(prefix="immo-test-runtime-"))
os.environ.setdefault("INTEGRATION_STATE_FILE", str(_runtime / "integrations.json"))
os.environ.setdefault("SECRET_KEY_FILE", str(_runtime / "secrets" / "keyring.json"))

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_private_memory_families(monkeypatch):
    """New private families are outside the legacy dataclass clear_all fixture.

    Give each test its own journal without changing production reset/restore
    guards. SQL tests already own their database and reset all mapped tables.
    """
    from backend import dependencies
    store = dependencies.store

    if not hasattr(store, 'db'):
        monkeypatch.setitem(store.__dict__, '_integration_connections', {})
    yield


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    # Run after ALL fixture finalizers, including monkeypatch restoration.
    # A module's cleanup fixture can itself perform legacy read queries; the
    # function fixture above may finalize before that fixture does.
    yield
    from backend import dependencies

    # Direct service/router tests can leave a read-only legacy caller Session.
    # They do not pass through request middleware. Close it at the test boundary
    # so connection-return tests measure their own requests, not a prior caller.
    # Assertions inside those tests still run before this cleanup.
    dependencies.cleanup_session()
