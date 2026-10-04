"""Prepared isolated raw recovery-hook proofs, not full-container acceptance."""

import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from backend.services.notification_inbox_recovery import validate_notification_inbox_recovery
from backend.services.notification_inbox_validation import InboxIntegrityError


def _image():
    connection = sqlite3.connect(":memory:")
    connection.executescript("""
        CREATE TABLE users(id VARCHAR PRIMARY KEY);
        CREATE TABLE notifications(id VARCHAR PRIMARY KEY, status VARCHAR, read_at DATETIME);
        CREATE TABLE notification_read_states(
            actor_id VARCHAR NOT NULL, notification_id VARCHAR NOT NULL,
            read_at DATETIME NOT NULL,
            PRIMARY KEY(actor_id,notification_id),
            FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(notification_id) REFERENCES notifications(id) ON DELETE CASCADE,
            CONSTRAINT ck_notification_read_identity
                CHECK(length(actor_id)>0 AND length(notification_id)>0)
        );
        INSERT INTO users VALUES ('reader-a'),('reader-b');
        INSERT INTO notifications VALUES ('notice','read','2026-10-02 12:00:00');
        INSERT INTO notification_read_states VALUES
            ('reader-a','notice','2026-10-03 12:15:00.123456'),
            ('reader-b','notice','2026-10-03 12:30:00.654321');
    """)
    return connection


def test_recovery_hook_preserves_actual_personal_and_global_facts_and_transaction():
    connection = _image()
    try:
        connection.execute("BEGIN")
        original = list(connection.iterdump())
        statements = []
        connection.set_trace_callback(statements.append)
        assert validate_notification_inbox_recovery(connection)
        assert connection.in_transaction
        assert statements and all(sql.lstrip().upper().startswith(("SELECT", "PRAGMA")) for sql in statements)
        connection.set_trace_callback(None)
        assert list(connection.iterdump()) == original
    finally:
        connection.close()


def test_recovery_hook_absence_is_only_an_observation_and_partial_family_refuses():
    with closing(sqlite3.connect(":memory:")) as connection:
        assert validate_notification_inbox_recovery(connection) is False
        connection.execute("CREATE TABLE notification_read_states(actor_id VARCHAR)")
        with pytest.raises(InboxIntegrityError):
            validate_notification_inbox_recovery(connection)


@pytest.mark.parametrize("statement,code", [
    ("UPDATE notification_read_states SET actor_id='absent-actor' WHERE actor_id='reader-a'", "parent_invalid"),
    ("UPDATE notification_read_states SET notification_id='absent-notice' WHERE actor_id='reader-a'", "parent_invalid"),
    ("UPDATE notification_read_states SET read_at='2026-10-03' WHERE actor_id='reader-a'", "state_invalid"),
    ("UPDATE notification_read_states SET read_at='2026-10-03 12:15:00+01:00' WHERE actor_id='reader-a'", "state_invalid"),
])
def test_recovery_hook_refuses_bad_facts_without_repair(statement, code):
    connection = _image()
    try:
        connection.execute(statement)
        original = list(connection.iterdump())
        with pytest.raises(InboxIntegrityError, match=code):
            validate_notification_inbox_recovery(connection)
        assert list(connection.iterdump()) == original
    finally:
        connection.close()


def test_recovery_hook_deadline_refuses_without_mutation():
    connection = _image()
    try:
        original = list(connection.iterdump())
        with pytest.raises(InboxIntegrityError, match="timeout"):
            validate_notification_inbox_recovery(connection, deadline=0)
        assert list(connection.iterdump()) == original
    finally:
        connection.close()


def test_recovery_hook_import_rejects_runtime_and_orm_modules(tmp_path):
    # Prepared bounded import boundary; no subprocess was started while authoring.
    root = Path(__file__).resolve().parents[2]
    script = """
import importlib.abc
import sys
sys.path.insert(0, sys.argv[1])
blocked = ('backend.auth', 'backend.config', 'backend.settings', 'backend.dependencies',
           'backend.app', 'backend.storage', 'backend.repositories', 'backend.db.orm_models',
           'backend.db.notification_inbox_models', 'backend.db.session')
class DenyRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + '.') for name in blocked):
            raise AssertionError('Runtime import forbidden: ' + fullname)
sys.meta_path.insert(0, DenyRuntime())
from backend.services.notification_inbox_recovery import validate_notification_inbox_recovery
import sqlite3
from contextlib import closing
with closing(sqlite3.connect(':memory:')) as connection:
    assert validate_notification_inbox_recovery(connection) is False
assert not any(name in sys.modules for name in blocked)
"""
    result = subprocess.run([sys.executable, "-I", "-c", script, str(root)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
