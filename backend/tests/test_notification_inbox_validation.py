"""Prepared pure/raw proofs. No application, auth or store fixture imports."""

import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.services.notification_inbox_types import InboxItemActions, InboxPage, InboxQuery
from backend.services.notification_inbox_validation import (
    InboxIntegrityError,
    validate_notification_inbox_database,
    validate_notification_inbox_schema,
)


def _image(*, actor_column="actor_id VARCHAR NOT NULL", delete="CASCADE", read_type="DATETIME"):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE users(id VARCHAR PRIMARY KEY)")
    db.execute("CREATE TABLE notifications(id VARCHAR PRIMARY KEY)")
    db.execute(f"""
        CREATE TABLE notification_read_states(
            {actor_column},
            notification_id VARCHAR NOT NULL,
            read_at {read_type} NOT NULL,
            PRIMARY KEY(actor_id,notification_id),
            FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE {delete},
            FOREIGN KEY(notification_id) REFERENCES notifications(id) ON DELETE CASCADE,
            CONSTRAINT ck_notification_read_identity
                CHECK(length(actor_id)>0 AND length(notification_id)>0)
        )
    """)
    db.execute("INSERT INTO users VALUES ('reader-a')")
    db.execute("INSERT INTO notifications VALUES ('notice-a')")
    return db


def test_query_and_live_page_forbid_request_authority_and_fake_snapshots():
    assert InboxQuery().limit == 10
    for values in ({"actor_id": "other"}, {"snapshot_token": "fake"},
                   {"read_actions_enabled": True}, {"limit": 0},
                   {"limit": 101}, {"limit": True}, {"after": ""}, {"status": "archived"}):
        with pytest.raises(ValidationError):
            InboxQuery(**values)
    page = InboxPage(items=[], full_count=100001, unread_count=100001,
                     has_more=False, next_cursor=None)
    assert page.snapshot_token is None and page.consistency == "live"
    assert page.actions.mark_all_read is False
    assert InboxItemActions().mark_read is False
    with pytest.raises(ValidationError):
        InboxPage(items=[], full_count=0, unread_count=0, has_more=False,
                  next_cursor=None, snapshot_token="fake")


def test_raw_legacy_absence_and_incomplete_read_pair_schema():
    with sqlite3.connect(":memory:") as db:
        assert validate_notification_inbox_database(db) is False
        db.execute("CREATE TABLE notification_read_states(actor_id VARCHAR)")
        with pytest.raises(InboxIntegrityError):
            validate_notification_inbox_schema(db)


@pytest.mark.parametrize("options", [
    {"actor_column": "actor_id VARCHAR"},
    {"delete": "RESTRICT"},
    {"read_type": "TEXT"},
])
def test_raw_read_pair_requires_native_shape(options):
    db = _image(**options)
    try:
        with pytest.raises(InboxIntegrityError):
            validate_notification_inbox_schema(db)
    finally:
        db.close()


def test_raw_read_state_validates_actual_parents_without_dml():
    db = _image()
    try:
        db.execute("INSERT INTO notification_read_states VALUES ('reader-a','notice-a',?)",
                   (datetime(2026, 10, 3, 12, 30).isoformat(sep=" "),))
        queries = []
        db.set_trace_callback(queries.append)
        assert validate_notification_inbox_database(db)
        assert queries and all(row.lstrip().upper().startswith(("SELECT", "PRAGMA"))
                               for row in queries)
        db.set_trace_callback(None)
        # Declared FKs in an untrusted raw image may have been disabled.
        db.execute("UPDATE notification_read_states SET actor_id='missing-reader'")
        with pytest.raises(InboxIntegrityError, match="parent_invalid"):
            validate_notification_inbox_database(db)
    finally:
        db.close()


@pytest.mark.parametrize("value", ["", "2026-10-03", "bad-time", "2026-10-03 12:30:00+00:00"])
def test_raw_read_time_is_a_complete_stored_naive_utc_datetime(value):
    db = _image()
    try:
        db.execute("INSERT INTO notification_read_states VALUES ('reader-a','notice-a',?)", (value,))
        with pytest.raises(InboxIntegrityError, match="state_invalid"):
            validate_notification_inbox_database(db)
    finally:
        db.close()


def test_raw_validator_deadline_is_read_only_and_fail_closed():
    db = _image()
    try:
        with pytest.raises(InboxIntegrityError, match="timeout"):
            validate_notification_inbox_database(db, deadline=0)
        assert db.execute("SELECT count(*) FROM notification_read_states").fetchone()[0] == 0
    finally:
        db.close()


def test_fresh_subprocess_pure_imports_reject_auth_settings_app_store(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = """
import importlib.abc
import sys
sys.path.insert(0, sys.argv[1])
blocked = {
    'backend.auth', 'backend.config', 'backend.settings', 'backend.dependencies',
    'backend.app', 'backend.storage', 'backend.repositories', 'backend.db.session',
}
class DenyRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + '.') for name in blocked):
            raise AssertionError('Runtime import forbidden: ' + fullname)
sys.meta_path.insert(0, DenyRuntime())
from backend.services.notification_inbox_types import InboxQuery
from backend.services.notification_inbox_validation import validate_notification_inbox_database
assert InboxQuery().limit == 10
import sqlite3
db = sqlite3.connect(':memory:')
assert validate_notification_inbox_database(db) is False
db.close()
assert not any(name in sys.modules for name in blocked)
"""
    result = subprocess.run([sys.executable, "-I", "-c", script, str(root)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
