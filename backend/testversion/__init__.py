"""Test version: a realistic data set (15 properties, three years of history) and master logins.

Started with `python -m backend --testversion` (or IMMO_TESTVERSION=true, as the Windows
test package does). On the first start, with an empty database, it creates the users
and builds the history through the app's API; afterwards it only starts the app.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Callable, Optional

from .dataset import MASTERS, PASSWORD, STAFF


def is_empty() -> bool:
    from ..dependencies import store

    return not store.list_portfolios()


def create_users(progress: Callable[[str], None] = print) -> dict[str, dict]:
    """The two master logins (owners) and four staff users; all with the start password."""
    from ..auth import create_access_token, get_user_by_username, register_user

    headers: dict[str, dict] = {}
    for username, email, full_name, role in MASTERS + STAFF:
        user = get_user_by_username(username)
        user_id = user["id"] if user else register_user(username, email, full_name, PASSWORD, role).id
        headers[username] = {"Authorization": f"Bearer {create_access_token(user_id)}"}
        progress(f"  Benutzer {username} ({email}, {role})")
    # who does what in the history
    headers["owner"] = headers[MASTERS[0][0]]
    headers["verwalter"] = headers["s.krause"]
    headers["techniker"] = headers["j.vogel"]
    return headers


def seed_testversion(app, today: Optional[date] = None, progress: Callable[[str], None] = print) -> bool:
    """Fill an empty database with the test data. Returns False when there was data already."""
    from fastapi.testclient import TestClient

    from .builder import Builder

    if not is_empty():
        return False
    started = time.monotonic()
    progress("Testversion: lege Benutzer und Testdaten an (dauert etwa eine Minute) …")
    headers = create_users(progress)
    client = TestClient(app, raise_server_exceptions=True)
    Builder(client, headers, today=today, progress=progress).run()
    progress(f"Testdaten angelegt in {time.monotonic() - started:.0f} s.")
    return True
