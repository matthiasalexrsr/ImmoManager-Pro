"""Real rent receipts: exact partials, statement date, retry, rollback and portfolio boundary."""

from datetime import date
from typing import Any
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
    DepositCreate,
    PortfolioCreate,
    PropertyCreate,
    RentChargeCreate,
    TenantCreate,
    UnitCreate,
)
from backend.services import rent_payments
from backend.services.housing_confirmation import etag
from backend.services.maintenance_rows import Rows
from backend.services.payment_allocations import tenant_account


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


def seed(target=store, number="MV-1"):
    portfolio = target.create_portfolio(PortfolioCreate(name="Nord"))
    prop = target.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential"))
    unit = target.create_unit(UnitCreate(property_id=prop.id, label="Wohnung 1", unit_type="residential",
                                         cold_rent=500, service_charge_advance=100))
    tenant = target.create_tenant(TenantCreate(full_name="Mia Mieterin"))
    contract = target.create_contract(ContractCreate(contract_number=number, property_id=prop.id, unit_id=unit.id,
                                                      tenant_id=tenant.id, start_date=date(2026, 1, 1), status="active"))
    account = target.create_account(AccountCreate(portfolio_id=portfolio.id, name="Mietkonto", account_type="bank"))
    return dict(portfolio=portfolio, prop=prop, unit=unit, tenant=tenant, contract=contract, account=account)


@pytest.fixture
def estate():
    return seed()


def user(role="buchhaltung", **kwargs):
    suffix = uuid4().hex[:8]
    account = auth.register_user(suffix, f"{suffix}@example.com", "Office", "Secret123", role, **kwargs)
    return account, {"Authorization": f"Bearer {auth.create_access_token(account.id)}"}


def payment(estate, **overrides):
    contract = estate["contract"]
    body = {"contract_id": contract.id, "contract_revision": etag("contracts", contract.id, contract.updated_at),
            "account_id": estate["account"].id, "amount": "200.10", "booking_date": "2026-01-07",
            "payment_text": "Teilzahlung Januar · Überweisung", "idempotency_key": str(uuid4())}
    return {**body, **overrides}


def post(client, headers, body):
    return client.post("/api/v1/rent-charges/contract-payment", json=body, headers=headers)


def ledger(client, headers, month="2026-01", as_of="2026-01-31"):
    response = client.get(f"/api/v1/rent-charges/ledger?month={month}&as_of={as_of}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_partial_receipts_are_real_cash_exact_allocations_and_date_cutoff(client, estate):
    _, headers = user()
    # A manually marked paid Sollstellung must neither fabricate cash nor double the contract rent.
    manual = store.create_rent_charge(RentChargeCreate(contract_id=estate["contract"].id, month="2026-01",
                                                       cold_rent=600, amount_paid=600, status="paid"))
    body = payment(estate)
    response = post(client, headers, body)
    assert response.status_code == 201, response.text
    booking = store.get_booking(response.json()["booking"]["id"])
    assert (booking.amount, booking.booking_date, booking.payment_text) == (200.10, date(2026, 1, 7), body["payment_text"])
    allocations = store.list_payment_allocations(booking_id=booking.id)
    assert [(a.contract_id, a.amount, a.source) for a in allocations] == [(estate["contract"].id, 200.10, "manual")]
    before = ledger(client, headers, as_of="2026-01-06")
    assert before["totals"] == {"expected": 600, "paid": 0, "outstanding": 600, "contract_credit": 0}
    after = ledger(client, headers)
    assert after["totals"] == {"expected": 600, "paid": 200.10, "outstanding": 399.90, "contract_credit": 0}
    assert tenant_account(store, estate["tenant"].id, date(2026, 1, 31))["totals"]["paid"] == 200.10
    assert store.get_rent_charge(manual.id) == manual
    second = post(client, headers, payment(estate, amount="399.90", booking_date="2026-01-15"))
    assert second.status_code == 201, second.text
    assert ledger(client, headers)["totals"] == {"expected": 600, "paid": 600, "outstanding": 0, "contract_credit": 0}
    dunning = client.get(f"/api/v1/dunning/contracts/{estate['contract'].id}?as_of=2026-01-31", headers=headers)
    assert dunning.status_code == 200, dunning.text
    # The same contract settlement used elsewhere sees the actual receipts, no fake status change.
    settlement = client.get(f"/api/v1/contracts/{estate['contract'].id}/settlement?as_of=2026-01-31", headers=headers).json()
    assert float(settlement["balance"]["outstanding_total"]) == 0


def test_same_command_replays_but_changed_amount_conflicts(client, estate):
    _, headers = user()
    body = payment(estate)
    first = post(client, headers, body)
    again = post(client, headers, body)
    assert first.status_code == again.status_code == 201
    assert again.json()["replayed"] is True
    assert again.json()["booking"]["id"] == first.json()["booking"]["id"]
    assert len(store.list_bookings()) == len(store.list_payment_allocations()) == 1
    assert post(client, headers, {**body, "amount": "200.11"}).status_code == 409
    assert len(store.list_bookings()) == 1


def test_deleted_booking_is_not_recreated_by_late_retry(client, estate):
    _, headers = user()
    body = payment(estate)
    first = post(client, headers, body)
    assert first.status_code == 201, first.text
    store.delete_booking(first.json()["booking"]["id"])
    response = post(client, headers, body)
    assert response.status_code == 409, response.text
    assert store.list_bookings() == []


@pytest.mark.parametrize("change", ["amount", "date", "note", "status", "binding", "allocation", "reversal"])
def test_late_retry_never_confirms_an_edited_or_reassigned_receipt(client, estate, change):
    _, headers = user()
    body = payment(estate)
    first = post(client, headers, body)
    assert first.status_code == 201, first.text
    booking_id = first.json()["booking"]["id"]
    if change == "allocation":
        from backend.services.payment_allocations import set_allocations
        set_allocations(store, booking_id, [])
    elif change == "reversal":
        response = client.post(f"/api/v1/bookings/{booking_id}/reverse", headers=headers,
                               json={"amount": 10, "booking_date": "2026-01-10"})
        assert response.status_code == 201, response.text
    else:
        changes: dict[str, dict[str, Any]] = {"amount": {"amount": 200.11}, "date": {"booking_date": date(2026, 1, 8)},
                   "note": {"payment_text": "Korrigiert"}, "status": {"status": "open"},
                   "binding": {"unit_id": None}}
        original = store.get_booking(booking_id)
        store.update_booking(booking_id, BookingCreate(**{
            **original.model_dump(exclude={"id", "created_at", "updated_at"}), **changes[change]}))
    response = post(client, headers, body)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "RENT_PAYMENT_CHANGED"
    assert response.json()["error"]["details"] == {"booking_id": booking_id}
    assert len(store.list_bookings()) == (2 if change == "reversal" else 1)


def test_missing_parent_confirms_no_write_but_inaccessible_receipt_remains_recorded(client, estate):
    actor, headers = user()
    absent = payment(estate, account_id=str(uuid4()))
    response = post(client, headers, absent)
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "RENT_PAYMENT_NOT_CREATED"
    assert store.list_bookings() == []
    body = payment(estate)
    assert post(client, headers, body).status_code == 201
    other = store.create_portfolio(PortfolioCreate(name="Süd"))
    auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": [other.id]})
    recorded = post(client, headers, body)
    assert recorded.status_code == 404, recorded.text
    assert recorded.json()["error"]["code"] == "RENT_PAYMENT_RECORDED_UNAVAILABLE"
    assert recorded.json()["error"]["details"] is None
    # An unrelated UUID cannot disclose any inaccessible command or booking fields.
    unknown = post(client, headers, {**body, "idempotency_key": str(uuid4())})
    assert unknown.status_code == 404, unknown.text
    assert unknown.json()["error"]["code"] == "RENT_PAYMENT_NOT_CREATED"
    assert unknown.json()["error"]["details"] is None
    assert len(store.list_bookings()) == 1


def test_deleted_contract_does_not_lose_the_durable_command_receipt(client, estate):
    _, headers = user()
    body = payment(estate)
    first = post(client, headers, body)
    assert first.status_code == 201, first.text
    store.delete_booking(first.json()["booking"]["id"])
    store.delete_contract(estate["contract"].id)
    response = post(client, headers, body)
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "RENT_PAYMENT_RECORDED_UNAVAILABLE"
    assert response.json()["error"]["details"] is None
    assert store.list_bookings() == []


def test_failure_after_allocation_rolls_back_every_row(client, estate, monkeypatch):
    actor, _ = user()
    real_add = Rows.add

    def failing_add(rows, table, record):
        if table == "change_history":
            raise RuntimeError("receipt write failed")
        return real_add(rows, table, record)

    monkeypatch.setattr(Rows, "add", failing_add)
    body = payment(estate)
    with pytest.raises(RuntimeError, match="receipt write failed"):
        rent_payments.record_payment(store, rent_payments.ContractPaymentRequest.model_validate(body), actor.id)
    assert store.list_bookings() == []
    assert store.list_payment_allocations() == []
    monkeypatch.setattr(Rows, "add", real_add)
    result = rent_payments.record_payment(store, rent_payments.ContractPaymentRequest.model_validate(body), actor.id)
    assert result["replayed"] is False
    assert len(store.list_bookings()) == 1


@pytest.mark.parametrize("overrides", [{"amount": "0"}, {"amount": "-1"}, {"amount": "1.001"},
                                       {"amount": "NaN"}, {"account_id": ""}, {"booking_date": "2999-01-01"}])
def test_invalid_payment_never_writes(client, estate, overrides):
    _, headers = user()
    assert post(client, headers, payment(estate, **overrides)).status_code == 422
    assert store.list_bookings() == store.list_payment_allocations() == []


def test_wrong_portfolio_stale_revision_and_readonly_are_refused(client, estate):
    _, headers = user()
    other = store.create_portfolio(PortfolioCreate(name="Süd"))
    account = store.create_account(AccountCreate(portfolio_id=other.id, name="Fremdes Konto", account_type="bank"))
    assert post(client, headers, payment(estate, account_id=account.id)).status_code == 422
    assert post(client, headers, payment(estate, contract_revision="old")).status_code == 409
    _, readonly = user("readonly")
    assert post(client, readonly, payment(estate)).status_code == 403
    assert store.list_bookings() == []


def test_selected_portfolio_and_actor_scoped_command(client, estate):
    _, headers = user(portfolio_access="selected", portfolio_ids=[estate["portfolio"].id])
    body = payment(estate)
    first = post(client, headers, body)
    assert first.status_code == 201, first.text
    assert ledger(client, headers)["totals"]["paid"] == 200.10
    other = store.create_portfolio(PortfolioCreate(name="Unsichtbar"))
    _, hidden = user(portfolio_access="selected", portfolio_ids=[other.id])
    assert ledger(client, hidden)["rows"] == []
    assert post(client, hidden, body).status_code == 404
    # Equal client key from another actor is a different intentional command, never another user's replay.
    _, other_actor = user()
    next_receipt = post(client, other_actor, body)
    assert next_receipt.status_code == 201, next_receipt.text
    assert not next_receipt.json()["replayed"]
    assert next_receipt.json()["booking"]["id"] != first.json()["booking"]["id"]


def test_fifo_storno_overpayment_and_unassigned_money(client, estate):
    _, headers = user()
    store.create_booking(BookingCreate(account_id=estate["account"].id, amount=9999, booking_date=date(2026, 1, 1)))
    first = post(client, headers, payment(estate, amount="800", booking_date="2026-02-07"))
    assert first.status_code == 201, first.text
    feb = ledger(client, headers, "2026-02", "2026-02-28")
    assert feb["totals"] == {"expected": 600, "paid": 200, "outstanding": 400, "contract_credit": 0}
    reverse = client.post(f"/api/v1/bookings/{first.json()['booking']['id']}/reverse", headers=headers,
                          json={"amount": 100, "booking_date": "2026-02-10"})
    assert reverse.status_code == 201, reverse.text
    assert ledger(client, headers, "2026-02", "2026-02-28")["totals"]["paid"] == 100
    assert post(client, headers, payment(estate, amount="600", booking_date="2026-02-12")).status_code == 201
    feb = ledger(client, headers, "2026-02", "2026-02-28")
    assert feb["totals"] == {"expected": 600, "paid": 600, "outstanding": 0, "contract_credit": 100}


def test_drafts_invalid_month_and_future_month(client, estate):
    _, headers = user()
    for month in ("2026-13", "2027-01"):
        response = client.get(f"/api/v1/rent-charges/ledger?month={month}&as_of=2026-01-31", headers=headers)
        assert response.status_code == 422
    contract = estate["contract"]
    changed = store.update_contract(contract.id, ContractCreate(**{**contract.model_dump(exclude={"id", "created_at", "updated_at"}), "status": "draft"}))
    estate["contract"] = changed
    assert ledger(client, headers)["rows"] == []
    assert post(client, headers, payment(estate)).status_code == 422


def test_sql_selected_tenants_never_materialize_unrelated_cash_or_links(client, estate, monkeypatch):
    if not hasattr(store, "db"):
        pytest.skip("SQL query shape only")
    from backend.services.payment_allocations import auto_allocate, credited_by_tenant

    # Add a second visible tenant and an unrelated tenant. The request's two tenants used
    # to select the whole installation's bookings and allocations before filtering in Python.
    extra = seed(number="MV-2")
    unrelated = seed(number="MV-3")
    for records, amount in ((estate, 200.10), (extra, 300.20), (unrelated, 9999)):
        booking = store.create_booking(BookingCreate(account_id=records["account"].id,
            tenant_id=records["tenant"].id, unit_id=records["unit"].id, property_id=records["prop"].id,
            amount=amount, booking_date=date(2026, 1, 7)))
        auto_allocate(store, booking)
    expected = credited_by_tenant(store, [estate["tenant"].id, extra["tenant"].id])

    def forbidden(*args, **kwargs):
        pytest.fail("A selected tenant read must not invoke a whole-table loader or booking-ID lists")

    monkeypatch.setattr(store, "list_bookings", forbidden)
    monkeypatch.setattr(store, "list_payment_allocations", forbidden)
    monkeypatch.setattr(store, "list_deposit_payments", forbidden)
    result = credited_by_tenant(store, [estate["tenant"].id, extra["tenant"].id], until=date(2026, 1, 31))
    assert result == expected
    assert set(result) == {estate["tenant"].id, extra["tenant"].id}
    assert credited_by_tenant(store, [estate["tenant"].id], until=date(2026, 1, 6)) == {}


def test_sql_tenant_subset_preserves_legacy_deposit_rounding_and_visibility(client, estate):
    if not hasattr(store, "db"):
        pytest.skip("SQLite legacy precision and scoped query parity")
    from sqlalchemy import insert

    from backend.db.deposit_models import DepositPaymentORM
    from backend.services.payment_allocations import credited_by_tenant
    from backend.services.portfolio_scope import scope_context, scope_from_user

    booking = store.create_booking(BookingCreate(account_id=estate["account"].id,
        tenant_id=estate["tenant"].id, unit_id=estate["unit"].id, property_id=estate["prop"].id,
        amount=100, booking_date=date(2026, 1, 7)))
    # SQLite can contain pre-validation imports with fractions of cents. The canonical
    # deposit read rounds each link; two half-cent links must subtract two cents.
    for _ in range(2):
        deposit = store.create_deposit(DepositCreate(contract_id=estate["contract"].id, amount=10))
        store.db.execute(insert(DepositPaymentORM).values(
            id=str(uuid4()), deposit_id=deposit.id, booking_id=booking.id, amount=0.005, kind="receipt"))
        store.db.commit()
    selected_actor, _ = user(portfolio_access="selected", portfolio_ids=[estate["portfolio"].id])
    selected_account = auth.get_user_by_id(selected_actor.id)
    assert selected_account is not None
    with scope_context(scope_from_user(selected_account)):
        tenants = [estate["tenant"].id, *(str(uuid4()) for _ in range(501))]
        bounded = credited_by_tenant(store, tenants, until=date(2026, 1, 31))
        canonical = credited_by_tenant(store, tenants, bookings=store.list_bookings(), until=date(2026, 1, 31))
        assert bounded == canonical
        assert str(bounded[estate["tenant"].id][0][2]) == "99.98"
        assert credited_by_tenant(store, tenants, until=date(2026, 1, 6)) == {}
    other = store.create_portfolio(PortfolioCreate(name="Süd"))
    hidden_actor, _ = user(portfolio_access="selected", portfolio_ids=[other.id])
    hidden_account = auth.get_user_by_id(hidden_actor.id)
    assert hidden_account is not None
    with scope_context(scope_from_user(hidden_account)):
        assert credited_by_tenant(store, tenants, until=date(2026, 1, 31)) == {}


def test_partial_first_month_uses_contract_history_and_not_the_editable_charge(client, estate):
    _, headers = user()
    contract = estate["contract"]
    changed = store.update_contract(contract.id, ContractCreate(**{
        **contract.model_dump(exclude={"id", "created_at", "updated_at"}), "start_date": date(2026, 2, 15)}))
    estate["contract"] = changed
    rows = ledger(client, headers, "2026-02", "2026-02-28")
    assert rows["totals"]["expected"] == 300
    assert post(client, headers, payment(estate, amount="100.10", booking_date="2026-02-16")).status_code == 201
    rows = ledger(client, headers, "2026-02", "2026-02-28")
    assert rows["totals"] == {"expected": 300, "paid": 100.10, "outstanding": 199.90, "contract_credit": 0}
