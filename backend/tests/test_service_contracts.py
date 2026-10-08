"""Property service contracts through the API: locations, tariff history, terms, bills, payments,
cost transfer into utility billing, documents, portfolio boundary, deadline reminders, snapshots.

Runs on the memory store and, with TEST_STORE_BACKEND=sql, on SQLite (PostgreSQL in
test_service_contracts_postgres.py). Calendar rules: test_service_contract_terms.py.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import (
    AccountCreate,
    AllocationKeyCreate,
    BillingPeriodCreate,
    BillingPeriodPatch,
    BookingCreate,
    ContactCreate,
    ContractCreate,
    DocumentCreate,
    InvoiceCreate,
    MeterCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)
from backend.permissions import may_write
from backend.services.jobs import service_contract_deadlines as reminders
from backend.services.jobs.core import JobRunner, MemoryJobStore, SqlJobStore

API = "/api/v1/service-contracts"


@pytest.fixture(autouse=True)
def _clean():
    auth.clear_users()
    store.clear_all()
    yield
    auth.clear_users()
    store.clear_all()


@pytest.fixture
def client():
    return TestClient(app)


def _bearer(user) -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token(user.id)}"}


def _owner() -> dict:
    return _bearer(auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer"))


def _staff(name, *portfolios, role="verwalter"):
    return _bearer(auth.register_user(name, f"{name}@example.com", name.title(), "Secret123", role,
                                      portfolio_access="selected", portfolio_ids=[p.id for p in portfolios]))


@pytest.fixture
def estate():
    north = store.create_portfolio(PortfolioCreate(name="Nord"))
    south = store.create_portfolio(PortfolioCreate(name="Süd"))
    house_n = store.create_property(PropertyCreate(portfolio_id=north.id, name="Nordhaus", property_type="residential"))
    house_n2 = store.create_property(PropertyCreate(portfolio_id=north.id, name="Nordhof", property_type="residential"))
    house_s = store.create_property(PropertyCreate(portfolio_id=south.id, name="Südhaus", property_type="residential"))
    unit_n = store.create_unit(UnitCreate(property_id=house_n.id, label="N1", unit_type="residential", area_sqm=60))
    unit_n2 = store.create_unit(UnitCreate(property_id=house_n2.id, label="H1", unit_type="residential", area_sqm=50))
    unit_s = store.create_unit(UnitCreate(property_id=house_s.id, label="S1", unit_type="residential", area_sqm=70))
    meter_n = store.create_meter(MeterCreate(unit_id=unit_n.id, meter_type="electricity", serial_number="Z-4711"))
    meter_s = store.create_meter(MeterCreate(unit_id=unit_s.id, meter_type="electricity", serial_number="Z-0815"))
    provider = store.create_contact(ContactCreate(contact_type="supplier", company_name="Stadtwerke Muster"))
    account = store.create_account(AccountCreate(portfolio_id=north.id, name="Konto Nord", account_type="bank"))
    account_s = store.create_account(AccountCreate(portfolio_id=south.id, name="Konto Süd", account_type="bank"))
    return {"north": north, "south": south, "house_n": house_n, "house_n2": house_n2, "house_s": house_s,
            "unit_n": unit_n, "unit_n2": unit_n2, "unit_s": unit_s, "meter_n": meter_n, "meter_s": meter_s,
            "provider": provider, "account": account, "account_s": account_s}


def _payload(estate, **fields) -> dict:
    """Allgemeinstrom: 24 months from 1.1.2025, then 12 months each, 3 months to the term end."""
    body = {
        "contract_type": "electricity", "title": "Allgemeinstrom Nordhaus", "provider_contact_id": estate["provider"].id,
        "contract_number": "SW-4711", "customer_number": "K-99", "start_date": "2025-01-01",
        "minimum_term_months": 24, "renewal_mode": "fixed", "renewal_months": 12, "notice_period_value": 3,
        "notice_period_unit": "month", "reminder_days": 30,
        "locations": [{"property_id": estate["house_n"].id, "meter_id": estate["meter_n"].id,
                       "supply_point": "DE0001234567890000000000000000001"}],
        "tariff": {"valid_from": "2025-01-01", "label": "Fix 24", "base_price": 12.5,
                   "unit_prices": [{"label": "Arbeitspreis", "unit": "kWh", "price": "0.32470"}],
                   "price_guarantee_until": "2026-12-31", "advance_amount": 100, "advance_interval": "monthly"},
    }
    body.update(fields)
    return body


def _create(client, headers, body) -> dict:
    response = client.post(API, headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _book(account, day, amount, **fields):
    return store.create_booking(BookingCreate(account_id=account.id, booking_date=date.fromisoformat(day),
                                              amount=amount, status="booked", **fields))


# --- master data, locations, tariffs, terms ------------------------------------------------------

def test_a_contract_with_location_tariff_and_its_terms(client, estate):
    owner = _owner()
    created = _create(client, owner, _payload(estate))
    assert created["provider_name"] == "Stadtwerke Muster" and created["restricted"] is False
    [location] = created["locations"]
    assert location["label"] == "Nordhaus / electricity · Z-4711" and location["share_weight"] == 1.0
    [tariff] = created["tariffs"]
    assert tariff["unit_prices"] == [{"label": "Arbeitspreis", "unit": "kWh", "price": "0.3247"}]
    assert tariff["advance_amount"] == 100.0 and tariff["base_price"] == 12.5

    detail = client.get(f"{API}/{created['id']}", headers=owner, params={"as_of": "2026-09-01"}).json()
    terms = detail["terms"]
    assert terms["status"] == "active" and terms["first_term_end"] == "2026-12-31"
    assert terms["current_term"] == {"start": "2025-01-01", "end": "2026-12-31"}
    assert terms["next_notice_deadline"] == {"date": "2026-09-30", "end": "2026-12-31", "days_left": 29,
                                             "renews_to": "2027-12-31"}
    assert terms["earliest_end_if_cancelled_today"] == "2026-12-31"
    assert [(d["kind"], d["date"]) for d in terms["upcoming"]] == [("notice", "2026-09-30"),
                                                                  ("price_guarantee", "2026-12-31")]
    later = client.get(f"{API}/{created['id']}/terms", headers=owner, params={"as_of": "2026-10-01"}).json()
    assert later["next_notice_deadline"]["date"] == "2027-09-30"     # missed: renewed for 12 months

    listed = client.get(API, headers=owner, params={"property_id": estate["house_n"].id, "as_of": "2026-09-01"}).json()
    assert [row["id"] for row in listed] == [created["id"]]
    assert listed[0]["next_deadline"]["kind"] == "notice" and listed[0]["current_advance"] == 100.0
    assert client.get(API, headers=owner, params={"property_id": estate["house_s"].id}).json() == []
    assert len(client.get(API, headers=owner, params={"q": "sw-4711"}).json()) == 1
    assert client.get(API, headers=owner, params={"contract_type": "gas"}).json() == []
    assert len(client.get(API, headers=owner, params={"meter_id": estate["meter_n"].id}).json()) == 1
    overview = client.get(f"{API}/deadlines", headers=owner, params={"as_of": "2026-09-01", "days": 60}).json()
    assert [(d["kind"], d["date"], d["title"]) for d in overview] == [("notice", "2026-09-30", "Allgemeinstrom Nordhaus")]


@pytest.mark.parametrize("change, status_code, message", [
    ({"provider_contact_id": "missing"}, 400, "Anbieter"),
    ({"contract_type": "teleport"}, 422, "Vertragsart"),
    ({"renewal_months": None}, 422, "Verlängerungsdauer"),
    ({"renewal_mode": "indefinite", "minimum_term_months": None}, 422, "Kündigungstermin"),
    ({"locations": []}, 422, ""),
])
def test_contradictions_and_unknown_references_are_refused(client, estate, change, status_code, message):
    response = client.post(API, headers=_owner(), json=_payload(estate, **change))
    assert response.status_code == status_code, response.text
    assert message in response.text
    assert store.list_service_contracts() == []


def test_locations_must_belong_together_and_appear_once(client, estate):
    owner = _owner()
    wrong_unit = _payload(estate, locations=[{"property_id": estate["house_n"].id, "unit_id": estate["unit_s"].id}])
    assert client.post(API, headers=owner, json=wrong_unit).status_code == 400
    wrong_meter = _payload(estate, locations=[{"property_id": estate["house_n"].id, "meter_id": estate["meter_s"].id}])
    assert "Zähler" in client.post(API, headers=owner, json=wrong_meter).json()["error"]["message"]
    twice = _payload(estate, locations=[{"property_id": estate["house_n"].id}, {"property_id": estate["house_n"].id}])
    assert "bereits" in client.post(API, headers=owner, json=twice).json()["error"]["message"]
    assert store.list_service_contracts() == [] and store.list_service_contract_locations() == []

    created = _create(client, owner, _payload(estate))
    added = client.post(f"{API}/{created['id']}/locations", headers=owner,
                        json={"property_id": estate["house_n2"].id, "unit_id": estate["unit_n2"].id, "share_weight": 2})
    assert added.status_code == 201, added.text
    assert len(client.get(f"{API}/{created['id']}/locations", headers=owner).json()) == 2
    first = created["locations"][0]["id"]
    assert client.delete(f"{API}/{created['id']}/locations/{first}", headers=owner).status_code == 204
    last = added.json()["id"]
    refused = client.delete(f"{API}/{created['id']}/locations/{last}", headers=owner)
    assert refused.status_code == 400 and "mindestens einen Standort" in refused.json()["error"]["message"]


def test_tariff_history_by_date(client, estate):
    owner = _owner()
    created = _create(client, owner, _payload(estate))
    contract = created["id"]
    newer = client.post(f"{API}/{contract}/tariffs", headers=owner, json={
        "valid_from": "2026-04-01", "label": "Fix 24 (neu)", "advance_amount": 120, "advance_interval": "monthly",
        "unit_prices": [{"label": "HT", "unit": "kWh", "price": 0.351}, {"label": "NT", "unit": "kWh", "price": "0.2805"}]})
    assert newer.status_code == 201, newer.text
    assert client.post(f"{API}/{contract}/tariffs", headers=owner,
                       json={"valid_from": "2026-04-01"}).status_code == 400          # one tariff per day
    assert client.post(f"{API}/{contract}/tariffs", headers=owner,
                       json={"valid_from": "2024-12-31"}).status_code == 400          # before the contract
    assert client.post(f"{API}/{contract}/tariffs", headers=owner, json={
        "valid_from": "2026-05-01", "unit_prices": [{"label": "AP", "unit": "kWh", "price": "0.1234567"}]}
    ).status_code == 422                                                              # at most six places
    at = lambda day: client.get(f"{API}/{contract}/tariffs/at", headers=owner, params={"date": day})  # noqa: E731
    assert at("2026-03-31").json()["label"] == "Fix 24"
    assert at("2026-04-01").json()["label"] == "Fix 24 (neu)"
    assert at("2026-04-01").json()["unit_prices"][0]["price"] == "0.351"
    assert at("2024-12-31").status_code == 404
    instalments = client.get(f"{API}/{contract}/instalments", headers=owner,
                             params={"date_from": "2026-01-01", "date_to": "2026-12-31"}).json()
    assert instalments["total"] == 3 * 100 + 9 * 120
    tariff_id = newer.json()["id"]
    changed = client.put(f"{API}/{contract}/tariffs/{tariff_id}", headers=owner,
                         json={"valid_from": "2026-07-01", "advance_amount": 110, "advance_interval": "monthly"})
    assert changed.status_code == 200 and at("2026-06-30").json()["label"] == "Fix 24"
    assert client.delete(f"{API}/{contract}/tariffs/{tariff_id}", headers=owner).status_code == 204
    assert len(client.get(f"{API}/{contract}/tariffs", headers=owner).json()) == 1


def test_cancellation_takes_effect_at_the_earliest_end_unless_extraordinary(client, estate):
    owner = _owner()
    contract = _create(client, owner, _payload(estate))["id"]
    cancelled = client.post(f"{API}/{contract}/cancel", headers=owner, json={"cancelled_on": "2026-09-30"})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["cancellation_effective"] == "2026-12-31"
    terms = client.get(f"{API}/{contract}/terms", headers=owner, params={"as_of": "2026-10-01"}).json()
    assert terms["status"] == "cancelled" and terms["next_notice_deadline"] is None
    assert [d["kind"] for d in terms["upcoming"]] == ["contract_end"]     # the guarantee ends with the contract
    late = client.post(f"{API}/{contract}/cancel", headers=owner, json={"cancelled_on": "2026-10-01"})
    assert late.json()["cancellation_effective"] == "2027-12-31"           # one day late: renewed
    early = client.post(f"{API}/{contract}/cancel", headers=owner,
                        json={"cancelled_on": "2026-10-01", "effective_date": "2026-11-30"})
    assert early.status_code == 400 and "frühestens zum 31.12.2027" in early.json()["error"]["message"]
    special = client.post(f"{API}/{contract}/cancel", headers=owner, params={"extraordinary": "true"},
                          json={"cancelled_on": "2026-10-01", "effective_date": "2026-11-30"})
    assert special.status_code == 200 and special.json()["cancellation_effective"] == "2026-11-30"
    withdrawn = client.delete(f"{API}/{contract}/cancel", headers=owner).json()
    assert withdrawn["cancelled_on"] is None and withdrawn["cancellation_effective"] is None


def test_put_keeps_the_rules_and_reports_a_stale_edit(client, estate):
    owner = _owner()
    created = _create(client, owner, _payload(estate))
    body = {k: v for k, v in _payload(estate).items() if k not in ("locations", "tariff")}
    renamed = client.put(f"{API}/{created['id']}", headers=owner,
                         json={**body, "title": "Allgemeinstrom", "updated_at": created["updated_at"]})
    assert renamed.status_code == 200, renamed.text
    stale = client.put(f"{API}/{created['id']}", headers=owner,
                       json={**body, "title": "Überholt", "updated_at": created["updated_at"]})
    assert stale.status_code == 409
    later_start = client.put(f"{API}/{created['id']}", headers=owner, json={**body, "start_date": "2025-06-01"})
    assert later_start.status_code == 400 and "Tarife vor dem neuen Vertragsbeginn" in later_start.json()["error"]["message"]


# --- expectation, bills, payments ----------------------------------------------------------------

def _yearly_contract(client, headers, estate, **fields) -> str:
    """One year from 1.1.2026, no renewal; advances of 100 a month."""
    body = _payload(estate, start_date="2026-01-01", minimum_term_months=12, renewal_mode="none", **fields)
    body["tariff"] = {"valid_from": "2026-01-01", "advance_amount": 100, "advance_interval": "monthly"}
    return _create(client, headers, body)["id"]


def test_expectation_bill_and_payment_count_once(client, estate):
    owner = _owner()
    contract = _yearly_contract(client, owner, estate)
    for month in range(1, 13):
        booking = _book(estate["account"], f"2026-{month:02d}-02", -100.0, payment_text="Abschlag SW-4711")
        assert client.post(f"{API}/{contract}/payments", headers=owner,
                           json={"booking_id": booking.id}).status_code == 201
    settlement = client.post(f"{API}/{contract}/invoices", headers=owner, json={
        "kind": "settlement", "period_start": "2026-01-01", "period_end": "2026-12-31", "advances_credited": 1200,
        "consumption": 4321.5, "consumption_unit": "kWh",
        "invoice": {"property_id": estate["house_n"].id, "supplier": "Stadtwerke Muster", "invoice_date": "2027-02-10",
                    "net_amount": 1134.45, "vat_amount": 215.55, "gross_amount": 1350.0}})
    assert settlement.status_code == 201, settlement.text
    bill = settlement.json()
    assert (bill["balance"], bill["planned_advances"], bill["open"]) == (150.0, 1200.0, 150.0)
    rest = _book(estate["account"], "2027-02-20", -150.0, payment_text="Nachzahlung SW-4711")
    paid = client.post(f"{API}/{contract}/payments", headers=owner,
                       json={"booking_id": rest.id, "service_contract_invoice_id": bill["id"]})
    assert paid.status_code == 201, paid.text

    def window(start, end):
        return client.get(f"{API}/{contract}/reconciliation", headers=owner,
                          params={"date_from": start, "date_to": end}).json()

    y2026, y2027, both = window("2026-01-01", "2026-12-31"), window("2027-01-01", "2027-12-31"), \
        window("2026-01-01", "2027-12-31")
    assert (y2026["expected"], y2026["invoiced"], y2026["paid"], y2026["open"], y2026["costs"]) == (
        1200.0, 0.0, 1200.0, 0.0, 1350.0)
    assert (y2027["expected"], y2027["invoiced"], y2027["credited"], y2027["invoice_balance"], y2027["paid"],
            y2027["open"], y2027["costs"]) == (0.0, 1350.0, 1200.0, 150.0, 150.0, 0.0, 0.0)
    assert both["obligations"] == both["costs"] == both["paid"] == 1350.0 and both["open"] == 0.0
    assert client.get(f"{API}/{contract}/invoices", headers=owner).json()[0]["open"] == 0.0

    # a bill belongs to one contract, a booking is allocated once per contract and never beyond its amount
    other = _yearly_contract(client, owner, estate, title="Zweitvertrag")
    taken = client.post(f"{API}/{other}/invoices", headers=owner, json={
        "invoice_id": bill["invoice"]["id"], "period_start": "2026-01-01", "period_end": "2026-12-31"})
    assert taken.status_code == 400 and "bereits" in taken.json()["error"]["message"]
    assert client.post(f"{API}/{contract}/payments", headers=owner, json={"booking_id": rest.id}).status_code == 400
    assert client.post(f"{API}/{other}/payments", headers=owner, json={"booking_id": rest.id}).status_code == 400
    split = _book(estate["account"], "2026-03-02", -80.0)
    assert client.post(f"{API}/{other}/payments", headers=owner,
                       json={"booking_id": split.id, "amount": 50}).status_code == 201
    assert "Höchstens 30.00" in client.post(f"{API}/{contract}/payments", headers=owner,
                                            json={"booking_id": split.id, "amount": 40}).json()["error"]["message"]
    assert client.post(f"{API}/{contract}/payments", headers=owner,
                       json={"booking_id": split.id, "amount": -30}).status_code == 400   # wrong direction
    assert client.post(f"{API}/{contract}/payments", headers=owner, json={"booking_id": split.id}).json()["amount"] == 30
    # a linked bill cannot be deleted from the invoice list
    refused = client.delete(f"/api/v1/invoices/{bill['invoice']['id']}", headers=owner)
    assert refused.status_code == 409 and "Objektvertrag" in refused.json()["error"]["message"]
    # deleting a booking removes its allocation (as with rent allocations)
    store.delete_booking(rest.id)
    assert window("2027-01-01", "2027-12-31")["paid"] == 0.0


def test_refunds_tenant_money_and_candidates(client, estate):
    owner = _owner()
    contract = _yearly_contract(client, owner, estate)
    refund = _book(estate["account"], "2026-03-05", 25.0, payment_text="Gutschrift Stadtwerke")
    assert client.post(f"{API}/{contract}/payments", headers=owner,
                       json={"booking_id": refund.id}).json()["amount"] == -25.0
    tenant = store.create_tenant(TenantCreate(full_name="Mia Muster"))
    store.create_contract(ContractCreate(contract_number="M-1", property_id=estate["house_n"].id,
                                         unit_id=estate["unit_n"].id, tenant_id=tenant.id,
                                         start_date=date(2025, 1, 1)))
    rent = _book(estate["account"], "2026-03-03", 700.0, tenant_id=tenant.id)
    refused = client.post(f"{API}/{contract}/payments", headers=owner, json={"booking_id": rent.id})
    assert refused.status_code == 400 and "Mieterzahlung" in refused.json()["error"]["message"]
    match = _book(estate["account"], "2026-04-02", -100.0, payment_text="Lastschrift SW-4711 Stadtwerke")
    plain = _book(estate["account"], "2026-04-03", -100.0, payment_text="Hausmeister")
    found = client.get(f"{API}/{contract}/payment-candidates", headers=owner,
                       params={"date_from": "2026-03-01", "date_to": "2026-04-30"}).json()
    ids = [item["booking_id"] for item in found["items"]]
    assert ids[0] == match.id and plain.id in ids and rent.id not in ids and refund.id not in ids
    assert found["items"][0]["reasons"] == ["number", "provider", "advance"]


# --- utility billing -----------------------------------------------------------------------------

def _period(estate, house, label="BK 2026", start="2026-01-01", end="2026-12-31"):
    period = store.create_billing_period(BillingPeriodCreate(property_id=estate[house].id, label=label,
                                                             start_date=date.fromisoformat(start),
                                                             end_date=date.fromisoformat(end)))
    key = store.create_allocation_key(AllocationKeyCreate(property_id=estate[house].id, name="Fläche",
                                                          key_type="area_sqm"))
    return period, key


def _caretaker(client, headers, estate, **fields) -> str:
    body = _payload(estate, contract_type="caretaker", title="Hauswart Nord", start_date="2025-01-01",
                    minimum_term_months=None, renewal_mode="indefinite", renewal_months=None, notice_to="quarter_end",
                    recoverable=True, cost_category="hauswart", tariff=None,
                    locations=[{"property_id": estate["house_n"].id, "share_weight": 2},
                               {"property_id": estate["house_n2"].id, "share_weight": 1}])
    body.update(fields)
    return _create(client, headers, body)["id"]


def _bill(client, headers, estate, contract, gross, start="2026-01-01", end="2026-12-31", day="2027-01-15"):
    response = client.post(f"{API}/{contract}/invoices", headers=headers, json={
        "period_start": start, "period_end": end,
        "invoice": {"supplier": "Hauswart Meier", "invoice_date": day, "net_amount": gross, "vat_amount": 0,
                    "vat_rate": 0, "gross_amount": gross, "invoice_number": f"R-{gross}"}})
    assert response.status_code == 201, response.text
    return response.json()


def test_recoverable_bills_enter_each_billing_period_once(client, estate):
    owner = _owner()
    contract = _caretaker(client, owner, estate)
    bill = _bill(client, owner, estate, contract, 300.0)
    period_a, key_a = _period(estate, "house_n")
    period_b, key_b = _period(estate, "house_n2")

    first = client.post(f"{API}/{contract}/cost-transfers", headers=owner,
                        json={"billing_period_id": period_a.id, "allocation_key_id": key_a.id})
    assert first.status_code == 201, first.text
    [item] = first.json()["created"]
    assert item["amount"] == 200.0 and item["service_contract_invoice_id"] == bill["id"]
    assert item["is_recoverable"] and item["cost_category"] == "hauswart"
    assert "Hauswart Nord: Rechnung R-300.0" in item["description"]
    again = client.post(f"{API}/{contract}/cost-transfers", headers=owner,
                        json={"billing_period_id": period_a.id, "allocation_key_id": key_a.id}).json()
    assert again == {"created": [], "skipped": [{"service_contract_invoice_id": bill["id"],
                                                 "reason": "already_transferred"}]}
    other = client.post(f"{API}/{contract}/cost-transfers", headers=owner,
                        json={"billing_period_id": period_b.id, "allocation_key_id": key_b.id}).json()
    assert [c["amount"] for c in other["created"]] == [100.0]          # 2 : 1, the parts add up to the bill
    assert sorted(t["amount"] for t in client.get(f"{API}/{contract}/cost-transfers", headers=owner).json()) == [
        100.0, 200.0]
    wrong_key = client.post(f"{API}/{contract}/cost-transfers", headers=owner,
                            json={"billing_period_id": period_a.id, "allocation_key_id": key_b.id})
    assert wrong_key.status_code == 400

    # the bill stays while a statement uses it; editing the cost item keeps its origin
    refused = client.delete(f"{API}/{contract}/invoices/{bill['id']}", headers=owner)
    assert refused.status_code == 409 and "BK 2026" in refused.json()["error"]["message"]
    edited = client.put(f"/api/v1/billing/cost-items/{item['id']}", headers=owner, json={
        "billing_period_id": period_a.id, "description": "Hauswart", "amount": 199.0, "allocation_key_id": key_a.id})
    assert edited.status_code == 200 and edited.json()["service_contract_invoice_id"] == bill["id"]
    duplicate = client.post("/api/v1/billing/cost-items", headers=owner, json={
        "billing_period_id": period_a.id, "description": "x", "amount": 1, "allocation_key_id": key_a.id,
        "service_contract_invoice_id": bill["id"]})
    assert duplicate.status_code == 400

    # a finalized period takes nothing more; its correction starts with the copy, which keeps the origin
    store._patch_entity("billing_period", period_a.id, BillingPeriodPatch(status="finalized"))
    late = _bill(client, owner, estate, contract, 30.0, day="2027-02-01")
    closed = client.post(f"{API}/{contract}/cost-transfers", headers=owner,
                         json={"billing_period_id": period_a.id, "allocation_key_id": key_a.id})
    assert closed.status_code == 409
    revision = client.post(f"/api/v1/billing/periods/{period_a.id}/revisions", headers=owner)
    assert revision.status_code == 200, revision.text
    correction = revision.json()["new_period_id"]
    into_correction = client.post(f"{API}/{contract}/cost-transfers", headers=owner,
                                  json={"billing_period_id": correction, "allocation_key_id": key_a.id}).json()
    assert [c["amount"] for c in into_correction["created"]] == [20.0]       # only the new bill
    assert {s["service_contract_invoice_id"] for s in into_correction["skipped"]} == {bill["id"]}
    assert late["id"] in {c["service_contract_invoice_id"] for c in into_correction["created"]}


def test_transfer_needs_recoverable_contracts_and_prorates_the_service_period(client, estate):
    owner = _owner()
    plain = _caretaker(client, owner, estate, recoverable=False, title="Wartung")
    period, key = _period(estate, "house_n")
    refused = client.post(f"{API}/{plain}/cost-transfers", headers=owner,
                          json={"billing_period_id": period.id, "allocation_key_id": key.id})
    assert refused.status_code == 400 and "umlagefähig" in refused.json()["error"]["message"]
    partly = _caretaker(client, owner, estate, title="Hauswart 80 %", recoverable_percent=80,
                        locations=[{"property_id": estate["house_n"].id}])
    _bill(client, owner, estate, partly, 365.0, start="2025-07-01", end="2026-06-30", day="2026-07-10")
    created = client.post(f"{API}/{partly}/cost-transfers", headers=owner,
                          json={"billing_period_id": period.id, "allocation_key_id": key.id}).json()["created"]
    # 181 of 365 service days fall into 2026: 181.00, of which 80 % are recoverable
    assert [c["amount"] for c in created] == [144.8]
    assert "01.01.2026–30.06.2026" in created[0]["description"] and "80 % umlagefähig" in created[0]["description"]
    outside = _period(estate, "house_n2")
    assert client.post(f"{API}/{partly}/cost-transfers", headers=owner,
                       json={"billing_period_id": outside[0].id, "allocation_key_id": outside[1].id}
                       ).status_code == 400                           # not a location of this contract


# --- documents, deletion -------------------------------------------------------------------------

def test_documents_of_the_contract_and_its_bills(client, estate):
    owner = _owner()
    contract = _caretaker(client, owner, estate)
    offer = store.create_document(DocumentCreate(property_id=estate["house_n"].id, title="Vertrag Hauswart",
                                                 document_type="service_contract", file_url="/uploads/documents/hw.pdf"))
    scan = store.create_document(DocumentCreate(property_id=estate["house_n"].id, title="Rechnung 2026",
                                                document_type="invoice", file_url="/uploads/documents/r.pdf"))
    bill = _bill(client, owner, estate, contract, 300.0)
    store.update_invoice(bill["invoice"]["id"], InvoiceCreate(
        property_id=None, supplier="Hauswart Meier", invoice_date=date(2027, 1, 15), net_amount=300.0,
        gross_amount=300.0, vat_rate=0, vat_amount=0))
    if hasattr(store, "db"):
        from backend.db.orm_models import InvoiceORM

        store.db.get(InvoiceORM, bill["invoice"]["id"]).source_document_id = scan.id
        store.db.commit()
    else:
        store.invoices[bill["invoice"]["id"]] = store.invoices[bill["invoice"]["id"]].model_copy(
            update={"source_document_id": scan.id})
    linked = client.post(f"{API}/{contract}/documents", headers=owner, json={"document_id": offer.id})
    assert linked.status_code == 201, linked.text
    assert client.post(f"{API}/{contract}/documents", headers=owner, json={"document_id": offer.id}).status_code == 400
    rows = client.get(f"{API}/{contract}/documents", headers=owner).json()
    assert [(r["title"], r["source"]) for r in rows] == [("Vertrag Hauswart", "contract"), ("Rechnung 2026", "invoice")]
    store.delete_document(offer.id)
    assert [r["title"] for r in client.get(f"{API}/{contract}/documents", headers=owner).json()] == ["Rechnung 2026"]


def test_what_a_contract_uses_is_not_deleted_from_under_it(client, estate):
    owner = _owner()
    contract = _yearly_contract(client, owner, estate)
    in_use = client.delete(f"/api/v1/properties/{estate['house_n'].id}", headers=owner)
    assert in_use.status_code == 409 and "Objektvertragsstandort" in in_use.json()["error"]["message"]
    assert "Objektvertrag" in client.delete(f"/api/v1/contacts/{estate['provider'].id}", headers=owner).json()["error"]["message"]
    booking = _book(estate["account"], "2026-01-02", -100.0)
    client.post(f"{API}/{contract}/payments", headers=owner, json={"booking_id": booking.id})
    refused = client.delete(f"{API}/{contract}", headers=owner)
    assert refused.status_code == 409 and "kündigen" in refused.json()["error"]["message"]
    empty = _yearly_contract(client, owner, estate, title="Leer")
    assert client.delete(f"{API}/{empty}", headers=owner).status_code == 204
    assert store.list_service_contract_locations(service_contract_id=empty) == []
    assert store.list_service_contract_tariffs(service_contract_id=empty) == []
    store.delete_meter(estate["meter_n"].id)          # the location stays, at property level
    assert [loc.meter_id for loc in store.list_service_contract_locations(contract)] == [None]


def test_bookkeeping_changes_money_but_not_the_contract():
    assert may_write("buchhaltung", "/service-contracts/abc/payments")
    assert may_write("buchhaltung", "/service-contracts/abc/invoices/def")
    assert may_write("buchhaltung", "/service-contracts/abc/cost-transfers")
    assert not may_write("buchhaltung", "/service-contracts")
    assert not may_write("buchhaltung", "/service-contracts/abc")
    assert not may_write("buchhaltung", "/service-contracts/abc/tariffs")
    assert not may_write("techniker", "/service-contracts/abc/payments")
    assert may_write("verwalter", "/service-contracts/abc/tariffs")


# --- portfolio boundary --------------------------------------------------------------------------

def test_a_contract_is_visible_through_any_location_and_changed_only_with_all(client, estate):
    owner = _owner()
    shared = _create(client, owner, _payload(estate, title="Gemeinsamer Hauswart", locations=[
        {"property_id": estate["house_n"].id}, {"property_id": estate["house_s"].id, "meter_id": estate["meter_s"].id}]))
    north_only = _create(client, owner, _payload(estate, title="Strom Nord"))
    south_only = _create(client, owner, _payload(estate, title="Strom Süd", locations=[
        {"property_id": estate["house_s"].id}]))
    staff = _staff("nora", estate["north"])

    listed = client.get(API, headers=staff).json()
    assert {row["title"] for row in listed} == {"Gemeinsamer Hauswart", "Strom Nord"}
    row = next(r for r in listed if r["id"] == shared["id"])
    assert [loc["property_id"] for loc in row["locations"]] == [estate["house_n"].id]   # other location rows hidden
    assert "Südhaus" not in str(listed) and "Z-0815" not in str(listed)
    detail = client.get(f"{API}/{shared['id']}", headers=staff).json()
    assert detail["restricted"] is True and len(detail["locations"]) == 1
    assert client.get(f"{API}/{south_only['id']}", headers=staff).status_code == 404
    assert client.get(f"{API}/{south_only['id']}/tariffs", headers=staff).status_code == 404
    assert client.get(f"{API}/{shared['id']}/reconciliation", headers=staff).json()["partial"] is True

    body = {k: v for k, v in _payload(estate).items() if k not in ("locations", "tariff")}
    assert client.put(f"{API}/{shared['id']}", headers=staff, json={**body, "title": "Übernommen"}).status_code == 403
    assert client.post(f"{API}/{shared['id']}/tariffs", headers=staff,
                       json={"valid_from": "2026-01-01"}).status_code == 403
    north_location = detail["locations"][0]["id"]
    assert client.delete(f"{API}/{shared['id']}/locations/{north_location}", headers=staff).status_code == 403
    booking = _book(estate["account"], "2026-01-02", -100.0)
    assert client.post(f"{API}/{shared['id']}/payments", headers=staff,
                       json={"booking_id": booking.id}).status_code == 403
    assert client.post(f"{API}/{shared['id']}/cancel", headers=staff,
                       json={"cancelled_on": "2026-09-01"}).status_code == 403
    assert client.delete(f"{API}/{shared['id']}", headers=staff).status_code == 403
    assert store.get_service_contract(shared["id"]).title == "Gemeinsamer Hauswart"
    assert len(store.list_service_contract_locations(shared["id"])) == 2

    # inside its own portfolio the account works normally
    renamed = client.put(f"{API}/{north_only['id']}", headers=staff, json={**body, "title": "Strom Nordhaus"})
    assert renamed.status_code == 200, renamed.text
    assert client.post(f"{API}/{north_only['id']}/tariffs", headers=staff,
                       json={"valid_from": "2026-01-01"}).status_code == 201
    assert client.post(f"{API}/{north_only['id']}/payments", headers=staff,
                       json={"booking_id": booking.id}).status_code == 201
    moved = client.post(f"{API}/{north_only['id']}/locations", headers=staff,
                        json={"property_id": estate["house_s"].id})
    assert moved.status_code in (400, 403, 404)
    assert len(store.list_service_contract_locations(north_only["id"])) == 1


def test_a_restricted_account_creates_contracts_with_shared_providers_inside_its_portfolios(client, estate):
    staff = _staff("nora", estate["north"])
    created = client.post(API, headers=staff, json=_payload(estate))     # provider from the shared address book
    assert created.status_code == 201, created.text
    assert created.json()["restricted"] is False
    assert [r["id"] for r in client.get(API, headers=staff).json()] == [created.json()["id"]]
    outside = client.post(API, headers=staff, json=_payload(estate, title="Fremd", locations=[
        {"property_id": estate["house_n"].id}, {"property_id": estate["house_s"].id}]))
    assert outside.status_code in (400, 403)
    assert {c.title for c in store.list_service_contracts()} == {"Allgemeinstrom Nordhaus"}
    assert len(store.list_service_contract_locations()) == 1
    nobody = _staff("nobody")
    assert client.post(API, headers=nobody, json=_payload(estate)).status_code in (400, 403)


# --- reminders -----------------------------------------------------------------------------------

def _job_store():
    if hasattr(store, "db"):
        from backend.db.session import engine

        return SqlJobStore(engine)
    return MemoryJobStore(store_factory=lambda: store)


def _run_reminders(jobs, as_of: str):
    jobs.enqueue(reminders.KIND, f"{reminders.KIND}@{as_of}", {"as_of": as_of})
    return JobRunner(jobs, {reminders.KIND: reminders.make_handler(chunk=1)}).run_until_idle()


def _reminder_tasks():
    return sorted((t.title, str(t.due_date)) for t in store.list_tasks())


def test_deadline_reminders_are_created_once_per_contract_and_deadline(client, estate):
    owner = _owner()
    allgemein = _create(client, owner, _payload(estate))                         # notice deadline 30.09.2026
    _create(client, owner, _payload(estate, title="Müllabfuhr", contract_type="waste", tariff=None,
                                    minimum_term_months=None, renewal_mode="none", renewal_months=None,
                                    notice_period_value=None, notice_period_unit=None, end_date="2026-10-01"))
    _create(client, owner, _payload(estate, title="Strom Süd", reminder_days=10,
                                    locations=[{"property_id": estate["house_s"].id}]))
    if hasattr(store, "db"):
        store.db.commit()
    jobs = _job_store()

    runs = _run_reminders(jobs, "2026-09-05")
    assert [run.status for run in runs] == ["succeeded"] and runs[0].progress["contracts"] == 3
    assert _reminder_tasks() == [("Kündigungsfrist: Allgemeinstrom Nordhaus", "2026-09-30"),
                                 ("Vertragsende: Müllabfuhr", "2026-10-01")]
    notes = [n for n in store.list_notifications() if n.notification_type == "service_contract_deadline"]
    assert len(notes) == 2 and {n.entity_type for n in notes} == {"service_contract"}
    assert "bis 30.09.2026 bei Stadtwerke Muster eingehen" in next(n.content for n in notes if "Kündigung" in n.title)
    task = next(t for t in store.list_tasks() if t.title.startswith("Kündigungsfrist"))
    assert task.property_id == estate["house_n"].id and task.priority == "high"

    _run_reminders(jobs, "2026-09-05")        # the same slot: the run exists, nothing new
    _run_reminders(jobs, "2026-09-06")        # the next day: already reminded
    _run_reminders(jobs, "2026-09-21")        # Strom Süd enters its 10-day window
    assert len(_reminder_tasks()) == 3
    # a changed notice period is a new deadline: reminded once more
    body = {k: v for k, v in _payload(estate).items() if k not in ("locations", "tariff")}
    assert client.put(f"{API}/{allgemein['id']}", headers=owner,
                      json={**body, "notice_period_value": 2}).status_code == 200
    _run_reminders(jobs, "2026-10-05")
    _run_reminders(jobs, "2026-10-06")
    assert ("Kündigungsfrist: Allgemeinstrom Nordhaus", "2026-10-31") in _reminder_tasks()
    assert len(_reminder_tasks()) == 4

    # what a restricted account is shown of it: only its portfolios
    staff = _staff("nora", estate["north"])
    shown = client.get("/api/v1/notifications", headers=staff).json()
    assert {n["title"] for n in shown} == {"Kündigungsfrist: Allgemeinstrom Nordhaus", "Vertragsende: Müllabfuhr"}


# --- snapshot ------------------------------------------------------------------------------------

def test_snapshots_carry_contracts_and_the_origin_of_transferred_costs(client, estate):
    from backend.services.data_snapshot import export_snapshot, import_snapshot

    owner = _owner()
    contract = _caretaker(client, owner, estate)
    _bill(client, owner, estate, contract, 300.0)
    period, key = _period(estate, "house_n")
    client.post(f"{API}/{contract}/cost-transfers", headers=owner,
                json={"billing_period_id": period.id, "allocation_key_id": key.id})
    client.post(f"{API}/{contract}/payments", headers=owner,
                json={"booking_id": _book(estate["account"], "2027-01-20", -300.0).id})
    snapshot = export_snapshot(store)
    assert snapshot["format_version"] == 4
    counts = {key: len(snapshot[key]) for key in ("service_contracts", "service_contract_locations",
                                                  "service_contract_invoices", "service_contract_payments")}
    assert counts == {"service_contracts": 1, "service_contract_locations": 2, "service_contract_invoices": 1,
                      "service_contract_payments": 1}
    assert [c["service_contract_invoice_id"] for c in snapshot["cost_items"]] == [
        snapshot["service_contract_invoices"][0]["id"]]
    import_snapshot(store, snapshot, replace=True)
    assert len(store.list_service_contract_locations()) == 2
    assert client.get(f"{API}/{contract}/reconciliation", headers=owner,
                      params={"date_from": "2027-01-01", "date_to": "2027-12-31"}).json()["paid"] == 300.0
    again = client.post(f"{API}/{contract}/cost-transfers", headers=owner,
                        json={"billing_period_id": period.id, "allocation_key_id": key.id}).json()
    assert again["created"] == []


def test_no_service_contract_read_opens_another_portfolio(client, estate):
    """Every GET under /service-contracts with the other portfolio's contract, bill and location IDs."""
    import re

    from fastapi.routing import APIRoute

    owner = _owner()
    south = _create(client, owner, _payload(estate, title="SUEDGEHEIM", contract_number="SUED-1",
                                            locations=[{"property_id": estate["house_s"].id}]))
    bill = client.post(f"{API}/{south['id']}/invoices", headers=owner, json={
        "period_start": "2026-01-01", "period_end": "2026-12-31",
        "invoice": {"property_id": estate["house_s"].id, "supplier": "SUEDGEHEIM AG", "invoice_date": "2026-05-01",
                    "net_amount": 10, "gross_amount": 10}}).json()
    shared = _create(client, owner, _payload(estate, title="Gemeinsam", locations=[
        {"property_id": estate["house_n"].id}, {"property_id": estate["house_s"].id, "supply_point": "SUEDGEHEIM"}]))
    hidden_location = next(loc["id"] for loc in shared["locations"] if loc["property_id"] == estate["house_s"].id)
    staff = _staff("nora", estate["north"])
    ids = [south["id"], bill["id"], south["tariffs"][0]["id"], south["locations"][0]["id"], hidden_location]
    opened, tried = [], 0
    for route in app.routes:
        if not isinstance(route, APIRoute) or "GET" not in route.methods or not route.path.startswith(API):
            continue
        for value in ids:
            path = re.sub(r"{\w+}", value, route.path)
            response = client.get(path, headers=staff, params={"date": "2026-06-01"})
            tried += 1
            if response.status_code >= 500 or (response.status_code < 300 and (
                    "SUEDGEHEIM" in response.text or estate["house_s"].id in response.text)):
                opened.append(f"{path}: {response.status_code}")
    assert not opened, opened
    assert tried >= 60
    assert "SUEDGEHEIM" in client.get(API, headers=owner).text
