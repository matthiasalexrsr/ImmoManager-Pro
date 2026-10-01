"""Business-domain permission checks perform actual API mutations or leave no trace."""
import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.models import PortfolioCreate
from backend.routers import accounts, portfolios, tasks
from backend.storage import InMemoryStore


@pytest.fixture
def role_installation(monkeypatch):
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    business = InMemoryStore()
    for module in (accounts, portfolios, tasks):
        monkeypatch.setattr(module, "store", business)
    portfolio = business.create_portfolio(PortfolioCreate(name="Synthetic permission portfolio"))
    with TestClient(app) as client:
        yield client, business, portfolio


@pytest.mark.parametrize("role,finance,operations,inventory", [
    ("eigentuemer", True, True, True), ("verwalter", True, True, True),
    ("buchhaltung", True, False, False), ("techniker", False, True, False),
    ("readonly", False, False, False),
])
def test_actual_business_writes_follow_account_domain_permissions(role_installation, role, finance, operations, inventory):
    client, store, portfolio = role_installation
    user = auth.register_user(role, role + "@example.invalid", "Synthetic account", "Strong123", role)
    headers = {"Authorization": "Bearer " + auth.create_access_token(user.id)}
    account = client.post("/api/v1/accounts", headers=headers,
                          json={"portfolio_id": portfolio.id, "name": "Synthetic bank", "account_type": "bank"})
    assert account.status_code == (201 if finance else 403)
    assert len(store.list_accounts()) == int(finance)
    task = client.post("/api/v1/tasks", headers=headers, json={"title": "Synthetic work order"})
    assert task.status_code == (201 if operations else 403)
    assert len(store.list_tasks()) == int(operations)
    created = client.post("/api/v1/portfolios", headers=headers, json={"name": "Second portfolio"})
    assert created.status_code == (201 if inventory else 403)
    assert len(store.list_portfolios()) == 1 + int(inventory)
    # Read access and personal security remain available independently.
    assert client.get("/api/v1/accounts", headers=headers).status_code == 200
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert ("finance" in me["write_permissions"]) is finance
    assert ("operations" in me["write_permissions"]) is operations
    assert client.post("/api/v1/auth/2fa/setup", headers=headers, json={}).status_code == 200
    assert client.put("/api/v1/integrations/email/config", headers=headers,
                      json={"config": {}}).status_code == (200 if inventory else 403)


def test_old_token_cannot_keep_write_rights_after_role_change(role_installation):
    client, store, portfolio = role_installation
    user = auth.register_user("worker", "worker@example.invalid", "Worker", "Strong123", "buchhaltung")
    headers = {"Authorization": "Bearer " + auth.create_access_token(user.id)}
    auth.update_user(user.id, {"role": "techniker"})
    result = client.post("/api/v1/accounts", headers=headers,
                         json={"portfolio_id": portfolio.id, "name": "Forbidden bank", "account_type": "bank"})
    assert result.status_code == 403
    assert not store.list_accounts()
    assert client.post("/api/v1/tasks", headers=headers, json={"title": "Allowed repair"}).status_code == 201
