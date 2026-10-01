"""Actual authenticated API, selected portfolios, revoked scope and legacy handoff."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import auth, dependencies
from backend.routers import rent_batches, rent_charges
from backend.tests.test_rent_batches import batch_store, setup_contract  # noqa: F401


@pytest.fixture
def batch_http(batch_store, monkeypatch):  # noqa: F811
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    monkeypatch.setattr(dependencies, "store", batch_store)
    monkeypatch.setattr(rent_charges, "store", batch_store)
    contract, _ = setup_contract(batch_store)
    portfolio = batch_store.get_property(contract.property_id).portfolio_id
    owner = auth.register_user("batchowner", "owner@example.test", "Owner", "Strong123", "eigentuemer")
    member = auth.register_user("batchmember", "member@example.test", "Member", "Strong123", "verwalter",
        portfolio_access="selected", portfolio_ids=[portfolio])
    readonly = auth.register_user("batchreader", "reader@example.test", "Reader", "Strong123", "readonly")
    app = FastAPI()
    app.include_router(rent_batches.router, prefix="/api/v1")
    app.include_router(rent_charges.router, prefix="/api/v1")
    def headers(user):
        return {"Authorization": "Bearer " + auth.create_access_token(user.id)}
    with TestClient(app) as client:
        yield client, batch_store, contract, member, owner, headers(member), headers(owner), headers(readonly)


def test_real_http_batch_confirmation_is_explicit_and_grant_change_during_pause_blocks_resume(batch_http):
    client, store, contract, member, owner, headers, owner_headers, reader_headers = batch_http
    payload = {"start_month": "2026-10", "end_month": "2026-12", "contract_ids": [contract.id], "idempotency_key": "http"}
    assert client.post("/api/v1/rent-charges/batches", json=payload).status_code == 401
    assert client.post("/api/v1/rent-charges/batches", headers=reader_headers, json=payload).status_code == 403
    response = client.post("/api/v1/rent-charges/batches", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    job = response.json()
    listing = client.get("/api/v1/rent-charges/batches?page_size=1", headers=headers).json()
    assert listing["items"] == [{"id": job["id"], "created_at": job["created_at"], "state": "preparing", "available": True}]
    base = "/api/v1/rent-charges/batches/" + job["id"]
    assert client.get(base, headers=owner_headers).status_code == 404
    for _ in range(10):
        if job["state"] == "ready":
            break
        response = client.post(base + "/advance", headers=headers, json={"cursor": job["cursor"], "budget": 2})
        assert response.status_code == 200, response.text
        job = response.json()
    assert job["state"] == "ready" and len(store.list_rent_charges()) == 1
    response = client.post(base + "/confirm", headers=headers, json={"cursor": job["cursor"], "plan_hash": "f" * 64})
    assert response.status_code == 409 and response.json()["detail"]["clear_code"] == "RENT_PLAN_CHANGED"
    response = client.post(base + "/confirm", headers=headers, json={"cursor": job["cursor"], "plan_hash": job["plan_hash"]})
    assert response.status_code == 200, response.text
    job = response.json()
    job = client.post(base + "/pause", headers=headers, json={"cursor": job["cursor"]}).json()
    auth._user_store.update(member.id, {"portfolio_access": "selected", "portfolio_ids": []}, actor_id=owner.id)
    response = client.post(base + "/resume", headers=headers, json={"cursor": job["cursor"]})
    assert response.status_code == 403, response.text
    assert len(store.list_rent_charges()) == 1
    changed_listing = client.get("/api/v1/rent-charges/batches?page_size=1", headers=headers).json()
    assert changed_listing["items"][0]["available"] is False
    assert set(changed_listing["items"][0]) == {"id", "created_at", "state", "available"}


def test_other_portfolio_contract_cannot_enter_a_preparation_snapshot(batch_http):
    client, store, contract, member, owner, headers, *_ = batch_http
    from backend.models import ContractPatch
    from backend.tests.test_payments import seed
    store._patch_entity("contract", contract.id, ContractPatch(contract_number="First synthetic scope"))
    other = seed(store, "rent_charge")
    response = client.post("/api/v1/rent-charges/batches", headers=headers, json={
        "start_month": "2026-10", "end_month": "2026-10", "contract_ids": [other.contract_id], "idempotency_key": "private"})
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["clear_code"] == "RENT_CONTRACT_NOT_FOUND"


def test_moved_property_revokes_saved_snapshot_access_even_with_unchanged_user_grants(batch_http):
    client, store, contract, member, owner, headers, *_ = batch_http
    from backend.models import PortfolioCreate, PropertyPatch
    response = client.post("/api/v1/rent-charges/batches", headers=headers, json={
        "start_month": "2026-10", "end_month": "2026-10", "contract_ids": [contract.id], "idempotency_key": "moving"})
    assert response.status_code == 201, response.text
    job = response.json()
    job = client.post(f"/api/v1/rent-charges/batches/{job['id']}/advance", headers=headers,
        json={"cursor": job["cursor"], "budget": 2}).json()
    other = store.create_portfolio(PortfolioCreate(name="Other synthetic private portfolio"))
    store._patch_entity("property", contract.property_id, PropertyPatch(portfolio_id=other.id))
    response = client.get(f"/api/v1/rent-charges/batches/{job['id']}", headers=headers)
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["clear_code"] == "RENT_SCOPE_CHANGED"


def test_legacy_large_preview_and_generate_handoff_without_rejection_or_unconfirmed_charge(batch_http):
    client, store, contract, *_, headers, owner_headers, reader_headers = batch_http
    payload = {"start_month": "2026-10", "end_month": "2096-12", "contract_ids": [contract.id], "idempotency_key": "legacy-large"}
    first = client.post("/api/v1/rent-charges/preview", headers=headers, json=payload)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["policy"] == "durable_batch" and result["requires_confirmation"]
    second = client.post("/api/v1/rent-charges/generate", headers=headers, json=payload)
    assert second.status_code == 200 and second.json()["batch"]["id"] == result["batch"]["id"]
    assert len(store.list_rent_charges()) == 1
