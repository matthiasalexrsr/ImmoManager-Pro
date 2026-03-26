"""HTTP integration tests using TestClient to verify auth enforcement and API behavior."""

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store


@pytest.fixture(autouse=True)
def _clean():
    """Clear store and users before each test."""
    store.clear_all()
    clear_users()
    yield
    clear_users()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Create a registered user and return auth headers."""
    user = register_user("testuser", "test@example.com", "Test User", "Secret123", "eigentuemer")
    token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


# === Auth Enforcement ===

class TestAuthEnforcement:
    """Verify that CRUD endpoints reject unauthenticated requests."""

    def test_portfolios_requires_auth(self, client):
        resp = client.get("/api/v1/portfolios")
        assert resp.status_code == 401

    def test_properties_requires_auth(self, client):
        resp = client.get("/api/v1/properties")
        assert resp.status_code == 401

    def test_units_requires_auth(self, client):
        resp = client.get("/api/v1/units")
        assert resp.status_code == 401

    def test_tenants_requires_auth(self, client):
        resp = client.get("/api/v1/tenants")
        assert resp.status_code == 401

    def test_contracts_requires_auth(self, client):
        resp = client.get("/api/v1/contracts")
        assert resp.status_code == 401

    def test_accounts_requires_auth(self, client):
        resp = client.get("/api/v1/accounts")
        assert resp.status_code == 401

    def test_bookings_requires_auth(self, client):
        resp = client.get("/api/v1/bookings")
        assert resp.status_code == 401

    def test_tasks_requires_auth(self, client):
        resp = client.get("/api/v1/tasks")
        assert resp.status_code == 401

    def test_reports_requires_auth(self, client):
        resp = client.get("/api/v1/reports/summary")
        assert resp.status_code == 401

    def test_create_portfolio_requires_auth(self, client):
        resp = client.post("/api/v1/portfolios", json={"name": "Test", "currency": "EUR"})
        assert resp.status_code == 401

    def test_audit_requires_auth(self, client):
        resp = client.get("/api/v1/audit")
        assert resp.status_code == 401

    def test_notifications_requires_auth(self, client):
        resp = client.get("/api/v1/notifications")
        assert resp.status_code == 401


# === Auth Endpoints (public) ===

class TestAuthEndpoints:
    """Verify auth endpoints work without prior authentication."""

    def test_register(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "username": "newuser",
            "email": "new@example.com",
            "full_name": "New User",
            "password": "Pass1234",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newuser"
        assert data["role"] == "readonly"

    def test_register_role_restriction(self, client):
        """Self-registration should restrict role to readonly/techniker."""
        resp = client.post("/api/v1/auth/register", json={
            "username": "attacker",
            "email": "attacker@example.com",
            "full_name": "Attacker",
            "password": "Pass1234",
            "role": "eigentuemer",
        })
        assert resp.status_code == 201
        data = resp.json()
        # Should be downgraded to readonly
        assert data["role"] == "readonly"

    def test_login(self, client):
        register_user("loginuser", "login@example.com", "Login User", "Pass1234")
        resp = client.post("/api/v1/auth/login", json={
            "username": "loginuser",
            "password": "Pass1234",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data

    def test_login_invalid(self, client):
        resp = client.post("/api/v1/auth/login", json={
            "username": "nobody",
            "password": "wrong",
        })
        assert resp.status_code == 401


# === Authenticated CRUD ===

class TestAuthenticatedCRUD:
    """Verify CRUD operations work when authenticated."""

    def test_list_portfolios(self, client, auth_headers):
        resp = client.get("/api/v1/portfolios", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_portfolio(self, client, auth_headers):
        resp = client.post("/api/v1/portfolios", headers=auth_headers, json={
            "name": "Test Portfolio",
            "currency": "EUR",
            "timezone": "Europe/Berlin",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Portfolio"
        assert data["id"]

    def test_get_portfolio(self, client, auth_headers):
        create_resp = client.post("/api/v1/portfolios", headers=auth_headers, json={
            "name": "Test Portfolio",
        })
        portfolio_id = create_resp.json()["id"]
        resp = client.get(f"/api/v1/portfolios/{portfolio_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == portfolio_id

    def test_update_portfolio(self, client, auth_headers):
        create_resp = client.post("/api/v1/portfolios", headers=auth_headers, json={
            "name": "Original",
        })
        portfolio_id = create_resp.json()["id"]
        resp = client.put(f"/api/v1/portfolios/{portfolio_id}", headers=auth_headers, json={
            "name": "Updated",
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    def test_patch_portfolio(self, client, auth_headers):
        create_resp = client.post("/api/v1/portfolios", headers=auth_headers, json={
            "name": "Original",
        })
        portfolio_id = create_resp.json()["id"]
        resp = client.patch(f"/api/v1/portfolios/{portfolio_id}", headers=auth_headers, json={
            "description": "New desc",
        })
        assert resp.status_code == 200
        assert resp.json()["description"] == "New desc"

    def test_delete_portfolio(self, client, auth_headers):
        create_resp = client.post("/api/v1/portfolios", headers=auth_headers, json={
            "name": "To Delete",
        })
        portfolio_id = create_resp.json()["id"]
        resp = client.delete(f"/api/v1/portfolios/{portfolio_id}", headers=auth_headers)
        assert resp.status_code == 204

    def test_portfolio_not_found(self, client, auth_headers):
        resp = client.get("/api/v1/portfolios/nonexistent", headers=auth_headers)
        assert resp.status_code == 404


# === Health Endpoint (public) ===

class TestHealth:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


# === Route Collision Fix ===

class TestRouteCollisionFix:
    """Verify /generate-recurring is not treated as a task_id."""

    def test_generate_recurring_route(self, client, auth_headers):
        resp = client.post("/api/v1/tasks/generate-recurring", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# === CORS ===

class TestCORS:
    def test_cors_headers(self, client):
        resp = client.options("/api/v1/portfolios", headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        })
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
