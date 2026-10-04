"""Every request gives its database connection back (SQL store only)."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend import dependencies
from backend.app import app
from backend.auth import clear_users, create_access_token, register_user

pytestmark = pytest.mark.skipif(dependencies._scoped_session is None, reason="needs the SQL store")


def test_parallel_requests_return_their_connections():
    """Regression: the session lived per worker thread but was removed in the event loop thread.

    Every worker thread that had served a request kept a connection; once 15 were taken
    (5 + 10 overflow) every further request waited 30 s and failed: the server hung.
    """
    from backend.db.session import engine

    clear_users()
    owner = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    client = TestClient(app, headers={"Authorization": f"Bearer {create_access_token(owner.id)}"})

    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda path: client.get(path).status_code,
                              ["/api/v1/units", "/api/v1/contracts", "/api/v1/dashboard/stats", "/api/v1/tenants"] * 10))

    assert codes == [200] * 40
    assert engine.pool.checkedout() == 0
    clear_users()


def test_more_parallel_requests_than_connections_do_not_lock_up():
    """Regression: auth and audit read the database on the event loop.

    With all 15 connections in use, a token check on the loop waited for a free
    connection while only the loop could hand one back: every request then hung.
    """
    import asyncio
    import time

    from backend.auth import get_current_user, require_auth, require_role
    from backend.db.session import engine

    # Dependencies that touch the database must run in the threadpool.
    for dependency in (get_current_user, require_auth, require_role("eigentuemer")):
        assert not asyncio.iscoroutinefunction(dependency)

    clear_users()
    owner = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    client = TestClient(app, headers={"Authorization": f"Bearer {create_access_token(owner.id)}"})
    pool_size = engine.pool.size() + engine.pool._max_overflow  # type: ignore[attr-defined]

    started = time.monotonic()
    with ThreadPoolExecutor(pool_size + 5) as pool:
        codes = list(pool.map(lambda path: client.get(path).status_code,
                              ["/api/v1/units", "/api/v1/tenants"] * (pool_size + 5)))

    assert set(codes) == {200}
    assert time.monotonic() - started < 25  # a lock-up only ends with the 30 s pool timeout
    assert engine.pool.checkedout() == 0
    clear_users()
