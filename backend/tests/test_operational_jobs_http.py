"""Real JWT/RBAC on the additive router in an isolated test application."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend import auth
from backend.dependencies import get_store
from backend.routers.operational_jobs import router
from backend.services import operational_jobs as service
from backend.services.auth_sessions import login_pair
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.storage import InMemoryStore
from backend.tests.test_payments import seed


@pytest.fixture
def installation(monkeypatch):
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    store = InMemoryStore()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.add_middleware(PortfolioScopeMiddleware)
    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app) as client:
        yield client, store


def actor(role, selected=False):
    user = auth.register_user(role, role + "@example.invalid", "Synthetic", "Synthetic Packet Passphrase 2026", role)
    if selected:
        auth._user_store._by_id[user.id]["portfolio_access"] = "selected"
        auth._user_store._by_id[user.id]["portfolio_ids"] = []
    return user, {"Authorization": "Bearer " + auth.create_access_token(user.id)}


@pytest.mark.parametrize("role,selected,allowed", [("eigentuemer", False, True), ("verwalter", False, True),
    ("verwalter", True, False), ("readonly", False, False), ("techniker", False, False), ("buchhaltung", False, False)])
def test_global_job_operator_boundary_and_real_continuation(installation, role, selected, allowed):
    client, store = installation
    _, headers = actor(role, selected)
    body = {"idempotency_key": "real-http", "as_of": "2026-11-05"}
    result = client.post("/api/v1/tasks/operational-jobs", headers=headers, json=body)
    assert result.status_code == (201 if allowed else 403)
    if not allowed:
        assert not store.__dict__.get("operational_jobs")
        return
    job = result.json()
    assert client.post("/api/v1/tasks/operational-jobs", headers=headers, json=body).json() == job
    for _ in range(3):
        response = client.post(f"/api/v1/tasks/operational-jobs/{job['id']}/continue", headers=headers, json={"max_items": 1})
        assert response.status_code == 200
    assert response.json()["state"] == "completed"
    assert client.get(f"/api/v1/tasks/operational-jobs/{job['id']}/items", headers=headers, params={"page_size": 1}).json()["items"] == []


def test_anonymous_and_current_deactivation_fail_without_creating_work(installation):
    client, store = installation
    assert client.post("/api/v1/tasks/operational-jobs", json={}).status_code == 401
    user, headers = actor("verwalter")
    auth._user_store._by_id[user.id]["is_active"] = False
    assert client.post("/api/v1/tasks/operational-jobs", headers=headers, json={"idempotency_key": "disabled", "as_of": "2026-11-05"}).status_code == 403
    assert not store.__dict__.get("operational_jobs")


def test_database_outage_returns_safe_retryable_response_without_driver_details(installation, monkeypatch):
    client, store = installation
    _, headers = actor("eigentuemer")
    def unavailable(*args, **kwargs):
        raise OperationalError("Internal private SQL", {}, RuntimeError("Private connection data"))
    monkeypatch.setattr(service, "create_job", unavailable)
    response = client.post("/api/v1/tasks/operational-jobs", headers=headers, json={"idempotency_key": "outage", "as_of": "2026-11-05"})
    assert response.status_code == 503 and response.headers["Retry-After"] == "2"
    assert response.json()["code"] == "database_unavailable"
    assert "Private" not in response.text and "Internal private SQL" not in response.text
    assert not store.__dict__.get("operational_jobs")


@pytest.mark.parametrize("persistent_family", [False, True])
def test_real_midpacket_token_revocation_rolls_back_and_fresh_login_can_resume(installation, monkeypatch, persistent_family):
    client, store = installation
    user, headers = actor("eigentuemer")
    if persistent_family:
        headers = {"Authorization": "Bearer " + login_pair(user.id).access_token}
    token = headers["Authorization"][7:]
    seed(store, "rent_charge")
    job = client.post("/api/v1/tasks/operational-jobs", headers=headers, json={"idempotency_key": "late-session",
        "as_of": "2026-11-05", "families": ["overdue_rent_charge"]}).json()
    original = service.Unit.create
    def revoke_after_publication(unit, kind, values):
        value = original(unit, kind, values)
        auth.revoke_token(token)
        return value
    with monkeypatch.context() as patch:
        patch.setattr(service.Unit, "create", revoke_after_publication)
        response = client.post(f"/api/v1/tasks/operational-jobs/{job['id']}/continue", headers=headers, json={"max_items": 7})
    assert response.status_code == 401 and store.list_notifications() == []
    assert client.get(f"/api/v1/tasks/operational-jobs/{job['id']}", headers=headers).status_code == 401
    fresh = {"Authorization": "Bearer " + login_pair(user.id).access_token}
    current = client.get(f"/api/v1/tasks/operational-jobs/{job['id']}", headers=fresh).json()
    assert current["state"] == "attention" and current["lanes"][0]["last_error"] == "actor_changed"
    assert token not in str(store.__dict__.get("operational_jobs")) + str(current)
    resumed = client.post(f"/api/v1/tasks/operational-jobs/{job['id']}/lanes/{current['lanes'][0]['id']}/retry", headers=fresh,
        json={"idempotency_key": "fresh-session", "expected_revision": current["revision"]})
    assert resumed.status_code == 200
    done = client.post(f"/api/v1/tasks/operational-jobs/{job['id']}/continue", headers=fresh, json={"max_items": 7})
    assert done.status_code == 200 and done.json()["state"] == "completed"
    assert len(store.list_notifications()) == 1
