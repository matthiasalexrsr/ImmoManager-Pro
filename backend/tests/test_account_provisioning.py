"""Account provisioning: initial setup, closed sign-up, admin-created users."""

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.config import settings


@pytest.fixture(autouse=True)
def _clean():
    clear_users()
    yield
    clear_users()


@pytest.fixture
def client():
    return TestClient(app)


def _headers(role: str) -> dict:
    user = register_user(f"{role}_user", f"{role}@example.com", role, "Secret123", role)
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _new_user(role: str = "readonly") -> dict:
    return {"username": f"new_{role}", "email": f"new_{role}@example.com",
            "full_name": "New", "password": "Secret123", "role": role}


def test_registration_status_reflects_setup_and_setting(client, monkeypatch):
    assert client.get("/api/v1/auth/registration-status").json() == {"initial_setup": True, "open": True}
    register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    assert client.get("/api/v1/auth/registration-status").json() == {"initial_setup": False, "open": False}
    monkeypatch.setattr(settings, "allow_self_registration", True)
    assert client.get("/api/v1/auth/registration-status").json()["open"] is True


def test_self_registered_user_cannot_write(client, monkeypatch):
    """Regression: sign-up used to allow 'techniker', which may write everything."""
    monkeypatch.setattr(settings, "allow_self_registration", True)
    register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    client.post("/api/v1/auth/register", json=_new_user("techniker"))
    token = client.post("/api/v1/auth/login",
                        json={"username": "new_techniker", "password": "Secret123"}).json()["access_token"]
    resp = client.post("/api/v1/portfolios", headers={"Authorization": f"Bearer {token}"}, json={"name": "X"})
    assert resp.status_code == 403


def test_owner_creates_user_with_role(client):
    resp = client.post("/api/v1/auth/users", headers=_headers("eigentuemer"), json=_new_user("buchhaltung"))
    assert resp.status_code == 201
    assert resp.json()["role"] == "buchhaltung"


def test_manager_may_only_create_readonly_users(client):
    headers = _headers("verwalter")
    assert client.post("/api/v1/auth/users", headers=headers, json=_new_user("techniker")).status_code == 403
    assert client.post("/api/v1/auth/users", headers=headers, json=_new_user("readonly")).status_code == 201


@pytest.mark.parametrize("role", ["readonly", "techniker", "buchhaltung"])
def test_non_admins_cannot_create_users(client, role):
    resp = client.post("/api/v1/auth/users", headers=_headers(role), json=_new_user())
    assert resp.status_code == 403


def test_create_user_rejects_unknown_role(client):
    resp = client.post("/api/v1/auth/users", headers=_headers("eigentuemer"), json=_new_user("superuser"))
    assert resp.status_code == 422
