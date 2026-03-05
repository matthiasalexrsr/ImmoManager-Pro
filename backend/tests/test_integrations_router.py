from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.services.integration_service import integration_service


def _auth_headers():
    clear_users()
    user = register_user("intg", "intg@example.com", "Int G", "Secret123", "eigentuemer")
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_list_integration_status_authenticated():
    client = TestClient(app)
    resp = client.get("/api/v1/integrations/status", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "integrations" in data
    assert any(i["id"] == "email" for i in data["integrations"])


def test_toggle_and_run_contract_wizard():
    client = TestClient(app)
    headers = _auth_headers()

    toggle = client.patch("/api/v1/integrations/contract-wizard", headers=headers, json={"enabled": False})
    assert toggle.status_code == 200
    assert toggle.json()["enabled"] is False

    run = client.post(
        "/api/v1/integrations/contract-wizard/run",
        headers=headers,
        json={"payload": {"tenant_name": "Max", "property_name": "Musterweg 2"}},
    )
    assert run.status_code == 200
    body = run.json()
    assert body["success"] is True
    assert "Vertragsentwurf" in body["message"]

    integration_service.toggle("contract-wizard", True)
