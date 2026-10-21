"""Cash already recorded through the horizon must replace its dated expectation once."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.finance_models import PlannedFlow, ReportDefinition, SettlementCommand
from backend.invoice_review_models import InvoiceReview
from backend.maintenance_models import InvoicePayment
from backend.models import BookingCreate, ContactCreate, InvoiceCreate, PropertyCreate, ReceivableCreate, UnitCreate
from backend.services import finance_reports
from backend.services.maintenance_projects import work
from backend.services.maintenance_rows import Rows
from backend.services.receivable_residuals import allocate, residual
from backend.tests.test_finance_packages_v2 import clean  # noqa: F401
from backend.tests.test_finance_packages_v2 import estate as _estate_fixture  # noqa: F401


@pytest.fixture(name="estate")
def payment_estate(request):
    return request.getfixturevalue("_estate_fixture")


def calculate(**changes):
    return finance_reports.compute(store, ReportDefinition(kind="liquidity-v2", as_of=date(2026, 1, 15),
        months=3, rent_collection_percent=Decimal(0), **changes))


def cash(estate, day, amount, **changes):
    return store.create_booking(BookingCreate(account_id=estate[5].id, property_id=estate[1].id,
        booking_date=date.fromisoformat(day), amount=amount, **changes))


def invoice(estate, **changes):
    return store.create_invoice(InvoiceCreate(property_id=estate[1].id, supplier="Horizontbeleg",
        invoice_date=date(2026, 1, 1), due_date=date(2026, 2, 10), net_amount=100, gross_amount=100, **changes))


def pay_invoice(bill, booking, amount):
    with work(store, None, ()) as unit:
        Rows.of(unit).add("invoice_payments", InvoicePayment(id="horizon-invoice-payment", invoice_id=bill.id,
                                                            booking_id=booking.id, amount=amount))


@pytest.mark.parametrize("day", ["2026-01-10", "2026-02-10", "2026-04-10"])
def test_dated_claim_cash_is_not_expected_a_second_time_and_outside_cash_stays_out(estate, day):
    claim = store.create_receivable(ReceivableCreate(contract_id=estate[4].id, due_date=date(2026, 2, 10), amount_due=100))
    booking = cash(estate, day, 40, tenant_id=estate[3].id, unit_id=estate[2].id)
    effective = max(booking.booking_date, claim.due_date)
    allocate(store, claim.id, SettlementCommand(expected_revision=residual(store, claim)["revision"],
        idempotency_key="horizon-claim-payment", booking_id=booking.id, amount=Decimal(40),
        effective_date=effective, reason="Datiert zugeordnete Teilzahlung"), None)
    result = calculate()
    assert result["closing_balance"] == "1100.00"
    assert all(source.get("day", "") <= "2026-03-31" for source in result["sources"])
    source = next(item for item in result["sources"] if item["identity"] == "receivable:" + claim.id)
    assert "focus_id=" + claim.id in source["url"]


@pytest.mark.parametrize("day", ["2026-01-10", "2026-02-10"])
def test_known_claim_return_restores_the_dated_residual_once(estate, day):
    claim = store.create_receivable(ReceivableCreate(contract_id=estate[4].id, due_date=date(2026, 2, 10), amount_due=100))
    booking = cash(estate, day, 40, tenant_id=estate[3].id, unit_id=estate[2].id)
    allocate(store, claim.id, SettlementCommand(expected_revision=residual(store, claim)["revision"],
        idempotency_key="horizon-claim-return", booking_id=booking.id, amount=Decimal(40),
        effective_date=date(2026, 2, 10), reason="Teilzahlung vor Rücklastschrift"), None)
    cash(estate, "2026-02-20", -10, tenant_id=estate[3].id, unit_id=estate[2].id, reverses_booking_id=booking.id)
    assert calculate()["closing_balance"] == "1100.00"


def test_future_credit_offset_reduces_the_expected_claim_without_creating_cash(estate):
    claim = store.create_receivable(ReceivableCreate(contract_id=estate[4].id, due_date=date(2026, 2, 10), amount_due=100))
    credit = store.create_receivable(ReceivableCreate(contract_id=estate[4].id, due_date=date(2026, 1, 10), amount_due=-40))
    allocate(store, claim.id, SettlementCommand(expected_revision=residual(store, claim)["revision"],
        idempotency_key="horizon-credit-offset", credit_id=credit.id, amount=Decimal(40),
        effective_date=date(2026, 2, 10), reason="Künftige Guthabenverrechnung"), None)
    assert calculate()["closing_balance"] == "1060.00"


@pytest.mark.parametrize("day", ["2026-01-10", "2026-02-10"])
def test_known_supplier_return_restores_the_invoice_residual_once(estate, day):
    bill = invoice(estate)
    booking = cash(estate, day, -40)
    pay_invoice(bill, booking, 40)
    cash(estate, "2026-02-20", 10, reverses_booking_id=booking.id)
    assert calculate()["closing_balance"] == "900.00"


def test_supplier_cash_after_the_horizon_does_not_remove_a_bill_inside_it(estate):
    bill = invoice(estate)
    pay_invoice(bill, cash(estate, "2026-04-10", -100), 100)
    assert calculate()["closing_balance"] == "900.00"


def test_known_eligible_future_skonto_is_not_expected_again_as_an_unpaid_difference(estate):
    bill = invoice(estate)
    with work(store, None, ()) as unit:
        Rows.of(unit).add("invoice_reviews", InvoiceReview(id="horizon-skonto", invoice_id=bill.id,
            received_on=bill.invoice_date, status="approved", approved_amount=100,
            skonto_percent=10, skonto_until=date(2026, 2, 10)))
    pay_invoice(bill, cash(estate, "2026-02-05", -90), 90)
    assert calculate()["closing_balance"] == "910.00"


@pytest.mark.parametrize("day,expected", [("2026-02-05", "920.00"), ("2026-04-05", "900.00")])
def test_approved_credit_note_applies_at_its_document_date_within_the_horizon(estate, day, expected):
    bill = invoice(estate)
    note = store.create_invoice(InvoiceCreate(property_id=estate[1].id, supplier="Lieferantengutschrift",
        invoice_date=date.fromisoformat(day), net_amount=-20, gross_amount=-20))
    with work(store, None, ()) as unit:
        Rows.of(unit).add("invoice_reviews", InvoiceReview(id="horizon-credit-note", invoice_id=note.id,
            kind="credit_note", credit_for_invoice_id=bill.id, received_on=note.invoice_date,
            status="approved", approved_amount=20))
    assert calculate()["closing_balance"] == expected


def test_approved_credit_note_also_reduces_legacy_invoice_costs_once_in_performance(estate):
    bill = invoice(estate)
    note = store.create_invoice(InvoiceCreate(property_id=estate[1].id, supplier="Lieferantengutschrift",
        invoice_date=date(2026, 1, 5), net_amount=-20, gross_amount=-20))
    with work(store, None, ()) as unit:
        Rows.of(unit).add("invoice_reviews", InvoiceReview(id="horizon-performance-credit", invoice_id=note.id,
            kind="credit_note", credit_for_invoice_id=bill.id, received_on=note.invoice_date,
            status="approved", approved_amount=20))
    result = finance_reports.compute(store, ReportDefinition(kind="performance-period-v2", as_of=date(2026, 1, 15)))
    costs = [source for source in result["sources"] if source["contribution"] == "costs"]
    assert result["totals"]["costs"] == "80.00"
    assert sum((Decimal(source["amount"]) for source in costs), Decimal(0)) == Decimal(80)
    assert all(source["identity"] == "invoice:" + bill.id for source in costs)


def service(estate, *, advance_day=10, other_unit=None):
    actor = auth.register_user("horizon-owner", "horizon@example.test", "Horizontprüfung", "Secret123", "eigentuemer")
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(actor.id)})
    provider = store.create_contact(ContactCreate(contact_type="supplier", company_name="Versorgung"))
    locations = [{"property_id": estate[1].id, "unit_id": estate[2].id}]
    if other_unit:
        locations.append({"property_id": other_unit.property_id, "unit_id": other_unit.id})
    response = client.post("/api/v1/service-contracts", json={"contract_type": "electricity", "title": "Abschlagsplan",
        "provider_contact_id": provider.id, "start_date": "2026-01-01", "end_date": "2026-12-31", "locations": locations,
        "tariff": {"valid_from": "2026-01-01", "advance_amount": 30, "advance_interval": "monthly", "advance_day": advance_day}})
    assert response.status_code == 201, response.text
    return client, response.json()["id"]


def pay_service(client, identifier, booking, amount):
    response = client.post(f"/api/v1/service-contracts/{identifier}/payments", json={"booking_id": booking.id, "amount": amount})
    assert response.status_code == 201, response.text


def test_future_partial_advance_after_return_replaces_only_the_effective_paid_share(estate):
    client, identifier = service(estate)
    booking = cash(estate, "2026-02-01", -20)
    pay_service(client, identifier, booking, 20)
    cash(estate, "2026-02-20", 10, reverses_booking_id=booking.id)
    assert calculate()["closing_balance"] == "940.00"  # future Feb/Mar30 each, including net booked10


def test_current_month_prepaid_advance_is_in_opening_and_not_expected_again(estate):
    client, identifier = service(estate, advance_day=20)
    pay_service(client, identifier, cash(estate, "2026-01-01", -30), 30)
    assert calculate()["closing_balance"] == "910.00"  # opening970, no second January, Feb/Mar60


def test_advance_outside_the_horizon_cannot_remove_the_two_expected_instalments(estate):
    client, identifier = service(estate)
    pay_service(client, identifier, cash(estate, "2026-04-01", -30), 30)
    assert calculate()["closing_balance"] == "940.00"


def test_independent_provider_refund_does_not_reduce_a_further_expected_outgoing_advance(estate):
    client, identifier = service(estate)
    pay_service(client, identifier, cash(estate, "2026-02-01", 10), -10)
    assert calculate()["closing_balance"] == "950.00"  # opening1000 + refund10 - Feb/Mar60


def test_multi_property_advance_has_one_global_budget_even_when_cash_names_one_property(estate):
    house = store.create_property(PropertyCreate(portfolio_id=estate[0].id, name="Zweiter Vertragsort", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=house.id, label="Zweiter Zähler", unit_type="residential"))
    client, identifier = service(estate, other_unit=unit)
    pay_service(client, identifier, cash(estate, "2026-02-01", -30), 30)
    complete = calculate()
    first = calculate(property_id=estate[1].id)
    second = calculate(property_id=house.id)
    assert complete["closing_balance"] == "940.00"
    assert first["closing_balance"] == "-45.00" and second["closing_balance"] == "-15.00"
    assert Decimal(first["closing_balance"]) + Decimal(second["closing_balance"]) == Decimal(complete["closing_balance"]) - 1000


def test_explicit_zero_scenario_can_still_replace_an_existing_automatic_expectation(estate):
    definition = ReportDefinition(kind="liquidity-v2", as_of=date(2026, 1, 15), months=3,
        planned_flows=[PlannedFlow(identity="rent:" + estate[4].id + ":2026-02", day=date(2026, 2, 3),
                                   amount=Decimal(0), label="Erwartung bewusst auf Null gesetzt")])
    assert finance_reports.compute(store, definition)["closing_balance"] == "1100.00"


@pytest.mark.parametrize("status", ["paid", "partial"])
def test_opaque_payment_flags_remain_an_explicit_planning_warning(estate, status):
    bill = invoice(estate, status=status)
    result = calculate()
    assert result["closing_balance"] == "900.00"
    assert any(warning["source"] == "invoice:" + bill.id and "Zahlungsnachweis" in warning["message"] for warning in result["warnings"])


def test_evidenced_partial_invoice_is_not_mislabelled_as_an_opaque_status(estate):
    bill = invoice(estate, status="partial")
    pay_invoice(bill, cash(estate, "2026-01-10", -40), 40)
    assert calculate()["closing_balance"] == "900.00" and calculate()["warnings"] == []
