"""Failure injection uses only independent temporary authentication databases."""

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy import Table, create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.db.orm_models import RevokedTokenORM
from backend.models import RefreshRequest
from backend.routers import auth as routes
from backend.services.upload_access import require_upload_access


@pytest.fixture
def auth_db(tmp_path, monkeypatch):
    path = tmp_path / "isolated-auth.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    table = RevokedTokenORM.__table__
    assert isinstance(table, Table)
    table.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    monkeypatch.setattr(auth, "_token_blacklist", set())
    monkeypatch.setattr(auth, "_blacklist_expiry", {})
    yield path, factory
    engine.dispose()


def failing_factory(monkeypatch, operation):
    session = MagicMock()
    failure = SQLAlchemyError("PRIVATE-SQL-PARAMETERS-MUST-NOT-LEAK")
    if operation == "open":
        factory = MagicMock(side_effect=failure)
    else:
        factory = MagicMock(return_value=session)
        session.query.return_value.filter.return_value.first.return_value = None
        if operation == "read":
            session.query.side_effect = failure
        elif operation == "commit":
            session.commit.side_effect = failure
        else:
            session.query.side_effect = failure
            session.rollback.side_effect = failure
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    return session


@pytest.mark.parametrize("operation", ["open", "read", "commit", "rollback"])
def test_logout_requires_confirmed_persistence(auth_db, monkeypatch, caplog, operation):
    token = auth.create_access_token("synthetic-user")
    failing_factory(monkeypatch, operation)
    response = Response()
    request = Request({"type": "http", "scheme": "https", "path": "/auth/logout", "headers": []})
    with pytest.raises(HTTPException) as failure:
        routes.logout({"access_token": token}, request, response)
    assert failure.value.status_code == 503
    assert failure.value.headers is not None
    assert failure.value.headers["Retry-After"]
    assert "set-cookie" not in response.headers
    assert token not in auth._token_blacklist
    assert "PRIVATE-SQL-PARAMETERS" not in caplog.text
    assert token not in caplog.text


@pytest.mark.parametrize("operation", ["open", "read"])
def test_unknown_token_is_not_authorized_during_database_failure(auth_db, monkeypatch, caplog, operation):
    token = auth.create_access_token("synthetic-user")
    failing_factory(monkeypatch, operation)
    with pytest.raises(HTTPException) as failure:
        auth.decode_token(token)
    assert failure.value.status_code == 503
    assert "PRIVATE-SQL-PARAMETERS" not in caplog.text
    assert token not in caplog.text


def test_upload_cookie_uses_same_failure_decision(auth_db, monkeypatch):
    token = auth.create_access_token("synthetic-user")
    failing_factory(monkeypatch, "read")
    request = Request({"type": "http", "scheme": "https", "path": "/uploads/original.pdf",
                       "headers": [(b"cookie", f"immo_upload_access={token}".encode())]})
    with pytest.raises(HTTPException) as failure:
        require_upload_access(request)
    assert failure.value.status_code == 503


def test_failed_refresh_neither_rotates_nor_sets_cookie(auth_db, monkeypatch):
    token = auth.create_refresh_token("synthetic-user")
    failing_factory(monkeypatch, "commit")
    monkeypatch.setattr(routes, "get_user_by_id", lambda _: {"id": "synthetic-user", "is_active": True})
    issue = MagicMock()
    monkeypatch.setattr(routes, "create_access_token", issue)
    response = Response()
    request = Request({"type": "http", "scheme": "https", "path": "/auth/refresh", "headers": []})
    with pytest.raises(HTTPException) as failure:
        routes.refresh(RefreshRequest(refresh_token=token), request, response)
    assert failure.value.status_code == 503
    issue.assert_not_called()
    assert "set-cookie" not in response.headers
    assert token not in auth._token_blacklist


def test_database_recovery_does_not_invent_a_revocation(auth_db, monkeypatch):
    _, factory = auth_db
    token = auth.create_access_token("synthetic-user")
    failing_factory(monkeypatch, "commit")
    with pytest.raises(HTTPException):
        auth.revoke_token(token)
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    assert auth.decode_token(token).sub == "synthetic-user"
    auth.revoke_token(token)
    auth.revoke_token(token)
    with factory() as session:
        assert session.query(RevokedTokenORM).count() == 1
    auth._token_blacklist.clear()
    assert auth.is_token_revoked(token)


def test_known_revocation_stays_denied_during_database_failure(auth_db, monkeypatch):
    token = auth.create_access_token("synthetic-user")
    auth.revoke_token(token)
    failing_factory(monkeypatch, "read")
    with pytest.raises(HTTPException) as failure:
        auth.decode_token(token)
    assert failure.value.status_code == 401


def test_db_read_cache_has_expiry_and_can_be_cleaned(auth_db):
    token = auth.create_access_token("synthetic-user")
    auth.revoke_token(token)
    auth._token_blacklist.clear()
    auth._blacklist_expiry.clear()
    assert auth.is_token_revoked(token)
    assert token in auth._blacklist_expiry
    assert auth._blacklist_expiry[token].tzinfo is not None
    auth._blacklist_expiry[token] = datetime.now(timezone.utc) - timedelta(seconds=1)
    auth._cleanup_blacklist()
    assert token not in auth._token_blacklist


def test_independent_auth_processes_and_restart_observe_revocation(auth_db):
    path, _ = auth_db
    token = auth.create_access_token("synthetic-user")
    program = """
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend import auth
engine = create_engine('sqlite:///' + sys.argv[1])
auth._auth_session_factory = sessionmaker(bind=engine)
token = sys.stdin.read().strip()
if sys.argv[2] == 'revoke':
    auth.revoke_token(token)
print('revoked' if auth.is_token_revoked(token) else 'valid')
engine.dispose()
"""
    for operation, expected in [("read", "valid"), ("revoke", "revoked"), ("read", "revoked"), ("read", "revoked")]:
        result = subprocess.run([sys.executable, "-c", program, path.as_posix(), operation],
                                input=token, text=True, capture_output=True, timeout=30)
        assert result.returncode == 0, "Isolated authentication child failed"
        assert result.stdout.strip() == expected
        assert token not in result.stderr


def test_scope_lookup_failure_never_enters_an_unscoped_endpoint(auth_db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.services.portfolio_http import PortfolioScopeMiddleware

    app = FastAPI()
    app.add_middleware(PortfolioScopeMiddleware)
    entered = []

    @app.get("/probe")
    def probe():
        entered.append(True)
        return {"private": "must not be returned"}

    token = auth.create_access_token("synthetic-user")
    failing_factory(monkeypatch, "read")
    with TestClient(app) as client:
        result = client.get("/probe", headers={"Authorization": f"Bearer {token}"})
    assert result.status_code == 503
    assert result.headers["Retry-After"] == "30"
    assert not entered
    assert "private" not in result.text
    assert "PRIVATE-SQL-PARAMETERS" not in result.text


def test_two_independent_refresh_claims_have_only_one_winner(auth_db):
    from concurrent.futures import ThreadPoolExecutor

    path, factory = auth_db
    token = auth.create_refresh_token("synthetic-user")
    program = """
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from backend import auth
engine = create_engine('sqlite:///' + sys.argv[1])
auth._auth_session_factory = sessionmaker(bind=engine)
try:
    auth.revoke_token(sys.stdin.read().strip(), require_unrevoked=True)
    print('claimed')
except HTTPException as error:
    print(str(error.status_code))
engine.dispose()
"""

    def claim():
        result = subprocess.run([sys.executable, "-c", program, path.as_posix()],
                                input=token, text=True, capture_output=True, timeout=30)
        assert result.returncode == 0, "Isolated refresh child failed"
        return result.stdout.strip()

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(lambda _: claim(), range(2)))
    assert sorted(outcomes) == ["401", "claimed"]
    with factory() as session:
        assert session.query(RevokedTokenORM).count() == 1
