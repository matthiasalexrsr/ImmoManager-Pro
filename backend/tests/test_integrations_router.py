import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.services.integrations.history_policy import request_observation, response_observation
from backend.services.integrations.history_store import SQLIntegrationHistoryStore
from backend.services.integrations.manager import integration_manager
from backend.services.integrations.providers import WhatsAppIntegrationProvider
from backend.tests.test_integration_history_core import journal_engine


@pytest.fixture(autouse=True)
def actual_history(monkeypatch, tmp_path):
    if isinstance(auth._user_store, auth.SQLUserStore):
        factory = auth._user_store._session_factory
        from backend.db.integration_history_schema import install_history_guards

        with factory() as session, session.get_bind().begin() as connection:
            install_history_guards(connection)
        monkeypatch.setattr(integration_manager, "_history_store", SQLIntegrationHistoryStore(factory))
        yield
        return
    with journal_engine(tmp_path, "sqlite") as engine:
        monkeypatch.setattr(integration_manager, "_history_store", SQLIntegrationHistoryStore(sessionmaker(engine)))
        yield


def _auth_headers(role="eigentuemer"):
    clear_users()
    user = register_user("intg", "intg@example.com", "Int G", "Secret123", role)
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_list_integration_status_authenticated():
    client = TestClient(app)
    resp = client.get("/api/v1/integrations", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "integrations" in data
    assert any(i["id"] == "email" for i in data["integrations"])
    assert any(i["id"] == "listing-portals" for i in data["integrations"])


def test_toggle_run_and_history_contract_wizard():
    client = TestClient(app)
    headers = _auth_headers()

    toggle = client.patch("/api/v1/integrations/contract-wizard", headers=headers, json={"enabled": True})
    assert toggle.status_code == 200
    assert toggle.json()["enabled"] is True

    run = client.post(
        "/api/v1/integrations/contract-wizard/run",
        headers=headers,
        json={"payload": {"tenant_name": "Max", "property_name": "Musterweg 2"}},
    )
    assert run.status_code == 200
    body = run.json()
    assert body["success"] is True
    assert "Vertragsentwurf" in body["message"]

    history = client.get("/api/v1/integrations/contract-wizard/history?limit=5", headers=headers)
    assert history.status_code == 200
    items = history.json()["items"]
    assert len(items) >= 1
    assert items[0]["integration_id"] == "contract-wizard"


def test_schema_validate_and_config_masking_endpoint():
    client = TestClient(app)
    headers = _auth_headers()

    schema = client.get("/api/v1/integrations/whatsapp/schema", headers=headers)
    assert schema.status_code == 200
    schema_data = schema.json()
    assert "api_token" in schema_data["required_config_keys"]

    validate = client.post(
        "/api/v1/integrations/whatsapp/validate",
        headers=headers,
        json={"config": {"phone_number_id": "123"}},
    )
    assert validate.status_code == 200
    assert validate.json()["valid"] is False

    update = client.put(
        "/api/v1/integrations/whatsapp/config",
        headers=headers,
        json={"config": {"phone_number_id": "123", "api_token": "abc", "graph_version": "v23.0"}},
    )
    assert update.status_code == 200
    assert update.json()["config"]["api_token"] == "***"

    detail = client.get("/api/v1/integrations/whatsapp", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["configured"] is True
    assert detail.json()["config"]["api_token"] == "***"

    integration_manager.update_config("whatsapp", {
        "phone_number_id": None, "api_token": None, "graph_version": None,
    })


def test_metrics_and_history_clear_endpoint():
    client = TestClient(app)
    headers = _auth_headers()

    client.patch("/api/v1/integrations/contract-wizard", headers=headers, json={"enabled": True})
    client.post(
        "/api/v1/integrations/contract-wizard/run",
        headers=headers,
        json={"payload": {"tenant_name": "Metrics", "property_name": "Objekt 1"}},
    )

    metrics = client.get("/api/v1/integrations/metrics", headers=headers)
    assert metrics.status_code == 200
    assert metrics.json()["total_integrations"] >= 1
    assert metrics.json()["runs_total"] >= 1

    cleared = client.delete("/api/v1/integrations/contract-wizard/history", headers=headers)
    assert cleared.status_code == 200
    assert cleared.json()["id"] == "contract-wizard"

    history = client.get("/api/v1/integrations/contract-wizard/history", headers=headers)
    assert history.status_code == 200
    assert history.json()["items"] == []


def test_communication_integration_history_redacts_payload_and_provider_response():
    provider = WhatsAppIntegrationProvider()
    request, _schema, known = request_observation("whatsapp", {
        "action": "text", "to": "491701234567", "text": "Private Nachricht",
        "pdf_base64": "sensitive-document",
    }, {"phone_number_id": "123", "api_token": "secret"}, provider.manifest)
    response, _response_schema = response_observation({
        "success": True, "message": "accepted", "details": {
            "external_reference": "wamid.synthetic", "response": {"phone": "491701234567"},
        },
    }, known, integration_id="whatsapp")
    assert request["payload"] == {"action": "text"}
    assert response["details"] == {"external_reference": "wamid.synthetic"}
    assert "491701234567" not in repr({"request": request, "response": response})
    assert "Private Nachricht" not in repr({"request": request, "response": response})


def test_readonly_cannot_inspect_or_mutate_installation_integrations():
    client = TestClient(app)
    headers = _auth_headers("readonly")
    assert client.get("/api/v1/integrations", headers=headers).status_code == 403
    assert client.get("/api/v1/integrations/whatsapp/schema", headers=headers).status_code == 403
    assert client.patch("/api/v1/integrations/contract-wizard", headers=headers,
                        json={"enabled": True}).status_code == 403
    assert client.put("/api/v1/integrations/whatsapp/config", headers=headers,
                      json={"config": {"phone_number_id": "123"}}).status_code == 403
    assert client.post("/api/v1/integrations/contract-wizard/run", headers=headers,
                       json={"payload": {}}).status_code == 403
    assert client.delete("/api/v1/integrations/contract-wizard/history",
                         headers=headers).status_code == 403


def test_generic_run_cannot_bypass_reviewed_communication_workflows():
    client = TestClient(app)
    headers = _auth_headers()
    for integration_id in ("email", "whatsapp", "deutsche-post"):
        response = client.post(
            f"/api/v1/integrations/{integration_id}/run",
            headers=headers, json={"payload": {}},
        )
        assert response.status_code == 409
        assert "Kommunikationsversand" in response.json()["error"]["message"]
