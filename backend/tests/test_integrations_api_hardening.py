import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.routers import integrations
from backend.services.integrations.config_store import InMemoryIntegrationConfigStore
from backend.services.integrations.manager import IntegrationManager


@pytest.fixture
def manager(monkeypatch):
    manager = IntegrationManager()
    manager.seed_defaults()
    monkeypatch.setattr(integrations, "integration_manager", manager)
    return manager


def headers(role="eigentuemer"):
    clear_users()
    user = register_user("integration-hardening", "integration@example.test", "Test", "Secret123", role)
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_storage_failure_is_readable_503_and_live_config_unchanged(manager):
    class BrokenStore(InMemoryIntegrationConfigStore):
        def save(self, state): raise OSError("secret-password")
    manager._store = BrokenStore()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.put("/api/v1/integrations/email/config", headers=headers(), json={"config": {"smtp_host": "smtp.example.test"}})
    assert response.status_code == 503
    assert "secret-password" not in response.text
    assert manager.get_integration("email")["config"] == {}


def test_toggle_rejects_coerced_bool(manager):
    response = TestClient(app).patch("/api/v1/integrations/email", headers=headers(), json={"enabled": "false"})
    assert response.status_code == 422
    assert manager.get_integration("email")["enabled"] is True


def test_bad_action_type_returns_failed_result_and_history(manager):
    client = TestClient(app)
    auth = headers()
    response = client.post("/api/v1/integrations/email/run", headers=auth, json={"payload": {"action": 42}})
    assert response.status_code == 200
    assert response.json()["success"] is False
    history = client.get("/api/v1/integrations/email/history", headers=auth).json()["items"]
    assert len(history) == 1 and not history[0]["success"]


@pytest.mark.parametrize("method,path,body", [("put", "/email/config", {"config": {"smtp_host": "smtp.example.test"}}),
    ("patch", "/email", {"enabled": False}), ("post", "/email/run", {"payload": {"action": "send", "recipient": "chosen@example.test"}})])
def test_readers_cannot_configure_toggle_or_send(manager, method, path, body):
    client = TestClient(app)
    auth = headers("readonly")
    assert client.get("/api/v1/integrations", headers=auth).status_code == 200
    assert getattr(client, method)("/api/v1/integrations" + path, headers=auth, json=body).status_code == 403
    assert manager.list_history("email") == []


def test_unavailable_history_is_a_readable_503(manager, monkeypatch):
    monkeypatch.setattr(manager._journal, "list", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("unavailable")))
    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/integrations/email/history", headers=headers())
    assert response.status_code == 503
    assert "Integrationsjournal" in response.text
