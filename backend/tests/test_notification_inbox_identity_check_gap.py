"""Prepared expected-refusal cases for the known CHECK gap; UNEXECUTED.

Source control flow currently accepts these native shapes. Strict xfail keeps
that known absence visible; it is not a green safety/validator acceptance. When
the separately reviewed validator exists, remove xfail and obtain actual proof.
"""

import sqlite3
from contextlib import closing

import pytest

from backend.services.notification_inbox_validation import (
    InboxIntegrityError,
    validate_notification_inbox_database,
)


def _untrusted_image(check):
    connection = sqlite3.connect(":memory:")
    clause = "" if check is None else f", CONSTRAINT ck_notification_read_identity CHECK ({check})"
    connection.executescript(f"""
        CREATE TABLE users(id VARCHAR PRIMARY KEY);
        CREATE TABLE notifications(id VARCHAR PRIMARY KEY);
        CREATE TABLE notification_read_states(
            actor_id VARCHAR NOT NULL, notification_id VARCHAR NOT NULL,
            read_at DATETIME NOT NULL, PRIMARY KEY(actor_id,notification_id),
            FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(notification_id) REFERENCES notifications(id) ON DELETE CASCADE
            {clause}
        );
        INSERT INTO users VALUES ('reader-a');
        INSERT INTO notifications VALUES ('notice-a');
        INSERT INTO notification_read_states VALUES ('reader-a','notice-a','2026-10-03 12:15:00');
    """)
    return connection


@pytest.mark.xfail(strict=True, reason="Known missing native CHECK proof; not a passed safety case")
@pytest.mark.parametrize("check", [
    None,
    "1",
    "length(actor_id)>0 OR 1",
    "length(actor_id)>0",
    "length('actor_id')>0 AND length('notification_id')>0",
], ids=["missing", "always-true", "or-true", "one-identity", "literal-arguments"])
def test_actual_raw_shape_requires_both_native_identity_guards(check):
    with closing(_untrusted_image(check)) as connection:
        original = list(connection.iterdump())
        statements = []
        connection.set_trace_callback(statements.append)
        try:
            with pytest.raises(InboxIntegrityError):
                validate_notification_inbox_database(connection)
        finally:
            connection.set_trace_callback(None)
            assert list(connection.iterdump()) == original
            assert all(sql.lstrip().upper().startswith(("SELECT", "PRAGMA")) for sql in statements)
