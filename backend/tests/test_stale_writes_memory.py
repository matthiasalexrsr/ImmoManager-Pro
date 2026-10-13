"""Actual concurrent HTTP edits recheck their original token at the memory write."""

import os
import threading
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import ContactCreate, Tenant, TenantCreate
from backend.models_service_contracts import ServiceContract, ServiceContractCreate
from backend.services import plausibility

pytestmark = pytest.mark.skipif(os.getenv("TEST_STORE_BACKEND") == "sql", reason="memory concurrency coverage")


@pytest.fixture(autouse=True)
def _clean():
    auth.clear_users()
    store.clear_all()
    yield
    auth.clear_users()
    store.clear_all()


@pytest.mark.parametrize("entity,method", [("tenant", "PUT"), ("tenant", "PATCH"), ("service_contract", "PUT")])
def test_concurrent_edit_accepts_only_one_original_token(monkeypatch, entity, method):
    original: Tenant | ServiceContract
    if entity == "tenant":
        original = store.create_tenant(TenantCreate(full_name="Original"))
        path, field, body = f"/api/v1/tenants/{original.id}", "full_name", {}
    else:
        provider = store.create_contact(ContactCreate(contact_type="supplier", company_name="Provider"))
        data = ServiceContractCreate(contract_type="cleaning", title="Original",
                                     provider_contact_id=provider.id, start_date=date(2025, 1, 1),
                                     end_date=date(2026, 12, 31))
        original = store.create_service_contract(data, [])
        path, field, body = f"/api/v1/service-contracts/{original.id}", "title", data.model_dump(mode="json")
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    headers = {"Authorization": f"Bearer {auth.create_access_token(owner.id)}"}
    token = original.updated_at.isoformat()
    checked = threading.Barrier(2, timeout=10)
    responses = []
    errors = []
    check = plausibility.check_not_stale

    def pause_after_check(request_method, request_path, payload, target):
        result = check(request_method, request_path, payload, target)
        if request_path == path.removeprefix("/api/v1"):
            checked.wait()
        return result

    monkeypatch.setattr(plausibility, "check_not_stale", pause_after_check)

    def write(name):
        try:
            with TestClient(app) as client:
                response = client.request(method, path, headers=headers,
                                          json={**body, field: name, "updated_at": token})
                responses.append((name, response.status_code))
        except BaseException as error:
            errors.append(repr(error))

    workers = [threading.Thread(target=write, args=(name,)) for name in ("First", "Second")]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(15)
    assert not any(worker.is_alive() for worker in workers)
    assert not errors, errors
    assert sorted(status for _, status in responses) == [200, 409], responses
    # A rejected request cannot replace the winner, and request tokens cannot leak.
    winner = next(name for name, status in responses if status == 200)
    monkeypatch.setattr(plausibility, "check_not_stale", check)
    with TestClient(app) as client:
        current = client.get(path, headers=headers)
        assert current.json()[field] == winner
        fresh = client.request(method, path, headers=headers,
                               json={**body, field: "Current", "updated_at": current.json()["updated_at"]})
        assert fresh.status_code == 200, fresh.text
        legacy = client.request(method, path, headers=headers, json={**body, field: "Without token"})
        assert legacy.status_code == 200, legacy.text
