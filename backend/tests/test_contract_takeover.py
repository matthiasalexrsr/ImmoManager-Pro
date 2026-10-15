"""Taking over a running tenancy: its account starts on the takeover day with the carried balance."""

from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import (
    AccountCreate,
    BookingCreate,
    ContractCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)
from backend.services import report_service
from backend.services.deposits import _rent_outstanding
from backend.services.document_versions import Unit
from backend.services.payment_allocations import auto_allocate, contract_payments, set_allocations, tenant_account

TAKEOVER = date(2026, 1, 1)


@pytest.fixture(autouse=True)
def clean():
    auth.clear_users()
    store.clear_all()
    yield
    auth.clear_users()
    store.clear_all()


@pytest.fixture
def client():
    return TestClient(app)


def headers(role="eigentuemer"):
    suffix = uuid4().hex[:8]
    account = auth.register_user(suffix, f"{suffix}@example.com", "Office", "Secret123", role)
    return {"Authorization": f"Bearer {auth.create_access_token(account.id)}"}


@pytest.fixture
def estate():
    """A tenancy running since 2019 at 500 € + 100 € advance, not yet taken over."""
    portfolio = store.create_portfolio(PortfolioCreate(name="Nord"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="Wohnung 1", unit_type="residential",
                                        cold_rent=500, service_charge_advance=100))
    tenant = store.create_tenant(TenantCreate(full_name="Mia Mieterin"))
    contract = store.create_contract(ContractCreate(contract_number="MV-1", property_id=prop.id, unit_id=unit.id,
                                                    tenant_id=tenant.id, start_date=date(2019, 5, 1)))
    account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Mietkonto", account_type="bank"))
    return dict(portfolio=portfolio, prop=prop, unit=unit, tenant=tenant, contract=contract, account=account)


def take_over(client, estate, **fields):
    response = client.patch(f"/api/v1/contracts/{estate['contract'].id}", headers=headers(),
                            json={"ledger_start": TAKEOVER.isoformat(), **fields})
    assert response.status_code == 200, response.text
    return response.json()


def pay(estate, amount, day):
    booking = store.create_booking(BookingCreate(
        account_id=estate["account"].id, tenant_id=estate["tenant"].id, unit_id=estate["unit"].id,
        property_id=estate["prop"].id, amount=amount, booking_date=day))
    auto_allocate(store, booking)
    return booking


def account_row(estate, as_of):
    return tenant_account(store, estate["tenant"].id, as_of)["contracts"][0]


def test_without_takeover_every_month_since_the_start_is_owed(estate):
    # the behaviour the takeover exists for: 81 months of 600 € since May 2019
    assert account_row(estate, date(2026, 1, 31))["outstanding"] == 81 * 600


def test_account_starts_on_the_takeover_day(client, estate):
    saved = take_over(client, estate)
    assert saved["ledger_start"] == "2026-01-01" and saved["carried_balance"] is None
    pay(estate, 600, date(2025, 12, 30))            # paid in the previous system: in the carried balance
    pay(estate, 600, date(2026, 1, 5))
    row = account_row(estate, date(2026, 3, 15))
    assert (row["expected"], row["paid"], row["outstanding"]) == (1800, 600, 1200)


def test_carried_arrears_are_the_oldest_claim(client, estate):
    take_over(client, estate, carried_balance=250.5)
    pay(estate, 600, date(2026, 1, 5))
    row = account_row(estate, date(2026, 1, 31))
    assert (row["expected"], row["paid"], row["outstanding"]) == (850.5, 600, 250.5)
    # the January payment settles the arrears first, so January stays partly open in the rent overview
    ledger = client.get("/api/v1/rent-charges/ledger?month=2026-01&as_of=2026-01-31", headers=headers()).json()
    january = ledger["rows"][0]
    assert (january["expected"], january["paid"], january["outstanding"]) == (600, 349.5, 250.5)
    # the contract's settlement names the carried line instead of a month
    settlement = client.get(f"/api/v1/contracts/{estate['contract'].id}/settlement?as_of=2026-01-31",
                            headers=headers()).json()
    first = settlement["settlement_lines"][0]
    assert (first["label"], first["due_date"], first["outstanding_amount"]) == (
        "Rückstand zum Übernahmetag", "2025-12-31", 0.0)
    assert [line["label"] for line in settlement["settlement_lines"][1:]] == [None]


def test_carried_credit_pays_the_first_months(client, estate):
    take_over(client, estate, carried_balance=-700)
    row = account_row(estate, date(2026, 2, 28))
    assert (row["expected"], row["paid"], row["outstanding"]) == (1200, 700, 500)
    assert account_row(estate, date(2026, 1, 31))["overpaid"] == 100


@pytest.mark.parametrize("carried", [300, -300])
def test_opening_balance_is_not_available_before_takeover(client, estate, carried):
    take_over(client, estate, carried_balance=carried)
    row = account_row(estate, date(2025, 12, 31))
    assert (row["expected"], row["paid"], row["outstanding"], row["overpaid"]) == (0, 0, 0, 0)
    response = client.get(f"/api/v1/contracts/{estate['contract'].id}/settlement?as_of=2025-12-31",
                          headers=headers())
    assert response.status_code == 200, response.text
    assert response.json()["settlement_lines"] == []


def test_refunding_opening_credit_reduces_every_account_view(client, estate):
    take_over(client, estate, carried_balance=-700)
    pay(estate, -250, date(2026, 1, 5))
    row = account_row(estate, date(2026, 1, 31))
    assert (row["expected"], row["paid"], row["outstanding"], row["overpaid"]) == (600, 450, 150, 0)
    # The refund has not happened yet in a historical snapshot.
    assert account_row(estate, date(2026, 1, 4))["overpaid"] == 100
    response = client.get("/api/v1/rent-charges/ledger?month=2026-01&as_of=2026-01-31", headers=headers())
    assert response.status_code == 200, response.text
    assert (response.json()["rows"][0]["paid"], response.json()["rows"][0]["outstanding"]) == (450, 150)
    response = client.get(f"/api/v1/dunning/contracts/{estate['contract'].id}?as_of=2026-01-31",
                          headers=headers())
    assert response.status_code == 200, response.text
    assert response.json()["totals"]["overdue_principal"] == 150


def test_a_return_consumes_new_receipts_before_opening_credit(client, estate):
    take_over(client, estate, carried_balance=-700)
    pay(estate, 200, date(2026, 1, 5))
    pay(estate, -250, date(2026, 1, 6))
    row = account_row(estate, date(2026, 1, 31))
    assert (row["paid"], row["outstanding"], row["overpaid"]) == (650, 0, 50)
    payments = contract_payments(store, store.get_contract(estate["contract"].id), until=date(2026, 1, 31))
    assert [(line.booking_date, float(line.amount)) for line in payments] == [(TAKEOVER, 650)]


def test_reversal_across_takeover_keeps_its_dated_debt_in_all_views(client, estate):
    take_over(client, estate, carried_balance=300)
    original = pay(estate, 600, date(2025, 12, 20))
    response = client.post(f"/api/v1/bookings/{original.id}/reverse", headers=headers(),
                           json={"amount": 600, "booking_date": "2026-01-01"})
    assert response.status_code == 201, response.text
    reversal_id = response.json()["id"]
    claim_key = f"rent:return:{reversal_id}"
    row = account_row(estate, date(2026, 1, 31))
    assert (row["expected"], row["paid"], row["outstanding"]) == (1500, 0, 1500)
    assert account_row(estate, date(2025, 12, 31))["outstanding"] == 0
    contract = store.get_contract(estate["contract"].id)
    assert _rent_outstanding(Unit(store, None, {}, None), contract, date(2026, 1, 31)) == 1500
    response = client.get(f"/api/v1/contracts/{contract.id}/settlement?as_of=2026-01-31", headers=headers())
    assert response.status_code == 200, response.text
    returned = next(line for line in response.json()["settlement_lines"] if line["claim_key"] == claim_key)
    assert (returned["due_date"], returned["total_amount"], returned["outstanding_amount"]) == (
        "2026-01-01", 600, 600)
    response = client.get(f"/api/v1/dunning/contracts/{contract.id}?as_of=2026-01-31", headers=headers())
    assert response.status_code == 200, response.text
    assert response.json()["totals"]["overdue_principal"] == 1500
    assert claim_key in {line["key"] for line in response.json()["claims"]}
    response = client.post(f"/api/v1/contracts/{contract.id}/dunning-campaign?as_of=2026-01-31", headers=headers())
    assert response.status_code == 200, response.text
    assert response.json()["total_principal"] == 1500
    response = client.get("/api/v1/rent-charges/ledger?month=2026-01&as_of=2026-01-31", headers=headers())
    assert response.status_code == 200, response.text
    # A first-of-month return must not replace the monthly-rent row.
    assert (response.json()["rows"][0]["expected"], response.json()["rows"][0]["outstanding"]) == (600, 600)


def test_return_excess_can_be_paid_later_without_same_day_claim_collisions(client, estate):
    take_over(client, estate)
    first = pay(estate, -150, date(2026, 1, 1))
    second = pay(estate, -50, date(2026, 1, 1))
    pay(estate, 100, date(2026, 1, 5))
    row = account_row(estate, date(2026, 1, 31))
    assert (row["expected"], row["paid"], row["outstanding"]) == (800, 100, 700)
    assert account_row(estate, date(2026, 1, 4))["outstanding"] == 800
    response = client.get(f"/api/v1/contracts/{estate['contract'].id}/settlement?as_of=2026-01-31",
                          headers=headers())
    assert response.status_code == 200, response.text
    lines = response.json()["settlement_lines"]
    assert len(lines) == 3
    assert {line["claim_key"] for line in lines if line["claim_key"]} == {
        f"rent:return:{first.id}", f"rent:return:{second.id}"}
    assert sum(line["paid_amount"] for line in lines) == 100
    assert sum(line["outstanding_amount"] for line in lines) == 700
    monthly = next(line for line in lines if line["label"] is None)
    assert (monthly["total_amount"], monthly["paid_amount"]) == (600, 0)
    response = client.get(f"/api/v1/dunning/contracts/{estate['contract'].id}?as_of=2026-01-31",
                          headers=headers())
    assert response.status_code == 200, response.text
    dunning_paid = {line["key"]: line["paid"] for line in response.json()["claims"]}
    assert {line["claim_key"]: line["paid_amount"] for line in lines
            if line["claim_key"] and line["outstanding_amount"] > 0} == {
        key: paid for key, paid in dunning_paid.items() if key.startswith("rent:return:")}


def test_return_without_takeover_also_preserves_excess_debt(client, estate):
    pay(estate, -50, date(2026, 1, 5))
    row = account_row(estate, date(2026, 1, 31))
    assert (row["expected"], row["paid"], row["outstanding"]) == (81 * 600 + 50, 0, 81 * 600 + 50)


def test_duplicate_manual_shares_make_one_return_claim(client, estate):
    take_over(client, estate)
    returned = pay(estate, -50, date(2026, 1, 5))
    contract_id = estate["contract"].id
    set_allocations(store, returned.id, [(contract_id, -30), (contract_id, -20)])
    pay(estate, 10, date(2026, 1, 6))
    response = client.get(f"/api/v1/contracts/{contract_id}/settlement?as_of=2026-01-31", headers=headers())
    assert response.status_code == 200, response.text
    lines = response.json()["settlement_lines"]
    returns = [line for line in lines if line["claim_key"] == f"rent:return:{returned.id}"]
    assert len(returns) == 1
    assert returns[0]["total_amount"] == 50
    assert sum(line["paid_amount"] for line in lines) == 10
    assert sum(line["outstanding_amount"] for line in lines) == 640


def test_dunning_names_the_carried_arrears_and_nothing_before(client, estate):
    take_over(client, estate, carried_balance=300)
    file = client.get(f"/api/v1/dunning/contracts/{estate['contract'].id}?as_of=2026-02-20",
                      headers=headers()).json()
    claims = {claim["key"]: claim for claim in file["claims"]}
    assert set(claims) == {"rent:carried", "rent:2026-01", "rent:2026-02"}
    assert claims["rent:carried"]["description"] == "Rückstand zum Übernahmetag"
    assert file["totals"]["overdue_principal"] == 300 + 600 + 600


def test_reports_keep_the_rent_due_before_the_takeover(client, estate):
    take_over(client, estate, carried_balance=300)
    due = report_service.rent_due_by_month(store, report_service.FinanceFilter(), date(2025, 12, 1),
                                           date(2026, 1, 31))
    assert {key: float(value) for key, value in due.items()} == {"2025-12": 600.0, "2026-01": 600.0}


@pytest.mark.parametrize("fields, message", [
    ({"ledger_start": "2026-01-15"}, "Monatsersten"),
    ({"ledger_start": "2019-05-01"}, "nach dem Vertragsbeginn"),
    ({"ledger_start": "2018-01-01"}, "nach dem Vertragsbeginn"),
    ({"carried_balance": 120}, "braucht das Datum"),
    ({"ledger_start": "2026-01-01", "end_date": "2025-06-30"}, "vor dem Vertragsende"),
])
def test_implausible_takeovers_are_refused(client, estate, fields, message):
    response = client.patch(f"/api/v1/contracts/{estate['contract'].id}", headers=headers(), json=fields)
    assert response.status_code in (400, 422), response.text
    assert message in response.text
    assert store.get_contract(estate["contract"].id).ledger_start is None


def test_clearing_the_takeover_restores_the_full_account(client, estate):
    take_over(client, estate, carried_balance=100)
    response = client.patch(f"/api/v1/contracts/{estate['contract'].id}", headers=headers(),
                            json={"ledger_start": None, "carried_balance": None})
    assert response.status_code == 200, response.text
    assert account_row(estate, date(2026, 1, 31))["outstanding"] == 81 * 600


def test_a_new_contract_can_be_created_as_taken_over(client, estate):
    unit = store.create_unit(UnitCreate(property_id=estate["prop"].id, label="Wohnung 2", unit_type="residential",
                                        cold_rent=400))
    response = client.post("/api/v1/contracts", headers=headers(), json={
        "contract_number": "MV-2", "property_id": estate["prop"].id, "unit_id": unit.id,
        "tenant_id": estate["tenant"].id, "start_date": "2015-03-01",
        "ledger_start": "2026-01-01", "carried_balance": -50})
    assert response.status_code == 201, response.text
    assert (response.json()["ledger_start"], response.json()["carried_balance"]) == ("2026-01-01", -50)


def test_the_takeover_survives_a_snapshot_round_trip(client, estate):
    from backend.services.data_snapshot import export_snapshot, import_snapshot

    take_over(client, estate, carried_balance=-12.34)
    snapshot = export_snapshot(store)
    import_snapshot(store, snapshot, replace=True)
    contract = store.get_contract(estate["contract"].id)
    assert (contract.ledger_start, contract.carried_balance) == (TAKEOVER, -12.34)
