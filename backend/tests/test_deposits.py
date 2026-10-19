"""Kautionsakte: agreement (cap, instalments), receipts counted once, interest, settlement, retention release.

Runs on the memory store and, with TEST_STORE_BACKEND=sql, on SQLite (database triggers included);
PostgreSQL in test_deposits_postgres.py.
"""

import hashlib
import os
import uuid
from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from archive_helpers import purge_deposits, purge_handover, purge_originals
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.domain import deposit_rules as rules
from backend.models import (
    AccountCreate,
    BillingPeriodCreate,
    ContractCreate,
    MeterCreate,
    PortfolioCreate,
    PropertyCreate,
    ReceivableCreate,
    TenantCreate,
    UnitCreate,
    UtilityStatementCreate,
)
from backend.services.data_snapshot import (
    SNAPSHOT_FORMAT_VERSION,
    clear_business_data,
    export_snapshot,
    import_snapshot,
)

SQL = os.environ.get("TEST_STORE_BACKEND", "memory") == "sql"
API = "/api/v1"
BASE = f"{API}/deposits"


def _reset_data():
    purge_deposits(store)
    purge_handover(store)
    purge_originals(store)
    clear_business_data(store)


@pytest.fixture(autouse=True)
def _clean():
    _reset_data()
    auth.clear_users()
    yield
    _reset_data()
    auth.clear_users()


def _user(name, role="eigentuemer", **access):
    return auth.register_user(name, f"{name}@example.com", name.title(), "Secret123", role, **access)


def _client(user) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"})


@pytest.fixture
def client():
    return _client(_user("linda.reiser"))


def _estate(name="Nord", number="V-1"):
    portfolio = store.create_portfolio(PortfolioCreate(name=name, owner_name="Linda Reiser"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name=f"{name} Bautzner Straße 61",
                                                property_type="residential", address_line="Bautzner Straße 61",
                                                postal_code="01099", city="Dresden"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="WE 3", unit_type="residential", rooms=2,
                                        area_sqm=60, cold_rent=500, service_charge_advance=150, heating_advance=50))
    tenant = store.create_tenant(TenantCreate(full_name=f"Mia Muster {number}"))
    contract = store.create_contract(ContractCreate(
        contract_number=number, property_id=prop.id, unit_id=unit.id, tenant_id=tenant.id,
        start_date=date(2024, 1, 1), end_date=date(2026, 6, 30), status="terminated", deposit_amount=1500))
    account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Kautionskonto",
                                                 account_type="deposit"))
    rent = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Mietkonto", account_type="checking"))
    store.create_meter(MeterCreate(unit_id=unit.id, meter_type="cold_water", serial_number=f"KW-{number}"))
    return {"portfolio": portfolio, "property": prop, "unit": unit, "tenant": tenant, "contract": contract,
            "account": account, "rent_account": rent}


def _agreement(client, estate, **changes):
    body = {"contract_id": estate["contract"].id, "amount": 1500, "form": "transfer", "instalment_count": 3,
            "account_id": estate["account"].id, "institution": "Sparkasse", "account_reference": "DE00 1234",
            "account_holder": "Linda Reiser (Treuhand)"}
    body.update(changes)
    return client.post(f"{BASE}/agreements", json=body)


def _file(client, estate, **changes):
    response = _agreement(client, estate, **changes)
    assert response.status_code == 201, response.text
    return response.json()


def _book(client, estate, amount, day, account="account", text="Zahlung"):
    response = client.post(f"{API}/bookings", json={
        "account_id": estate[account].id, "tenant_id": estate["tenant"].id, "property_id": estate["property"].id,
        "unit_id": estate["unit"].id, "booking_date": day, "amount": amount, "payment_text": text})
    assert response.status_code == 201, response.text
    return response.json()


def _receive(client, deposit_id, booking_id, amount=None):
    body = {"booking_id": booking_id}
    if amount is not None:
        body["amount"] = amount
    return client.post(f"{BASE}/{deposit_id}/payments", json=body)


def _message(response):
    body = response.json()
    return body.get("error", {}).get("message") or body.get("detail") or ""


# ─── Pure rules ──────────────────────────────────────────────────────────────

def test_rules_cap_instalments_interest_and_settlement():
    assert rules.check_cap(Decimal("1500"), Decimal("500")).exceeds is False
    over = rules.check_cap(Decimal("1500.01"), Decimal("500"))
    assert over.exceeds and over.excess == Decimal("0.01") and over.cap == Decimal("1500.00")
    assert rules.check_cap(Decimal("9999"), None).cap is None          # unknown cold rent: no claim either way
    assert rules.instalment_due_dates(date(2024, 3, 15), 3) == [date(2024, 3, 15), date(2024, 4, 3), date(2024, 5, 3)]
    assert rules.instalment_due_dates(date(2024, 12, 1), 3) == [date(2024, 12, 1), date(2025, 1, 3), date(2025, 2, 3)]
    assert rules.split_amount(Decimal("1000"), 3) == [Decimal("333.34"), Decimal("333.33"), Decimal("333.33")]
    with pytest.raises(rules.DepositRuleError):
        rules.schedule(Decimal("1000"), date(2024, 1, 1), [Decimal("500"), Decimal("400")])
    with pytest.raises(rules.DepositRuleError):
        rules.instalment_due_dates(date(2024, 1, 1), 4)
    # receipts settle oldest first, each amount once; a correction lowers what was received
    states, surplus = rules.apply_receipts(rules.schedule(Decimal("900"), date(2024, 1, 1), count=3),
                                           [(date(2024, 1, 1), Decimal("400")), (date(2024, 2, 1), Decimal("-50"))])
    assert [(s.paid, s.status(date(2024, 1, 15))) for s in states] == [
        (Decimal("300.00"), "paid"), (Decimal("50.00"), "partial"), (Decimal("0.00"), "open")]
    assert surplus == 0
    # interest: 1000 from 1 July and 500 more from 1 August 2024 at 0.5 %, then 0.1 % from 1 March 2025
    result = rules.interest([(date(2024, 7, 1), Decimal("1000")), (date(2024, 8, 1), Decimal("500"))],
                            [rules.RatePeriod(date(2024, 1, 1), Decimal("0.5")),
                             rules.RatePeriod(date(2025, 3, 1), Decimal("0.1"))], date(2025, 6, 30))
    # 2024 (366 days): 1000 × 0.5 % × 31/366 + 1500 × 0.5 % × 153/366 = 3.5587 → 3.56 capitalised
    # 2025: 1503.56 × 0.5 % × 59/365 + 1503.56 × 0.1 % × 121/365 = 1.7137 → 1.71
    assert [(y.year, y.interest) for y in result.years] == [(2024, Decimal("3.56")), (2025, Decimal("1.71"))]
    assert result.total == Decimal("5.27") and result.balance == Decimal("1505.27")
    assert rules.interest([(date(2024, 1, 1), Decimal("1000"))], [], date(2026, 1, 1)).total == 0
    assert rules.parse_rate("0,25") == Decimal("0.25")
    for bad in ("0.12345", "-1", "30", "abc"):
        with pytest.raises(rules.DepositRuleError):
            rules.parse_rate(bad)
    # settlement: credit 1510, defect 200, rent offset 300, retention 100 → payout 910
    outcome = rules.settle(Decimal("1500"), Decimal("10"), [
        rules.Item("defect", Decimal("200")), rules.Item("rent_arrears", Decimal("300")),
        rules.Item("retention", Decimal("100"))])
    assert (outcome.credit, outcome.claims, outcome.result, outcome.payout, outcome.remaining_claim) == (
        Decimal("1510.00"), Decimal("500.00"), Decimal("910.00"), Decimal("910.00"), Decimal("0.00"))
    # new claims beyond the credit become a remaining claim; offsets of existing claims never do
    short = rules.settle(Decimal("500"), Decimal("0"), [rules.Item("offsets" if False else "receivable",
                                                                   Decimal("300")),
                                                        rules.Item("defect", Decimal("450"))])
    assert (short.payout, short.remaining_claim) == (Decimal("0.00"), Decimal("250.00"))
    with pytest.raises(rules.DepositRuleError):
        rules.settle(Decimal("500"), Decimal("0"), [rules.Item("receivable", Decimal("600"))])
    with pytest.raises(rules.DepositRuleError):
        rules.settle(Decimal("500"), Decimal("0"), [rules.Item("defect", Decimal("450")),
                                                    rules.Item("retention", Decimal("100"))])


# ─── Agreement ───────────────────────────────────────────────────────────────

def test_the_agreement_respects_three_net_cold_rents_and_the_instalments(client):
    estate = _estate()
    source = client.get(f"{BASE}/source", params={"contract_id": estate["contract"].id}).json()
    assert source["cap"] == {"cold_rent": 500.0, "cap": 1500.0, "exceeds": False, "excess": 0.0, "known": True}
    assert source["suggested_amount"] == 1500.0
    assert [i["due_date"] for i in source["schedules"]["3"]] == ["2024-01-01", "2024-02-03", "2024-03-03"]
    assert {a["name"] for a in source["accounts"]} == {"Kautionskonto", "Mietkonto"}

    too_high = _agreement(client, estate, amount=1600)
    assert too_high.status_code == 400 and "drei Nettokaltmieten" in _message(too_high)
    assert store.list_deposits() == []
    reasoned = _file(client, estate, amount=1600, cap_reason="Zusätzliche Sicherheit für Einbauküche (vereinbart)")
    assert reasoned["cap"]["exceeds"] and reasoned["cap"]["excess"] == 100.0

    detail = _file(client, estate)
    assert [(i["number"], i["due_date"], i["amount"], i["status"]) for i in detail["instalments"]] == [
        (1, "2024-01-01", 500.0, "overdue"), (2, "2024-02-03", 500.0, "overdue"), (3, "2024-03-03", 500.0, "overdue")]
    assert detail["stage"] == "agreed" and detail["account"]["name"] == "Kautionskonto"
    uneven = _agreement(client, estate, instalment_amounts=[700, 700])
    assert uneven.status_code == 400 and "Raten ergeben" in _message(uneven)
    four = _agreement(client, estate, instalment_amounts=[400, 400, 400, 300])
    assert four.status_code == 422
    guarantee = _agreement(client, estate, form="guarantee", account_id=None, instalment_count=2)
    assert guarantee.status_code == 400
    foreign = _estate("Süd", "S-1")
    other_account = _agreement(client, estate, account_id=foreign["account"].id)
    assert other_account.status_code == 400

    revision = detail["deposit"]["revision"]
    changed = client.put(f"{BASE}/{detail['deposit']['id']}/agreement", json={
        "base_revision": revision, "contract_id": estate["contract"].id, "amount": 1200, "form": "cash",
        "instalment_amounts": [600, 600]})
    assert changed.status_code == 200, changed.text
    assert [i["amount"] for i in changed.json()["instalments"]] == [600.0, 600.0]
    stale = client.put(f"{BASE}/{detail['deposit']['id']}/agreement", json={
        "base_revision": revision, "contract_id": estate["contract"].id, "amount": 1000})
    assert stale.status_code == 409


# ─── Receipts ────────────────────────────────────────────────────────────────

def test_partial_payments_settle_the_instalments_and_count_once(client):
    estate = _estate()
    detail = _file(client, estate)
    deposit_id = detail["deposit"]["id"]
    first = _book(client, estate, 500, "2024-01-01", text="Kaution 1. Rate")
    combined = _book(client, estate, 1200, "2024-02-03", text="Miete Februar und Kaution")   # 700 rent + 500
    partial = _book(client, estate, 200, "2024-03-03", text="Kaution Teil")
    rent_only = _book(client, estate, 700, "2024-01-03", account="rent_account", text="Miete Januar")

    candidates = client.get(f"{BASE}/{deposit_id}/payment-candidates").json()["items"]
    assert {c["booking_id"] for c in candidates} == {first["id"], combined["id"], partial["id"]}   # deposit account only
    assert _receive(client, deposit_id, first["id"]).status_code == 200
    assert _receive(client, deposit_id, first["id"]).status_code == 409        # once per deposit
    too_much = _receive(client, deposit_id, combined["id"], 1300)
    assert too_much.status_code == 400
    assert _receive(client, deposit_id, combined["id"], 500).status_code == 200
    wrong_account = _receive(client, deposit_id, rent_only["id"])
    assert wrong_account.status_code == 400
    result = _receive(client, deposit_id, partial["id"]).json()
    assert result["received"] == 1200.0 and result["outstanding"] == 300.0 and result["stage"] == "partially_received"
    assert [(i["paid"], i["open"]) for i in result["instalments"]] == [(500.0, 0.0), (500.0, 0.0), (200.0, 300.0)]

    # the rent account counts only what is not deposit: 700 + 700 for January and February, nothing unassigned
    allocations = {a["booking_id"]: a["amount"] for a in client.get(f"{API}/bookings/allocations").json()}
    assert allocations == {combined["id"]: 700.0, rent_only["id"]: 700.0}
    account = client.get(f"{API}/tenants/{estate['tenant'].id}/account", params={"as_of": "2024-03-31"}).json()
    assert account["totals"]["paid"] == 1400.0 and account["totals"]["unassigned"] == 0.0
    assert account["deposit_total"] == 1200.0
    assert client.post(f"{API}/bookings/allocate-unassigned").json()["unassigned"] == []   # all-deposit: no rent
    review = client.get(f"{API}/review").json()
    assert not [i for i in review.get("items", review) if i.get("kind") == "unassigned_payment"]

    # a booking of the deposit file keeps amount and date; it cannot be deleted
    changed = client.patch(f"{API}/bookings/{partial['id']}", json={"amount": 150})
    assert changed.status_code == 409
    assert client.patch(f"{API}/bookings/{partial['id']}", json={"payment_text": "Kaution Rest"}).status_code == 200
    assert client.delete(f"{API}/bookings/{partial['id']}").status_code == 409
    # unlinking credits the money to rent again
    link = next(p for p in result["payments"] if p["booking_id"] == partial["id"])
    after = client.delete(f"{BASE}/{deposit_id}/payments/{link['id']}").json()
    assert after["received"] == 1000.0
    allocations = {a["booking_id"]: a["amount"] for a in client.get(f"{API}/bookings/allocations").json()}
    assert allocations[partial["id"]] == 200.0


def test_a_returned_deposit_payment_is_a_correction_of_the_receipt(client):
    estate = _estate()
    deposit_id = _file(client, estate)["deposit"]["id"]
    paid = _book(client, estate, 1500, "2024-01-01")
    _receive(client, deposit_id, paid["id"])
    reversal = client.post(f"{API}/bookings/{paid['id']}/reverse", json={"amount": 1500,
                                                                         "booking_date": "2024-01-10"}).json()
    corrected = _receive(client, deposit_id, reversal["id"])
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["received"] == 0.0
    allocations = [a for a in client.get(f"{API}/bookings/allocations").json()
                   if a["booking_id"] in (paid["id"], reversal["id"])]
    assert allocations == []


def test_manual_rent_allocation_and_deposit_never_exceed_the_booking(client):
    estate = _estate()
    deposit_id = _file(client, estate)["deposit"]["id"]
    booking = _book(client, estate, 1000, "2024-01-01")
    manual = client.put(f"{API}/bookings/{booking['id']}/allocations",
                        json=[{"contract_id": estate["contract"].id, "amount": 700}])
    assert manual.status_code == 200
    assert _receive(client, deposit_id, booking["id"], 400).status_code == 400
    assert _receive(client, deposit_id, booking["id"]).json()["received"] == 300.0
    again = client.put(f"{API}/bookings/{booking['id']}/allocations",
                       json=[{"contract_id": estate["contract"].id, "amount": 800}])
    assert again.status_code == 400


# ─── Interest ────────────────────────────────────────────────────────────────

def test_interest_periods_are_exact_and_need_no_invented_rate(client):
    estate = _estate()
    detail = _file(client, estate, instalment_count=1)
    deposit_id = detail["deposit"]["id"]
    booking = _book(client, estate, 1500, "2024-01-01")
    detail = _receive(client, deposit_id, booking["id"]).json()
    assert detail["interest_rates"] == [] and detail["interest"]["total"] == 0.0
    rates = client.put(f"{BASE}/{deposit_id}/interest-rates", json={
        "base_revision": detail["deposit"]["revision"],
        "rates": [{"valid_from": "2024-01-01", "rate_percent": "1"}, {"valid_from": "2025-01-01",
                                                                      "rate_percent": "0,5"}]})
    assert rates.status_code == 200, rates.text
    bad = client.put(f"{BASE}/{deposit_id}/interest-rates", json={
        "base_revision": rates.json()["deposit"]["revision"], "rates": [{"valid_from": "2024-01-01",
                                                                         "rate_percent": "0.12345"}]})
    assert bad.status_code == 400
    years = rates.json()["interest"]["years"]
    # 2024: 1500 × 1 % = 15.00; 2025: 1515 × 0.5 % = 7.58 (7.575 rounded half up)
    assert [(y["year"], y["interest"]) for y in years[:2]] == [(2024, "15.00"), (2025, "7.58")]


# ─── Takeover of a deposit paid before the app ───────────────────────────────

def _take_over(client, deposit_id, **values):
    revision = client.get(f"{BASE}/{deposit_id}/file").json()["deposit"]["revision"]
    return client.put(f"{BASE}/{deposit_id}/takeover", json={"base_revision": revision, **values})


def test_a_deposit_paid_before_the_app_is_taken_over_and_settled_with_its_interest(client):
    estate = _estate()
    detail = _file(client, estate)                               # 3 × 500 from 1 January 2024
    deposit_id = detail["deposit"]["id"]
    assert (detail["received"], detail["stage"]) == (0.0, "agreed")
    client.put(f"{BASE}/{deposit_id}/interest-rates", json={
        "base_revision": detail["deposit"]["revision"], "rates": [{"valid_from": "2024-01-01", "rate_percent": "1"}]})
    before = _book(client, estate, 100, "2024-12-01", text="Kaution Rest (im Vorsystem verbucht)")

    taken = _take_over(client, deposit_id, carried_on="2025-01-01", carried_amount=1500, carried_interest=15,
                       carried_note="Kontoauszug Sparkasse vom 31.12.2024")
    assert taken.status_code == 200, taken.text
    detail = taken.json()
    assert (detail["received"], detail["outstanding"], detail["surplus"], detail["stage"]) == (
        1500.0, 0.0, 0.0, "received")
    assert [i["status"] for i in detail["instalments"]] == ["paid", "paid", "paid"]
    assert detail["deposit"]["carried_note"] == "Kontoauszug Sparkasse vom 31.12.2024"
    # interest from the takeover day on 1500 + the 15.00 credited until then: 2025 = 1515 × 1 % = 15.15
    assert detail["interest"]["carried"] == 15.0
    assert (detail["interest"]["years"][0]["year"], detail["interest"]["years"][0]["principal_start"],
            detail["interest"]["years"][0]["interest"]) == (2025, "1515.00", "15.15")
    assert detail["interest"]["total"] == 15.0 + sum(float(y["interest"]) for y in detail["interest"]["years"])
    listed = client.get(f"{BASE}/files").json()["items"][0]
    assert (listed["received"], listed["outstanding"], listed["stage"]) == (1500.0, 0.0, "received")
    # a booking before the takeover day is part of the carried amount
    candidates = client.get(f"{BASE}/{deposit_id}/payment-candidates").json()["items"]
    assert before["id"] not in {row["booking_id"] for row in candidates}
    refused = _receive(client, deposit_id, before["id"])
    assert refused.status_code == 400 and "Übernahmetag" in _message(refused)

    draft = client.post(f"{BASE}/{deposit_id}/settlements", json={"kind": "final"}).json()["settlements"][0]
    assert not any(p["code"] in ("no_receipt", "not_fully_received") for p in draft["problems"])
    # 15.00 carried + 2025: 15.15 + 2026 to 30 June: 1530.15 × 1 % × 180/365 = 7.5459 → 7.55
    assert draft["interest"]["carried"] == 15.0 and draft["interest"]["computed"] == 37.7
    assert (draft["outcome"]["principal"], draft["outcome"]["interest"], draft["outcome"]["payout"]) == (
        "1500.00", "37.70", "1537.70")
    preview, final = _finalize(client, deposit_id, draft["id"])
    assert final.status_code == 200, final.text
    done = final.json()
    assert done["stage"] == "settled"
    original = done["settlements"][0]["original"]
    assert original["outcome"]["payout"] == "1537.70" and original["interest"]["carried"] == "15.00"
    payout = next(b for b in store.list_bookings() if b.id == done["settlements"][0]["payout_booking_id"])
    assert payout.amount == -1537.70
    # a settled deposit keeps its takeover
    assert _take_over(client, deposit_id).status_code == 409
    if SQL:
        with store.db.get_bind().connect() as connection:
            for statement in ("UPDATE deposits SET carried_amount = 1", "UPDATE deposits SET carried_on = NULL"):
                with pytest.raises(sa.exc.DBAPIError, match="immutable"):
                    with connection.begin():
                        connection.exec_driver_sql(statement)


def test_takeover_rules(client):
    estate = _estate()
    deposit_id = _file(client, estate)["deposit"]["id"]
    for values, status, text in (
            ({"carried_on": "2099-01-01", "carried_amount": 500}, 400, "Zukunft"),
            ({"carried_amount": 500}, 400, "Übernahmetag"),
            ({"carried_on": "2025-01-01"}, 400, "Übernahmetag"),
            ({"carried_on": "2025-01-01", "carried_amount": 500.005}, 400, "Nachkommastellen"),
            ({"carried_interest": 5}, 400, "übernommenen Betrag"),
    ):
        response = _take_over(client, deposit_id, **values)
        assert response.status_code == status and text in _message(response), (values, response.text)
    stale = client.put(f"{BASE}/{deposit_id}/takeover", json={"base_revision": "stale", "carried_on": "2025-01-01",
                                                              "carried_amount": 500})
    assert stale.status_code == 409
    # a receipt linked before the day would count twice
    early = _book(client, estate, 500, "2024-01-01")
    assert _receive(client, deposit_id, early["id"]).status_code == 200
    clash = _take_over(client, deposit_id, carried_on="2025-01-01", carried_amount=1000)
    assert clash.status_code == 409 and "doppelt" in _message(clash)
    # with a takeover from 1 January 2024 the receipt that day counts in addition
    combined = _take_over(client, deposit_id, carried_on="2024-01-01", carried_amount=1000).json()
    assert (combined["received"], combined["stage"]) == (1500.0, "received")
    assert _agreement(client, estate).status_code == 201       # another file of the contract is untouched
    guarantee = client.put(f"{BASE}/{deposit_id}/agreement", json={
        "base_revision": combined["deposit"]["revision"], "contract_id": estate["contract"].id, "amount": 1500,
        "form": "guarantee"})
    assert guarantee.status_code == 409
    removed = _take_over(client, deposit_id).json()
    assert removed["received"] == 500.0 and removed["deposit"]["carried_on"] is None
    # read-only roles cannot take over
    readonly = _client(_user("rita", "readonly"))
    assert _take_over(readonly, deposit_id, carried_on="2024-01-01", carried_amount=1000).status_code == 403


def test_a_takeover_after_the_settlement_date_cannot_be_paid_out(client):
    estate = _estate()
    deposit_id = _file(client, estate)["deposit"]["id"]
    taken = _take_over(client, deposit_id, carried_on="2026-07-01", carried_amount=1500, carried_interest=20)
    assert taken.status_code == 200, taken.text
    draft = client.post(f"{BASE}/{deposit_id}/settlements", json={"kind": "final"}).json()["settlements"][0]
    problem = next(item for item in draft["problems"] if item["code"] == "receipt_after_date")
    assert problem["blocking"] is True
    before = {row.id for row in store.list_bookings()}
    _, refused = _finalize(client, deposit_id, draft["id"])
    assert refused.status_code == 409, refused.text
    assert {row.id for row in store.list_bookings()} == before
    corrected = _settle(client, deposit_id, draft, [], day="2026-07-01")
    assert not any(item["code"] == "receipt_after_date" for item in corrected["problems"])


@pytest.mark.parametrize("status", ["returned", "partially_returned"])
def test_a_returned_legacy_deposit_cannot_be_taken_over_as_a_fresh_receipt(client, status):
    estate = _estate()
    deposit = client.post(BASE, json={"contract_id": estate["contract"].id, "amount": 1500, "status": status,
        "held_date": "2024-01-01", "return_date": "2026-06-30"}).json()
    refused = _take_over(client, deposit["id"], carried_on="2024-01-01", carried_amount=1500)
    assert refused.status_code == 409 and "zurückgezahlt" in _message(refused)
    detail = client.get(f"{BASE}/{deposit['id']}/file").json()
    assert detail["received"] == 0 and detail["deposit"]["carried_on"] is None


def test_earlier_plain_records_are_taken_over_in_one_step(client):
    north, south, east = _estate("Nord", "N-1"), _estate("Süd", "S-1"), _estate("Ost", "O-1")
    held = client.post(BASE, json={"contract_id": north["contract"].id, "amount": 1500, "status": "held",
                                   "held_date": "2024-01-01"}).json()
    other = client.post(BASE, json={"contract_id": south["contract"].id, "amount": 900.5, "status": "held",
                                    "held_date": "2023-05-02"}).json()
    undated = client.post(BASE, json={"contract_id": east["contract"].id, "amount": 800}).json()
    returned = client.post(BASE, json={"contract_id": east["contract"].id, "amount": 700, "status": "returned",
                                       "held_date": "2020-01-01", "return_date": "2023-12-31"}).json()
    agreement = _file(client, east)["deposit"]["id"]          # a file of this version: not a plain record
    stages = {row["id"]: row["stage"] for row in client.get(f"{BASE}/files").json()["items"]}
    assert stages[returned["id"]] == "settled"                 # returned with the earlier record, not "agreed"

    candidates = client.get(f"{BASE}/legacy-takeover").json()
    assert {row["id"] for row in candidates["items"]} == {held["id"], other["id"]}
    assert (candidates["count"], candidates["amount"]) == (2, 2400.5)
    assert undated["id"] not in {row["id"] for row in candidates["items"]} and agreement
    readonly = _client(_user("rita", "readonly"))
    assert readonly.post(f"{BASE}/legacy-takeover", json={"deposit_ids": [held["id"]]}).status_code == 403

    done = client.post(f"{BASE}/legacy-takeover", json={"deposit_ids": [row["id"] for row in candidates["items"]]})
    assert done.status_code == 200 and done.json() == {"taken_over": 2}
    north_file = client.get(f"{BASE}/{held['id']}/file").json()
    assert (north_file["received"], north_file["stage"], north_file["deposit"]["carried_on"]) == (
        1500.0, "received", "2024-01-01")
    assert "bisherigen Kautionsdatensatz" in north_file["deposit"]["carried_note"]
    assert north_file["legacy_candidate"] is False
    assert client.get(f"{BASE}/legacy-takeover").json()["count"] == 0
    # all or none: a record that is no longer a plain one refuses the whole request
    again = client.post(f"{BASE}/legacy-takeover", json={"deposit_ids": [held["id"]]})
    assert again.status_code == 409 and "nichts wurde übernommen" in _message(again)
    # a restricted account takes over only what it sees
    later = client.post(BASE, json={"contract_id": south["contract"].id, "amount": 300, "status": "held",
                                    "held_date": "2024-02-01"}).json()
    staff = _client(_user("staff", "verwalter", portfolio_access="selected", portfolio_ids=[north["portfolio"].id]))
    assert staff.get(f"{BASE}/legacy-takeover").json()["count"] == 0
    assert staff.post(f"{BASE}/legacy-takeover", json={"deposit_ids": [later["id"]]}).status_code == 404
    # the takeover travels with snapshots
    data = export_snapshot(store)
    _reset_data()
    import_snapshot(store, data, replace=True)
    restored = client.get(f"{BASE}/{other['id']}/file").json()
    assert (restored["received"], restored["deposit"]["carried_on"], restored["deposit"]["carried_amount"]) == (
        900.5, "2023-05-02", 900.5)


# ─── Settlement ──────────────────────────────────────────────────────────────

def _move_out_protocol(client, estate):
    """A finalized move-out protocol with one defect on the tenant."""
    base = f"{API}/handover-protocols"
    detail = client.post(f"{base}/from-contract", json={"contract_id": estate["contract"].id,
                                                        "protocol_type": "move_out"}).json()
    rooms = [{"id": r["id"], "name": r["name"], "condition": "good", "notes": None} for r in detail["rooms"]]
    defect_id = str(uuid.uuid4())
    protocol = detail["protocol"]
    body = {"base_revision": protocol["revision"],
            **{name: protocol[name] for name in ("protocol_date", "tenant_present", "landlord_present",
                                                 "overall_condition", "notes", "tenant_signature",
                                                 "landlord_signature")},
            "rooms": rooms,
            "defects": [{"id": defect_id, "room_id": rooms[1]["id"], "description": "Bohrlöcher in der Küchenwand",
                         "responsible": "tenant", "remedy": None, "due_date": None},
                        {"id": str(uuid.uuid4()), "room_id": None, "description": "Heizkörper alt",
                         "responsible": "landlord", "remedy": None, "due_date": None}],
            "keys": [{"id": str(uuid.uuid4()), "key_type": "apartment_door", "label": "Wohnung", "handed_over": 2,
                      "returned": 2, "notes": None}],
            "meter_readings": []}
    saved = client.put(f"{base}/{protocol['id']}/content", json=body)
    assert saved.status_code == 200, saved.text
    preview = client.post(f"{base}/{protocol['id']}/preview").json()
    final = client.post(f"{base}/{protocol['id']}/finalize", json={
        "idempotency_key": "move-out-1", "review_hash": preview["review_hash"], "confirmed_content": True,
        "confirmed_signatures": True})
    assert final.status_code == 200, final.text
    return protocol["id"], defect_id


def _settle(client, deposit_id, settlement, items, day="2026-06-30", **extra):
    response = client.put(f"{BASE}/{deposit_id}/settlements/{settlement['id']}", json={
        "base_revision": settlement["revision"], "settlement_date": day, "items": items, **extra})
    assert response.status_code == 200, response.text
    return next(s for s in response.json()["settlements"] if s["id"] == settlement["id"])


def _finalize(client, deposit_id, settlement_id, key="settle-key-1", **extra):
    preview = client.post(f"{BASE}/{deposit_id}/settlements/{settlement_id}/preview").json()
    response = client.post(f"{BASE}/{deposit_id}/settlements/{settlement_id}/finalize", json={
        "idempotency_key": key, "review_hash": preview["review_hash"], "confirmed": True, **extra})
    return preview, response


def _paid_deposit(client, estate, amount=1500):
    detail = _file(client, estate, instalment_count=1, amount=amount)
    deposit_id = detail["deposit"]["id"]
    _receive(client, deposit_id, _book(client, estate, amount, "2024-01-01")["id"])
    return deposit_id


@pytest.mark.parametrize("restricted", [False, True])
def test_settlement_items_cannot_be_moved_from_another_file(client, restricted):
    first, second = _estate("Nord", "N-1"), _estate("Süd", "S-1")
    first_id = _file(client, first)["deposit"]["id"]
    second_id = _file(client, second)["deposit"]["id"]
    first_draft = client.post(f"{BASE}/{first_id}/settlements", json={}).json()["settlements"][0]
    second_draft = client.post(f"{BASE}/{second_id}/settlements", json={}).json()["settlements"][0]
    first_draft = _settle(client, first_id, first_draft, [
        {"kind": "other", "description": "Reinigung", "amount": 90, "reason": "Rechnung 5"}])
    original = first_draft["items"][0]
    writer = (_client(_user("staff", "verwalter", portfolio_access="selected",
                            portfolio_ids=[second["portfolio"].id])) if restricted else client)
    response = writer.put(f"{BASE}/{second_id}/settlements/{second_draft['id']}", json={
        "base_revision": second_draft["revision"], "settlement_date": "2026-06-30",
        "items": [{"id": original["id"], "kind": "other", "description": "Fremde Position",
                   "amount": 1, "reason": "Korrektur"}]})
    assert response.status_code == 409, response.text
    assert client.get(f"{BASE}/{first_id}/file").json()["settlements"][0]["items"] == [original]
    assert client.get(f"{BASE}/{second_id}/file").json()["settlements"][0]["items"] == []


def test_dunning_counts_finalized_deposit_receivable_offsets_once(client):
    estate = _estate()
    deposit_id = _paid_deposit(client, estate, amount=100)
    period = store.create_billing_period(BillingPeriodCreate(
        property_id=estate["property"].id, label="NK 2025", start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31), status="finalized"))
    statement = store.create_utility_statement(UtilityStatementCreate(
        billing_period_id=period.id, contract_id=estate["contract"].id, unit_id=estate["unit"].id,
        total_cost=1500, advance_paid=1000, balance=500, status="finalized"))
    receivable = store.create_receivable(ReceivableCreate(
        contract_id=estate["contract"].id, statement_id=statement.id, due_date=date(2026, 7, 1), amount_due=500))
    _book(client, estate, 21000, "2026-06-01", account="rent_account", text="Miete vollständig")
    draft = client.post(f"{BASE}/{deposit_id}/settlements", json={}).json()["settlements"][0]
    draft = _settle(client, deposit_id, draft, [
        {"kind": "receivable", "description": "Nebenkostennachzahlung", "amount": 100,
         "receivable_id": receivable.id}], day="2026-07-05")

    def outstanding(day):
        response = client.get(f"{API}/dunning/contracts/{estate['contract'].id}", params={"as_of": day})
        assert response.status_code == 200, response.text
        return next(c for c in response.json()["claims"] if c["receivable_id"] == receivable.id)

    assert outstanding("2026-07-10")["outstanding"] == 500     # a draft offset never pays
    assert _finalize(client, deposit_id, draft["id"])[1].status_code == 200
    assert outstanding("2026-07-04")["outstanding"] == 500     # before the dated offset
    claim = outstanding("2026-07-10")
    assert (claim["amount"], claim["paid"], claim["outstanding"]) == (500, 100, 400)


def test_settlement_rejects_duplicate_item_ids_atomically_and_preserves_own_ids(client):
    deposit_id = _file(client, _estate())["deposit"]["id"]
    draft = client.post(f"{BASE}/{deposit_id}/settlements", json={}).json()["settlements"][0]
    item_id = str(uuid.uuid4())
    item = {"id": item_id, "kind": "other", "description": "Reinigung", "amount": 90,
            "reason": "Rechnung 5"}
    draft = _settle(client, deposit_id, draft, [item])
    assert draft["items"][0]["id"] == item_id
    draft = _settle(client, deposit_id, draft, [{**item, "amount": 95}])
    assert draft["items"][0]["id"] == item_id and draft["items"][0]["amount"] == 95
    response = client.put(f"{BASE}/{deposit_id}/settlements/{draft['id']}", json={
        "base_revision": draft["revision"], "settlement_date": "2026-06-30",
        "items": [item, {**item, "description": "Zweite Position", "amount": 10}]})
    assert response.status_code == 400, response.text
    assert client.get(f"{BASE}/{deposit_id}/file").json()["settlements"][0]["items"] == draft["items"]


def test_final_settlement_from_the_move_out_protocol_creates_payout_and_offsets_once(client):
    estate = _estate()
    deposit_id = _paid_deposit(client, estate)
    protocol_id, defect_id = _move_out_protocol(client, estate)
    utility = store.create_receivable(ReceivableCreate(contract_id=estate["contract"].id, due_date=date(2026, 3, 1),
                                                       amount_due=120.5, description="Nachzahlung NK 2025"))
    # rent: everything paid except June 2026 (700)
    for month in range(1, 30):
        year, number = 2024 + (month - 1) // 12, (month - 1) % 12 + 1
        _book(client, estate, 700, f"{year}-{number:02d}-03", account="rent_account", text="Miete")

    created = client.post(f"{BASE}/{deposit_id}/settlements", json={"kind": "final"}).json()
    draft = created["settlements"][0]
    assert created["created"] and draft["handover_protocol_id"] == protocol_id
    assert draft["settlement_date"] == "2026-06-30"
    suggestions = draft["suggestions"]
    assert [d["description"] for d in suggestions["defects"]] == ["Bohrlöcher in der Küchenwand"]   # tenant's only
    assert [(r["id"], r["open"]) for r in suggestions["receivables"]] == [(utility.id, 120.5)]
    assert suggestions["rent_arrears"] == 700.0
    assert any(p["code"] == "defect_open" and not p["blocking"] for p in draft["problems"])

    draft = _settle(client, deposit_id, draft, [
        {"kind": "defect", "description": "Bohrlöcher verschließen", "amount": 80, "handover_defect_id": defect_id},
        {"kind": "receivable", "description": "Nachzahlung NK 2025", "amount": 120.5, "receivable_id": utility.id},
        {"kind": "rent_arrears", "description": "Miete Juni 2026", "amount": 700},
    ])
    # 1500 + 0 interest − 80 − 120.50 − 700 = 599.50
    assert draft["outcome"]["payout"] == "599.50" and draft["outcome"]["result"] == "599.50"
    assert not [p for p in draft["problems"] if p["blocking"]]
    pdf = client.post(f"{BASE}/{deposit_id}/settlements/{draft['id']}/preview-pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")

    preview, response = _finalize(client, deposit_id, draft["id"])
    assert response.status_code == 200, response.text
    done = response.json()
    assert done["stage"] == "settled" and done["deposit"]["status"] == "returned"
    final = done["settlements"][0]
    assert final["finalized"] and final["result_amount"] == 599.5
    assert final["original"]["pdf_sha256"] == preview["pdf_sha256"] == hashlib.sha256(pdf.content).hexdigest()
    payout = store.get_booking(final["payout_booking_id"])
    assert payout.amount == -599.5 and payout.account_id == estate["account"].id
    assert payout.tenant_id == estate["tenant"].id
    assert store.get_receivable(utility.id).status == "paid"
    credit = store.get_booking(final["offset_credit_booking_id"])
    released = store.get_booking(final["offset_booking_id"])
    assert (credit.amount, released.amount) == (700.0, -700.0)
    # the rent account: June is paid by the deposit, payout and release are no rent
    account = client.get(f"{API}/tenants/{estate['tenant'].id}/account", params={"as_of": "2026-07-31"}).json()
    contract_row = account["contracts"][0]
    assert contract_row["outstanding"] == 0.0 and account["totals"]["unassigned"] == 0.0
    # same command again: same result, no second booking; another key: refused
    bookings_before = len(store.list_bookings())
    again = client.post(f"{BASE}/{deposit_id}/settlements/{draft['id']}/finalize", json={
        "idempotency_key": "settle-key-1", "review_hash": preview["review_hash"], "confirmed": True})
    assert again.status_code == 200 and again.json()["settlements"][0]["document_id"] == final["document_id"]
    assert len(store.list_bookings()) == bookings_before
    other = client.post(f"{BASE}/{deposit_id}/settlements/{draft['id']}/finalize", json={
        "idempotency_key": "settle-key-2", "review_hash": preview["review_hash"], "confirmed": True})
    assert other.status_code == 409
    # the original is immutable and verified on every read
    original = client.get(f"{BASE}/{deposit_id}/settlements/{draft['id']}/document")
    assert original.status_code == 200 and hashlib.sha256(original.content).hexdigest() == preview["pdf_sha256"]
    virtual = client.get(final["original"]["file_url"])
    assert virtual.status_code == 200 and virtual.content == original.content
    # nothing of a settled file changes any more
    assert client.put(f"{BASE}/{deposit_id}/settlements/{draft['id']}", json={
        "base_revision": final["revision"], "settlement_date": "2026-06-30", "items": []}).status_code == 409
    assert client.delete(f"{BASE}/{deposit_id}/settlements/{draft['id']}").status_code == 409
    assert client.patch(f"{BASE}/{deposit_id}", json={"amount": 1}).status_code == 409
    assert client.delete(f"{BASE}/{deposit_id}").status_code == 409
    assert client.delete(f"{API}/bookings/{payout.id}").status_code == 409
    assert client.delete(f"{API}/receivables/{utility.id}").status_code == 409
    assert client.patch(f"{API}/bookings/{payout.id}", json={"amount": -1}).status_code == 409
    rates = client.put(f"{BASE}/{deposit_id}/interest-rates", json={"base_revision": done["deposit"]["revision"],
                                                                       "rates": []})
    assert rates.status_code == 409
    if SQL:
        with store.db.get_bind().connect() as connection:
            for statement in ("UPDATE deposit_settlements SET notes = 'x'", "DELETE FROM deposit_payments",
                              "UPDATE deposit_settlement_items SET amount = 1", "UPDATE deposits SET amount = 1",
                              "DELETE FROM deposit_instalments"):
                with pytest.raises(sa.exc.DBAPIError, match="immutable"):
                    with connection.begin():
                        connection.exec_driver_sql(statement)


def test_claims_beyond_the_deposit_become_one_receivable(client):
    estate = _estate()
    deposit_id = _paid_deposit(client, estate, amount=500)
    draft = client.post(f"{BASE}/{deposit_id}/settlements", json={"kind": "final"}).json()["settlements"][0]
    no_reason = _settle(client, deposit_id, draft, [{"kind": "other", "description": "Malerarbeiten", "amount": 650}])
    assert any(p["code"] == "claim_reason" and p["blocking"] for p in no_reason["problems"])
    draft = _settle(client, deposit_id, no_reason, [
        {"kind": "other", "description": "Malerarbeiten", "amount": 650, "reason": "Rechnung Maler Böhm Nr. 77"}])
    assert draft["outcome"]["remaining_claim"] == "150.00"
    response = _finalize(client, deposit_id, draft["id"])[1]
    assert response.status_code == 200, response.text
    final = response.json()["settlements"][0]
    assert final["payout_booking_id"] is None and final["result_amount"] == -150.0
    claim = store.get_receivable(final["claim_receivable_id"])
    assert claim.amount_due == 150.0 and claim.status == "open" and "Restforderung" in (claim.description or "")


def test_retention_for_an_open_utility_period_and_its_later_release(client):
    estate = _estate()
    deposit_id = _paid_deposit(client, estate)
    draft = client.post(f"{BASE}/{deposit_id}/settlements", json={"kind": "final"}).json()["settlements"][0]
    assert draft["suggestions"]["retention_allowed"] and draft["suggestions"]["monthly_advances"] == 200.0
    draft = _settle(client, deposit_id, draft, [
        {"kind": "retention", "description": "Einbehalt NK 2026", "amount": 400,
         "reason": "Abrechnung 2026 steht aus; voraussichtliche Nachzahlung"}])
    assert draft["outcome"]["payout"] == "1100.00" and draft["outcome"]["retention"] == "400.00"
    finished = _finalize(client, deposit_id, draft["id"])[1].json()
    assert finished["stage"] == "retained" and finished["retention"] == 400.0
    assert finished["deposit"]["status"] == "partially_returned"
    assert store.get_booking(finished["settlements"][0]["payout_booking_id"]).amount == -1100.0

    # the utility statement arrives: back-payment 250.40, the rest of the retention is paid out
    store.create_billing_period(BillingPeriodCreate(property_id=estate["property"].id, label="BK 2026",
                                                    start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
                                                    status="finalized"))
    back = store.create_receivable(ReceivableCreate(contract_id=estate["contract"].id, due_date=date(2027, 3, 1),
                                                    amount_due=250.4, description="Nachzahlung NK 2026"))
    release = client.post(f"{BASE}/{deposit_id}/settlements", json={"kind": "retention_release",
                                                                    "settlement_date": "2027-03-15"}).json()
    release = next(s for s in release["settlements"] if s["kind"] == "retention_release")
    bad = client.put(f"{BASE}/{deposit_id}/settlements/{release['id']}", json={
        "base_revision": release["revision"], "settlement_date": "2027-03-15",
        "items": [{"kind": "retention", "description": "noch einmal", "amount": 1, "reason": "x"}]})
    assert bad.status_code == 400
    release = _settle(client, deposit_id, release, [
        {"kind": "receivable", "description": "Nachzahlung NK 2026", "amount": 250.4, "receivable_id": back.id}],
        day="2027-03-15")
    assert release["outcome"]["payout"] == "149.60"
    preview, response = _finalize(client, deposit_id, release["id"], key="release-key-1")
    assert response.status_code == 200, response.text
    closed = response.json()
    assert closed["stage"] == "closed" and closed["deposit"]["status"] == "returned"
    assert store.get_receivable(back.id).status == "paid"
    released = next(s for s in closed["settlements"] if s["kind"] == "retention_release")
    assert store.get_booking(released["payout_booking_id"]).amount == -149.6
    first = next(s for s in closed["settlements"] if s["kind"] == "final")
    assert first["original"]["document_id"] != released["original"]["document_id"]       # an original of its own


def test_no_retention_once_the_utility_statement_is_issued(client):
    estate = _estate()
    store.create_billing_period(BillingPeriodCreate(property_id=estate["property"].id, label="BK 2026",
                                                    start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
                                                    status="finalized"))
    deposit_id = _paid_deposit(client, estate)
    draft = client.post(f"{BASE}/{deposit_id}/settlements", json={"kind": "final"}).json()["settlements"][0]
    assert draft["suggestions"]["retention_allowed"] is False
    draft = _settle(client, deposit_id, draft, [{"kind": "retention", "description": "Einbehalt", "amount": 100,
                                                 "reason": "vorsorglich"}])
    assert any(p["code"] == "retention_not_open" and p["blocking"] for p in draft["problems"])
    assert _finalize(client, deposit_id, draft["id"])[1].status_code == 409


def test_a_guarantee_is_provided_and_released_without_booking(client):
    estate = _estate()
    detail = _file(client, estate, form="guarantee", account_id=None, instalment_count=1,
                   institution="Volksbank", account_reference="Bürgschaft 4711")
    deposit_id = detail["deposit"]["id"]
    assert detail["instalments"] == [] and detail["stage"] == "agreed"
    booking = _book(client, estate, 1500, "2024-01-01")
    assert _receive(client, deposit_id, booking["id"]).status_code == 409
    assert client.post(f"{BASE}/{deposit_id}/settlements", json={"kind": "final"}).status_code == 409
    provided = client.put(f"{BASE}/{deposit_id}/security", json={
        "base_revision": detail["deposit"]["revision"], "provided_on": "2024-01-01"}).json()
    assert provided["stage"] == "provided"
    no_proof = client.put(f"{BASE}/{deposit_id}/security", json={
        "base_revision": provided["deposit"]["revision"], "provided_on": "2024-01-01", "released_on": "2026-07-15"})
    assert no_proof.status_code == 400
    released = client.put(f"{BASE}/{deposit_id}/security", json={
        "base_revision": provided["deposit"]["revision"], "provided_on": "2024-01-01", "released_on": "2026-07-15",
        "release_note": "Bürgschaftsurkunde im Original an die Volksbank zurückgesandt"})
    assert released.status_code == 200 and released.json()["stage"] == "released"
    assert released.json()["deposit"]["status"] == "returned"
    count = len(store.list_bookings())
    assert count == 1 and not store.list_deposit_payments()


# ─── Roles and portfolio boundary ────────────────────────────────────────────

def test_roles(client):
    estate = _estate()
    deposit_id = _paid_deposit(client, estate)
    technician = _client(_user("tom", "techniker"))
    readonly = _client(_user("rita", "readonly"))
    bookkeeper = _client(_user("berta", "buchhaltung"))
    assert technician.get(f"{BASE}/{deposit_id}/file").status_code == 200          # reading is open
    for actor in (technician, readonly):
        assert _agreement(actor, estate).status_code == 403
        assert actor.post(f"{BASE}/{deposit_id}/settlements", json={"kind": "final"}).status_code == 403
    assert _agreement(bookkeeper, estate).status_code == 201
    draft = bookkeeper.post(f"{BASE}/{deposit_id}/settlements", json={"kind": "final"}).json()["settlements"][0]
    assert _finalize(bookkeeper, deposit_id, draft["id"])[1].status_code == 200


def test_a_restricted_account_sees_and_changes_only_deposits_of_its_portfolios(client):
    north, south = _estate("Nord", "N-1"), _estate("Süd", "S-1")
    north_id = _paid_deposit(client, north)
    south_id = _paid_deposit(client, south)
    draft = client.post(f"{BASE}/{south_id}/settlements", json={"kind": "final"}).json()["settlements"][0]
    south_final = _finalize(client, south_id, draft["id"])[1].json()["settlements"][0]
    staff = _client(_user("staff", "verwalter", portfolio_access="selected", portfolio_ids=[north["portfolio"].id]))
    listed = staff.get(f"{BASE}/files").json()
    assert [row["id"] for row in listed["items"]] == [north_id] and listed["total"] == 1
    assert {d["id"] for d in staff.get(BASE).json()} == {north_id}
    for path in (f"{BASE}/{south_id}/file", f"{BASE}/{south_id}", f"{BASE}/{south_id}/payment-candidates",
                 f"{BASE}/{south_id}/settlements/{draft['id']}/document", south_final["original"]["file_url"]):
        assert staff.get(path).status_code == 404, path
    assert staff.get(f"{BASE}/source", params={"contract_id": south["contract"].id}).status_code == 404
    assert _agreement(staff, south).status_code == 404
    assert staff.post(f"{BASE}/{south_id}/settlements", json={"kind": "final"}).status_code == 404
    assert staff.get(f"{BASE}/{north_id}/file").status_code == 200
    # its own portfolio: normal work, but not with a foreign booking
    foreign = _book(client, south, 100, "2024-02-01")
    assert _receive(staff, north_id, foreign["id"]).status_code == 404
    draft = staff.post(f"{BASE}/{north_id}/settlements", json={"kind": "final"}).json()["settlements"][0]
    assert _finalize(staff, north_id, draft["id"])[1].status_code == 200


# ─── Snapshot, data access, plain records ────────────────────────────────────

def test_snapshot_round_trip_and_data_access_export(client):
    estate = _estate()
    deposit_id = _paid_deposit(client, estate)
    client.put(f"{BASE}/{deposit_id}/interest-rates", json={
        "base_revision": client.get(f"{BASE}/{deposit_id}/file").json()["deposit"]["revision"],
        "rates": [{"valid_from": "2024-01-01", "rate_percent": "0.75"}]})
    draft = client.post(f"{BASE}/{deposit_id}/settlements", json={"kind": "final"}).json()["settlements"][0]
    _settle(client, deposit_id, draft, [{"kind": "other", "description": "Reinigung", "amount": 90,
                                         "reason": "Rechnung Nr. 5"}])
    before = client.get(f"{BASE}/{deposit_id}/file").json()
    final = _finalize(client, deposit_id, draft["id"])[1].json()
    data = export_snapshot(store)
    assert data["format_version"] == SNAPSHOT_FORMAT_VERSION >= 7
    assert {len(data[name]) for name in ("deposit_payments", "deposit_settlements", "deposit_settlement_items",
                                         "deposit_interest_rates")} >= {1}
    assert any(o["metadata_snapshot"]["document_type"] == "deposit_settlement" for o in data["document_originals"])

    export = client.get(f"{API}/admin/dsgvo/tenant/{estate['tenant'].id}/export").json()
    assert [d["id"] for d in export["deposits"]] == [deposit_id]
    assert len(export["deposit_payments"]) == 2 and len(export["deposit_settlement_items"]) == 1

    _reset_data()
    import_snapshot(store, data, replace=True)
    restored = client.get(f"{BASE}/{deposit_id}/file").json()
    assert restored["stage"] == "settled" and restored["received"] == before["received"]
    assert restored["settlements"][0]["original"]["pdf_sha256"] == final["settlements"][0]["original"]["pdf_sha256"]
    assert client.get(f"{BASE}/{deposit_id}/settlements/{draft['id']}/document").status_code == 200


def test_plain_records_still_work_and_a_bare_deposit_can_be_deleted(client):
    estate = _estate()
    plain = client.post(BASE, json={"contract_id": estate["contract"].id, "amount": 1000}).json()
    assert plain["form"] == "transfer"
    file = client.get(f"{BASE}/{plain['id']}/file").json()
    assert file["stage"] == "agreed" and file["instalments"] == []
    detail = _file(client, estate)
    assert client.delete(f"{BASE}/{detail['deposit']['id']}").status_code == 204
    assert store.list_deposit_instalments() == []
