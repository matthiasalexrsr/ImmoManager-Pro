"""Real HTTP role boundaries and receipt validation; synthetic data only."""

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.services import credit_ledger as service
from backend.storage import InMemoryStore
from backend.tests.test_credit_ledger import credit_scenario, payout, reversal


@pytest.mark.parametrize("role", ["eigentuemer", "verwalter", "buchhaltung", "techniker", "readonly"])
def test_credit_commands_follow_billing_permissions_and_keep_actor(role, monkeypatch):
    clear_users()
    try:
        active = InMemoryStore()
        source, contract, _, _ = credit_scenario(active, monkeypatch)
        user = register_user("synthetic-credit", "credit@example.com", "Credit test", "Strong123", role)
        headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
        command = payout(source).model_dump(mode="json")
        with TestClient(app) as client:
            assert client.get(f"/api/v1/billing/contracts/{contract.id}/credits", headers=headers).status_code == 200
            assert client.post("/api/v1/billing/credit-payouts", json=command).status_code == 401
            response = client.post("/api/v1/billing/credit-payouts", json=command, headers=headers)
            if role in {"techniker", "readonly"}:
                assert response.status_code == 403
                assert service.journal(active, contract.id)["total"] == 0
                return
            assert response.status_code == 201, response.text
            receipt = response.json()
            assert receipt["actor_id"] == user.id and receipt["amount"] == "60.00"
            assert client.post("/api/v1/billing/credit-payouts", json=command, headers=headers).json() == receipt
            assert client.post("/api/v1/billing/credit-payouts", json={**command, "amount": "61"}, headers=headers).status_code == 409
            assert client.post("/api/v1/billing/credit-payouts", json={**command, "confirmed_payment": False}, headers=headers).status_code == 422
            assert client.post("/api/v1/billing/credit-payouts", json={**command, "source_settlement_id": "missing"}, headers=headers).status_code == 404
            request = reversal().model_dump(mode="json")
            result = client.post(f"/api/v1/billing/credit-receipts/{receipt['id']}/reversal", json=request, headers=headers)
            assert result.status_code == 201 and result.json()["actor_id"] == user.id
            assert service.summary(active, contract.id)["available_amount"] == "100.00"
    finally:
        clear_users()
