"""Pure proposed recovery connection hook; profile policy belongs to Root.

A false result means the entire family is absent, not that the image is a
recognized old release. The caller must prove its archive profile separately.
"""

import sqlite3

from sqlalchemy.engine import Connection

from .notification_inbox_validation import validate_notification_inbox_database


def validate_notification_inbox_recovery(
    connection: sqlite3.Connection | Connection, *, deadline: float | None = None
) -> bool:
    """Validate actual personal facts without loading runtime state or modifying DB.

    Root must require true for current/M2 images. Only a fully proved older
    archive may consume false. Existing malformed families always raise the
    original InboxIntegrityError from the shared structural/data validator.
    """
    return validate_notification_inbox_database(connection, deadline=deadline)
