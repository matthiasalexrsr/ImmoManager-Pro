"""Dedicated disposable PostgreSQL UUID schemas, actual independent auth sessions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from backend import auth
from backend.db.session_models import AuthRefreshORM, AuthSessionORM
from backend.services import auth_sessions as service
from backend.tests.test_private_server_concurrency import postgres_database  # noqa: F401 pytest fixture


@pytest.fixture
def security(postgres_database, monkeypatch):  # noqa: F811
    engine, factory, *_ = postgres_database
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    monkeypatch.setattr(auth, "_token_blacklist", set())
    monkeypatch.setattr(auth, "_blacklist_expiry", {})
    owner = auth.register_user("owner", "owner@example.test", "Synthetic owner", "Strong123", "eigentuemer")
    viewer = auth.register_user("viewer", "viewer@example.test", "Synthetic viewer", "Strong123", "readonly")
    return engine, factory, owner, viewer


@pytest.mark.parametrize("legacy", [False, True])
def test_pg_parallel_rotations_revoke_winning_family_after_consumed_replay(security, legacy):
    engine, factory, _, viewer = security
    independent = service.login_pair(viewer.id)
    initial = service.login_pair(viewer.id)
    refresh = auth.create_refresh_token(viewer.id) if legacy else initial.refresh_token
    barrier = Barrier(2)
    def rotate(_):
        barrier.wait(timeout=15)
        try:
            return service.rotate(refresh)
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(rotate, range(2)))
    winners = [value for value in results if not isinstance(value, int)]
    assert len(winners) == 1 and results.count(401) == 1
    with pytest.raises(HTTPException) as replay:
        auth.decode_token(winners[0].access_token)
    assert replay.value.status_code == 401
    assert auth.decode_token(independent.access_token).sub == viewer.id
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AuthSessionORM).where(AuthSessionORM.revoke_reason == "refresh_reuse")) == 1
        assert db.scalar(select(func.count()).select_from(AuthRefreshORM).where(AuthRefreshORM.consumed_at.is_not(None))) == 1
    assert engine.pool.checkedout() == 0


def test_pg_refresh_after_authoritative_account_disable_and_other_user_isolation(security):
    engine, _, owner, viewer = security
    tokens = service.login_pair(viewer.id)
    owner_tokens = service.login_pair(owner.id)
    sid = auth.decode_token(tokens.access_token).sid
    with pytest.raises(HTTPException) as other:
        service.revoke_own(owner.id, sid, None)
    assert other.value.status_code == 404
    auth.update_user(viewer.id, {"is_active": False}, actor_id=owner.id)
    with pytest.raises(HTTPException) as disabled:
        service.rotate(tokens.refresh_token)
    assert disabled.value.status_code == 401
    assert auth.decode_token(owner_tokens.access_token).sub == owner.id
    assert engine.pool.checkedout() == 0
