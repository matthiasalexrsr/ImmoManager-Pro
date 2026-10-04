"""Real auth/domain locks, isolated process; no mocked user dictionary."""

import os
import subprocess
import sys

PROBE = r'''
from threading import Event, RLock, Thread, current_thread
from backend import auth
from backend.storage import InMemoryStore
from backend.services.contract_correspondence import work
from backend.services.tenant_privacy import _memory_privacy_lock

auth._user_store = auth.InMemoryUserStore()
auth._auth_session_factory = None
user = auth.register_user('synthetic-lock-member', 'locks@example.test', 'Synthetic', 'Strong123', 'verwalter')
real_account = auth._user_store._lock
assert isinstance(real_account, type(RLock()))
account_attempt, writer_entered, writer_done, privacy_done = Event(), Event(), Event(), Event()
errors = []
class ObservedAccount:
    def __enter__(self):
        if current_thread().name == 'private-probe':
            account_attempt.set()
        real_account.acquire()
        return self
    def __exit__(self, *args):
        real_account.release()
auth._user_store._lock = ObservedAccount()
store = InMemoryStore()
def writer():
    try:
        with work(store, user.id, write=True):
            writer_entered.set()
            assert account_attempt.wait(3)
        writer_done.set()
    except BaseException as exc:
        errors.append(type(exc).__name__)
def privacy():
    try:
        assert writer_entered.wait(3)
        with _memory_privacy_lock():
            privacy_done.set()
    except BaseException as exc:
        errors.append(type(exc).__name__)
a, b = Thread(target=writer, name='publisher-probe', daemon=True), Thread(target=privacy, name='private-probe', daemon=True)
a.start(); b.start()
a.join(5); b.join(5)
assert not errors and writer_done.is_set() and privacy_done.is_set(), (errors, writer_done.is_set(), privacy_done.is_set())
print('CORRESPONDENCE_MEMORY_LOCK_ORDER_OK')
'''


def test_actual_memory_auth_refresh_and_privacy_complete_without_lock_cycle():
    environment = os.environ.copy()
    environment.update(TEST_STORE_BACKEND="memory", SQLITE_PERSISTENT_STORE="false", ALLOW_INMEMORY_FALLBACK="true",
        AUTO_SEED_DEMO_DATA="false", BACKUP_SCHEDULER_ENABLED="false", OPERATIONAL_SCHEDULER_ENABLED="false")
    environment.pop("DATABASE_URL", None)
    result = subprocess.run([sys.executable, "-c", PROBE], env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "CORRESPONDENCE_MEMORY_LOCK_ORDER_OK" in result.stdout
