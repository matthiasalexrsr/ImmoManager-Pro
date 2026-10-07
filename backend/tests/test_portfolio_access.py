"""Portfolio access of accounts: stored, assigned only by owners, never silently widened."""

import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from backend import auth
from backend.app import app
from backend.db import session as db_session
from backend.dependencies import store
from backend.models import PortfolioCreate


@pytest.fixture(autouse=True)
def _clean():
    auth.clear_users()
    yield
    auth.clear_users()


@pytest.fixture
def client():
    return TestClient(app)


def _bearer(user) -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token(user.id)}"}


@pytest.fixture
def portfolios():
    return [store.create_portfolio(PortfolioCreate(name=name)) for name in ("Nord", "Süd")]


def _owner(client):
    return _bearer(auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer"))


def test_a_new_account_sees_nothing_until_the_owner_assigns_portfolios(client, portfolios):
    headers = _owner(client)
    created = client.post("/api/v1/auth/users", headers=headers, json={
        "username": "staff", "email": "s@example.com", "full_name": "Staff", "password": "Secret123",
        "role": "verwalter"}).json()
    assert (created["portfolio_access"], created["portfolio_ids"]) == ("selected", [])

    north = portfolios[0].id
    patched = client.patch(f"/api/v1/auth/users/{created['id']}", headers=headers,
                           json={"portfolio_access": "selected", "portfolio_ids": [north, north]}).json()
    assert patched["portfolio_ids"] == [north] and patched["portfolio_access_origin"] == "owner_assignment"
    assert auth.get_user_by_id(created["id"])["portfolio_ids"] == [north]

    everything = client.patch(f"/api/v1/auth/users/{created['id']}", headers=headers,
                              json={"portfolio_access": "all", "portfolio_ids": [north]}).json()
    assert (everything["portfolio_access"], everything["portfolio_ids"]) == ("all", [])


def test_portfolio_assignments_are_validated(client, portfolios):
    headers = _owner(client)
    staff = client.post("/api/v1/auth/users", headers=headers, json={
        "username": "staff", "email": "s@example.com", "full_name": "Staff", "password": "Secret123",
        "role": "verwalter", "portfolio_access": "selected", "portfolio_ids": [portfolios[1].id]}).json()
    assert staff["portfolio_ids"] == [portfolios[1].id]

    unknown = client.patch(f"/api/v1/auth/users/{staff['id']}", headers=headers,
                           json={"portfolio_access": "selected", "portfolio_ids": ["gibt-es-nicht"]})
    assert unknown.status_code == 422
    without_mode = client.patch(f"/api/v1/auth/users/{staff['id']}", headers=headers,
                                json={"portfolio_ids": [portfolios[0].id]})
    assert without_mode.status_code == 422
    assert auth.get_user_by_id(staff["id"])["portfolio_ids"] == [portfolios[1].id]


def test_only_owners_assign_portfolios_and_owners_always_see_everything(client, portfolios):
    headers = _owner(client)
    manager = _bearer(auth.register_user("manager", "m@example.com", "Manager", "Secret123", "verwalter"))
    reader = client.post("/api/v1/auth/users", headers=manager, json={
        "username": "reader", "email": "r@example.com", "full_name": "Reader", "password": "Secret123"}).json()

    for body in ({"portfolio_access": "all"},
                 {"portfolio_access": "selected", "portfolio_ids": [portfolios[0].id]}):
        assert client.patch(f"/api/v1/auth/users/{reader['id']}", headers=manager, json=body).status_code == 403
    refused = client.post("/api/v1/auth/users", headers=manager, json={
        "username": "other", "email": "x@example.com", "full_name": "X", "password": "Secret123",
        "portfolio_access": "all"})
    assert refused.status_code == 403

    promoted = client.patch(f"/api/v1/auth/users/{reader['id']}", headers=headers,
                            json={"role": "eigentuemer"}).json()
    assert promoted["portfolio_access"] == "all"
    owner_selected = client.patch(f"/api/v1/auth/users/{reader['id']}", headers=headers,
                                  json={"portfolio_access": "selected", "portfolio_ids": [portfolios[0].id]}).json()
    assert owner_selected["portfolio_access"] == "all"


def test_accounts_created_in_code_keep_seeing_everything():
    user = auth.register_user("setup", "setup@example.com", "Setup", "Secret123", "buchhaltung")
    assert user.portfolio_access == "all"


def test_first_start_after_the_update_keeps_existing_accounts_working(tmp_path, monkeypatch):
    """An installation started with create_all (SQLite, no Alembic) must not lock its staff out."""
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE users (id VARCHAR PRIMARY KEY, username TEXT NOT NULL UNIQUE, email TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL, hashed_password TEXT NOT NULL, role TEXT NOT NULL, is_active BOOLEAN NOT NULL,
                totp_secret TEXT, totp_enabled BOOLEAN NOT NULL, created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL);
            INSERT INTO users VALUES ('staff', 'staff', 's@example.com', 'Staff', 'x', 'verwalter', 1, NULL, 0,
                                      '2025-01-01', '2025-01-01');
        """)
    engine = create_engine(f"sqlite:///{path}")
    monkeypatch.setattr(db_session, "engine", engine)
    db_session.create_tables()
    db_session.create_tables()           # a second start changes nothing
    with engine.connect() as conn:
        assert "user_portfolio_access" in inspect(conn).get_table_names()
        assert conn.exec_driver_sql("SELECT mode, origin FROM user_portfolio_access").all() == [("all", "legacy_all")]
    engine.dispose()
