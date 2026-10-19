"""Shared financial evidence stays consistent across list, file and suggestions."""

from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from backend.dependencies import store
from backend.maintenance_models import InvoicePaymentCreate
from backend.models import AccountCreate, BookingCreate, InvoiceCreate, PortfolioCreate, PropertyCreate, TenantCreate
from backend.routers import invoices
from backend.services import invoice_overview, maintenance_projects


@pytest.fixture
def finance():
    store.clear_all()
    portfolio = store.create_portfolio(PortfolioCreate(name="Finanzprüfung"))
    account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Bank", account_type="Bankkonto"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="MFH"))
    def invoice(amount=100, **kw):
        return store.create_invoice(InvoiceCreate(supplier="Anbieter", invoice_date=date.today(), net_amount=amount,
                                                  gross_amount=amount, property_id=prop.id, **kw))
    def booking(amount, **kw):
        return store.create_booking(BookingCreate(account_id=account.id, booking_date=date.today(), amount=amount,
                                                  property_id=prop.id, status="open", **kw))
    def pay(invoice, booking, amount):
        return maintenance_projects.add_invoice_payment(store, invoice.id,
            InvoicePaymentCreate(booking_id=booking.id, amount=amount), None)
    return invoice, booking, pay


def test_suggestions_respect_cash_used_by_other_invoices_and_own_remaining_debt(finance):
    invoice, booking, pay = finance
    target, other = invoice(), invoice()
    shared, own, unused = booking(-100), booking(-50), booking(-200)
    pay(other, shared, 80)
    pay(target, own, 30)
    result = invoices.match_invoice_to_bookings(target.id)
    assert result["allocated_total"] == 70
    assert result["unmatched_amount"] == 0
    amounts = {row["booking_id"]: row["allocated_amount"] for row in result["allocations"]}
    assert own.id not in amounts  # a second link of the same booking is forbidden
    assert amounts.get(shared.id, 0) <= 20
    assert set(amounts) <= {shared.id, unused.id}


def test_candidate_pages_are_stable_on_equal_dates_and_omit_already_linked_booking(finance):
    invoice, booking, pay = finance
    target = invoice(1000)
    bookings = [booking(-100) for _ in range(28)]
    pay(target, bookings[9], 10)
    first = maintenance_projects.payment_candidates(store, target.id, limit=25)
    second = maintenance_projects.payment_candidates(store, target.id, skip=25, limit=25)
    ids = [row["id"] for row in first["items"] + second["items"]]
    assert ids == sorted(b.id for b in bookings if b.id != bookings[9].id)
    assert first["has_more"] and not second["has_more"]


def test_overview_does_not_turn_manual_paid_flags_into_payment_evidence(finance):
    invoice, _, _ = finance
    manual = invoice(status="paid")
    row = invoice_overview.overview(store, [manual])[0]
    assert row["status"] == "paid"  # no modification of the legacy record
    assert row["payment_summary"]["paid"] == 0
    assert row["payment_summary"]["open"] is None
    assert "ohne zugeordnete Zahlung" in row["payment_summary"]["note"]


def test_overview_uses_partial_payments_reversals_and_calendar_due_day(finance):
    invoice, booking, pay = finance
    today = date.today()
    target = invoice(due_date=today)
    payment = booking(-100)
    pay(target, payment, 40)
    row = invoice_overview.overview(store, [target], today=today)[0]["payment_summary"]
    assert (row["paid"], row["open"], row["status"], row["overdue"]) == (40, 60, "partial", False)
    assert invoice_overview.overview(store, [target], today=today + timedelta(days=1))[0]["payment_summary"]["status"] == "overdue"
    store.create_booking(BookingCreate(account_id=payment.account_id, property_id=payment.property_id,
                                       booking_date=today, amount=100, reverses_booking_id=payment.id))
    row = invoice_overview.overview(store, [target], today=today)[0]["payment_summary"]
    assert (row["paid"], row["open"], row["status"]) == (0, 100, "open")


def test_cancelled_invoice_has_no_payment_proposal(finance):
    invoice, booking, _ = finance
    target = invoice(status="cancelled")
    booking(-100)
    with pytest.raises(HTTPException) as exc:
        invoices.match_invoice_to_bookings(target.id)
    assert exc.value.status_code == 409


def test_suggestions_never_spend_tenant_money_or_use_a_different_property(finance):
    invoice, booking, _ = finance
    target = invoice()
    tenant = store.create_tenant(TenantCreate(full_name="Partei"))
    tenant_payment = booking(-100, tenant_id=tenant.id)
    other = store.create_property(PropertyCreate(portfolio_id=store.get_property(target.property_id).portfolio_id,
                                                 name="Anderes Haus", property_type="MFH"))
    store.create_booking(BookingCreate(account_id=tenant_payment.account_id, property_id=other.id,
                                       amount=-100, booking_date=date.today(), status="open"))
    result = invoices.match_invoice_to_bookings(target.id)
    assert result["allocations"] == []
    assert result["unmatched_amount"] == 100


def test_invoice_overview_continues_after_the_default_first_hundred_records(finance):
    invoice, _, _ = finance
    expected = {invoice().id for _ in range(101)}
    first = invoices.invoice_overview(skip=0, limit=100)
    second = invoices.invoice_overview(skip=100, limit=100)
    assert len(first) == 100 and len(second) == 1
    assert [i["id"] for i in first + second] == sorted(expected)
    assert all(i["payment_summary"]["open"] == 100 for i in first + second)
