"""User administration guards: who may change, reset, deactivate or delete whom."""

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user


@pytest.fixture(autouse=True)
def _clean():
    clear_users()
    yield
    clear_users()


@pytest.fixture
def client():
    return TestClient(app)


def _user(name: str, role: str):
    return register_user(name, f"{name}@example.com", name.title(), "Secret123", role)


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _login(client, username: str, password: str):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_manager_cannot_touch_owner_account(client):
    """Regression: a manager could deactivate the owner and lock them out."""
    owner, manager = _user("owner", "eigentuemer"), _user("manager", "verwalter")
    resp = client.patch(f"/api/v1/auth/users/{owner.id}", headers=_auth(manager), json={"is_active": False})
    assert resp.status_code == 403
    resp = client.post(f"/api/v1/auth/users/{owner.id}/password", headers=_auth(manager),
                       json={"password": "Hijack123"})
    assert resp.status_code == 403
    assert _login(client, "owner", "Secret123").status_code == 200


def test_manager_can_administer_readonly_account(client):
    manager, reader = _user("manager", "verwalter"), _user("reader", "readonly")
    resp = client.patch(f"/api/v1/auth/users/{reader.id}", headers=_auth(manager),
                        json={"full_name": "Renamed", "is_active": False})
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Renamed"
    assert resp.json()["is_active"] is False


def test_owner_cannot_demote_or_deactivate_self(client):
    owner = _user("owner", "eigentuemer")
    assert client.patch(f"/api/v1/auth/users/{owner.id}", headers=_auth(owner),
                        json={"role": "readonly"}).status_code == 400
    assert client.patch(f"/api/v1/auth/users/{owner.id}", headers=_auth(owner),
                        json={"is_active": False}).status_code == 400
    assert client.patch(f"/api/v1/auth/users/{owner.id}", headers=_auth(owner),
                        json={"full_name": "Still Me"}).status_code == 200


def test_owner_may_demote_another_owner(client):
    owner, second = _user("owner", "eigentuemer"), _user("second", "eigentuemer")
    resp = client.patch(f"/api/v1/auth/users/{second.id}", headers=_auth(owner), json={"role": "verwalter"})
    assert resp.status_code == 200


def test_last_active_owner_is_protected_from_other_owner_paths(client):
    owner = _user("owner", "eigentuemer")
    ghost = _user("ghost", "eigentuemer")
    client.patch(f"/api/v1/auth/users/{ghost.id}", headers=_auth(owner), json={"is_active": False})
    # Defence in depth: the API's self-protection already prevents reaching this state.
    from backend.routers.auth import _is_last_active_owner, _load_target

    assert _is_last_active_owner(_load_target(owner.id)) is True
    assert _is_last_active_owner(_load_target(ghost.id)) is False


def test_password_reset_changes_login(client):
    owner, staff = _user("owner", "eigentuemer"), _user("staff", "buchhaltung")
    resp = client.post(f"/api/v1/auth/users/{staff.id}/password", headers=_auth(owner),
                       json={"password": "NewSecret456"})
    assert resp.status_code == 200
    assert _login(client, "staff", "Secret123").status_code == 401
    assert _login(client, "staff", "NewSecret456").status_code == 200


def test_password_reset_enforces_policy(client):
    owner, staff = _user("owner", "eigentuemer"), _user("staff", "buchhaltung")
    resp = client.post(f"/api/v1/auth/users/{staff.id}/password", headers=_auth(owner),
                       json={"password": "weakpass"})
    assert resp.status_code == 400


def test_patch_rejects_invalid_role(client):
    """Regression: PATCH accepted arbitrary role strings."""
    owner, staff = _user("owner", "eigentuemer"), _user("staff", "readonly")
    resp = client.patch(f"/api/v1/auth/users/{staff.id}", headers=_auth(owner), json={"role": "superuser"})
    assert resp.status_code == 422


def test_unknown_user_returns_404(client):
    owner = _user("owner", "eigentuemer")
    assert client.patch("/api/v1/auth/users/nope", headers=_auth(owner), json={"full_name": "x"}).status_code == 404
    assert client.delete("/api/v1/auth/users/nope", headers=_auth(owner)).status_code == 404


def test_sql_store_sets_password_hash_but_update_ignores_it():
    from datetime import datetime, timezone

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.auth import SQLUserStore, hash_password, verify_password
    from backend.db.orm_models import Base, UserORM

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[UserORM.__tablename__]])
    store = SQLUserStore(sessionmaker(bind=engine))
    now = datetime.now(timezone.utc)
    store.create({
        "id": "u1", "username": "staff", "email": "s@example.com", "full_name": "Staff",
        "hashed_password": hash_password("Secret123"), "role": "readonly", "is_active": True,
        "totp_secret": None, "totp_enabled": False, "created_at": now, "updated_at": now,
    })

    store.update("u1", {"hashed_password": "ignored"})
    stored = store.get_by_id("u1")
    assert stored is not None and verify_password("Secret123", stored["hashed_password"])

    assert store.set_password_hash("u1", hash_password("NewSecret456")) is not None
    stored = store.get_by_id("u1")
    assert stored is not None and verify_password("NewSecret456", stored["hashed_password"])
    assert store.set_password_hash("missing", "x") is None
