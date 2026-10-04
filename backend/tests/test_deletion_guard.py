"""Deleting a record that others depend on is refused instead of cascading."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.models import (
    AccountCreate,
    BookingCreate,
    ContractCreate,
    DepositCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)
from backend.services.data_snapshot import clear_business_data


@pytest.fixture
def client():
    clear_business_data(store)
    clear_users()
    owner = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    yield TestClient(app, headers={"Authorization": f"Bearer {create_access_token(owner.id)}"})
    clear_users()
    clear_business_data(store)


@pytest.fixture
def lease():
    pf = store.create_portfolio(PortfolioCreate(name="Bestand"))
    prop = store.create_property(PropertyCreate(portfolio_id=pf.id, name="MFH", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="WE 1", unit_type="residential"))
    tenant = store.create_tenant(TenantCreate(full_name="Mia Muster"))
    contract = store.create_contract(ContractCreate(contract_number="V-1", property_id=prop.id, unit_id=unit.id,
                                                    tenant_id=tenant.id, start_date=date(2024, 1, 1)))
    account = store.create_account(AccountCreate(portfolio_id=pf.id, name="Mietkonto", account_type="bank"))
    booking = store.create_booking(BookingCreate(account_id=account.id, tenant_id=tenant.id, property_id=prop.id,
                                                 booking_date=date(2025, 1, 3), amount=750))
    deposit = store.create_deposit(DepositCreate(contract_id=contract.id, amount=1800))
    return locals()


def _message(resp) -> str:
    return resp.json()["error"]["message"]


def test_tenant_with_contract_is_kept(client, lease):
    """Regression: deleting a tenant silently deleted their contract and deposit."""
    resp = client.delete(f"/api/v1/tenants/{lease['tenant'].id}")

    assert resp.status_code == 409
    assert "1 Vertrag, 1 Buchung" in _message(resp)
    assert "archivieren" in _message(resp)
    assert store.get_contract(lease["contract"].id)
    assert len(store.list_deposits()) == 1


def test_account_with_bookings_is_kept(client, lease):
    """Regression: deleting an account deleted every booking on it."""
    resp = client.delete(f"/api/v1/accounts/{lease['account'].id}")

    assert resp.status_code == 409
    assert store.get_booking(lease["booking"].id)


def test_portfolio_with_properties_and_accounts_is_kept(client, lease):
    resp = client.delete(f"/api/v1/portfolios/{lease['pf'].id}")

    assert resp.status_code == 409
    assert "1 Objekt, 1 Konto" in _message(resp)
    assert len(store.list_bookings()) == 1


@pytest.mark.parametrize("path,key", [("properties", "prop"), ("units", "unit"), ("contracts", "contract")])
def test_records_with_dependents_are_kept(client, lease, path, key):
    resp = client.delete(f"/api/v1/{path}/{lease[key].id}")

    assert resp.status_code == 409
    assert store.get_contract(lease["contract"].id)


def test_deleting_children_first_still_works(client, lease):
    for path, key in [("deposits", "deposit"), ("contracts", "contract"), ("bookings", "booking"),
                      ("tenants", "tenant"), ("accounts", "account"), ("units", "unit"),
                      ("properties", "prop"), ("portfolios", "pf")]:
        assert client.delete(f"/api/v1/{path}/{lease[key].id}").status_code == 204, path


def test_unknown_record_is_still_404(client):
    assert client.delete("/api/v1/tenants/missing").status_code == 404


def test_bulk_delete_skips_records_with_dependents(client, lease):
    lonely = store.create_tenant(TenantCreate(full_name="Ohne Vertrag"))

    resp = client.post("/api/v1/admin/bulk-delete/tenants", json={"ids": [lease["tenant"].id, lonely.id]})

    assert resp.json()["deleted"] == 1
    assert "1 Vertrag" in resp.json()["errors"][0]["error"]
    assert store.get_tenant(lease["tenant"].id)
