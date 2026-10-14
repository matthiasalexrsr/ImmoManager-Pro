"""Contracts, statements and deposits reject data that cannot be right."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.models import (
    BillingPeriodCreate,
    ContractCreate,
    ContractPatch,
    DepositCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
    UtilityStatementCreate,
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
def house():
    pf = store.create_portfolio(PortfolioCreate(name="Bestand"))
    prop = store.create_property(PropertyCreate(portfolio_id=pf.id, name="MFH", property_type="residential"))
    other = store.create_property(PropertyCreate(portfolio_id=pf.id, name="Anderes", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="WE 6", unit_type="residential"))
    foreign_unit = store.create_unit(UnitCreate(property_id=other.id, label="X", unit_type="residential"))
    old = store.create_tenant(TenantCreate(full_name="Lukas Becker"))
    new = store.create_tenant(TenantCreate(full_name="Sophie Wagner"))
    lease = store.create_contract(ContractCreate(
        contract_number="A-006", property_id=prop.id, unit_id=unit.id, tenant_id=old.id,
        start_date=date(2021, 3, 1), end_date=date(2025, 6, 30), status="terminated"))
    return {"prop": prop, "unit": unit, "foreign_unit": foreign_unit, "new": new, "lease": lease}


def _contract(house, number="A-007", start="2025-09-01", status="active", end=None):
    return {"contract_number": number, "property_id": house["prop"].id, "unit_id": house["unit"].id,
            "tenant_id": house["new"].id, "start_date": start, "end_date": end, "status": status}


# --- Overlapping tenancies ---------------------------------------------------


def test_second_tenancy_of_a_let_unit_is_rejected(client, house):
    """Regression: a second active contract for an already let unit was accepted."""
    resp = client.post("/api/v1/contracts", json=_contract(house, start="2024-01-01"))

    assert resp.status_code == 400
    assert "bereits vermietet" in resp.json()["error"]["message"]
    assert "A-006" in resp.json()["error"]["message"]


@pytest.mark.parametrize("start,expected", [("2025-06-30", 400), ("2025-07-01", 201), ("2025-09-01", 201)])
def test_follow_up_tenancy_may_start_after_the_previous_one_ends(client, house, start, expected):
    assert client.post("/api/v1/contracts", json=_contract(house, start=start)).status_code == expected


def test_drafts_do_not_occupy_but_activating_them_is_checked(client, house):
    draft = client.post("/api/v1/contracts", json=_contract(house, start="2024-01-01", status="draft"))
    assert draft.status_code == 201

    resp = client.patch(f"/api/v1/contracts/{draft.json()['id']}", json={"status": "active"})

    assert resp.status_code == 400
    assert store.get_contract(draft.json()["id"]).status == "draft"


def test_patching_dates_into_an_overlap_is_rejected(client, house):
    follow_up = client.post("/api/v1/contracts", json=_contract(house)).json()

    resp = client.patch(f"/api/v1/contracts/{follow_up['id']}", json={"start_date": "2025-05-01"})

    assert resp.status_code == 400
    assert store.get_contract(follow_up["id"]).start_date == date(2025, 9, 1)


def test_expired_contracts_do_not_block(client, house):
    client.patch(f"/api/v1/contracts/{house['lease'].id}", json={"status": "expired", "end_date": None})

    assert client.post("/api/v1/contracts", json=_contract(house, start="2024-01-01")).status_code == 201


# --- PATCH validates before it writes ----------------------------------------


def test_invalid_contract_patch_is_not_stored(client, house):
    """Regression: the invalid status was stored, and listing contracts failed from then on."""
    resp = client.patch(f"/api/v1/contracts/{house['lease'].id}", json={"status": "kaputt"})

    assert resp.status_code == 422
    assert client.get("/api/v1/contracts").status_code == 200
    assert store.get_contract(house["lease"].id).status == "terminated"


@pytest.mark.parametrize("changes", [
    {"end_date": "2020-01-01"},             # before the start
    {"contract_number": None},              # required
])
def test_contract_patch_runs_model_validation(client, house, changes):
    resp = client.patch(f"/api/v1/contracts/{house['lease'].id}", json=changes)

    assert resp.status_code == 422
    assert store.get_contract(house["lease"].id).end_date == date(2025, 6, 30)


def test_contract_patch_runs_business_validation(client, house):
    resp = client.patch(f"/api/v1/contracts/{house['lease'].id}", json={"unit_id": house["foreign_unit"].id})

    assert resp.status_code == 400
    assert store.get_contract(house["lease"].id).unit_id == house["unit"].id


def test_store_patch_validates_before_writing(house):
    with pytest.raises(PydanticValidationError):
        store._patch_entity("contract", house["lease"].id, ContractPatch(status="kaputt"))

    assert store.get_contract(house["lease"].id).status == "terminated"


# --- Receivables from a utility statement -------------------------------------


def test_receivables_from_a_statement_are_created_once(client, house):
    """Regression: every call created the receivables again (12 instead of 6)."""
    period = store.create_billing_period(BillingPeriodCreate(
        property_id=house["prop"].id, label="BK 2024", start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31), status="finalized"))
    for balance in (120.5, -80.0, 0.0):
        store.create_utility_statement(UtilityStatementCreate(
            billing_period_id=period.id, contract_id=house["lease"].id, unit_id=house["unit"].id,
            total_cost=1000, advance_paid=1000 - balance, balance=balance))
    url = f"/api/v1/billing/periods/{period.id}/create-receivables"

    first = client.post(url).json()
    second = client.post(url).json()

    assert first["created_receivables"] == 2
    assert second["created_receivables"] == 0
    assert len(store.list_receivables()) == 2


# --- Deposits -------------------------------------------------------------------


@pytest.mark.parametrize("payload", [
    {"amount": -50},
    {"amount": 0},
    {"amount": 1560, "deductions": 2000},
    {"amount": 1560, "deductions": -10},
    {"amount": 1560, "held_date": "2020-04-01", "return_date": "2019-01-01"},
])
def test_impossible_deposits_are_rejected(client, house, payload):
    resp = client.post("/api/v1/deposits", json={"contract_id": house["lease"].id, **payload})

    assert resp.status_code == 400
    assert store.list_deposits() == []


def test_deposit_patch_cannot_exceed_the_deposit(client, house):
    deposit = store.create_deposit(DepositCreate(contract_id=house["lease"].id, amount=1560, held_date=date(2021, 3, 1)))

    too_much = client.patch(f"/api/v1/deposits/{deposit.id}", json={"status": "returned", "deductions": 2000})
    partial = client.patch(f"/api/v1/deposits/{deposit.id}",
                           json={"status": "partially_returned", "deductions": 300, "return_date": "2025-07-15"})

    assert too_much.status_code == 400
    assert partial.status_code == 200
    assert store.get_deposit(deposit.id).deductions == 300
