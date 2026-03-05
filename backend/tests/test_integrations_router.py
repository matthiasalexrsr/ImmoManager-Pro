from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.services.integrations.manager import integration_manager


def _auth_headers():
    clear_users()
    user = register_user("intg", "intg@example.com", "Int G", "Secret123", "eigentuemer")
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
        json={"config": {"phone_number_id": "123", "api_token": "abc"}},
    )
    assert update.status_code == 200
    assert update.json()["config"]["api_token"] == "***"

    detail = client.get("/api/v1/integrations/whatsapp", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["configured"] is True
    assert detail.json()["config"]["api_token"] == "***"

    integration_manager.update_config("whatsapp", {"phone_number_id": None, "api_token": None})
