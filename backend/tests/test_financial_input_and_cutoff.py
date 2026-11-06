"""Request amounts and dated settlement totals must agree on memory and SQLite."""
import math
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db import schema_state
from backend.domain.money import money_sum
from backend.finance_models import SettlementCommand
from backend.invoice_review_models import InvoiceReview
from backend.maintenance_models import InvoicePayment
from backend.models import (
    AccountCreate,
    BookingCreate,
    ContractCreate,
    InvoiceCreate,
    MeterCreate,
    MeterReadingCreate,
    MeterReadingPatch,
    PortfolioCreate,
    PropertyCreate,
    Receivable,
    ReceivableCreate,
    ReceivablePatch,
    StandaloneMeterReadingPatch,
    TaxRateCreate,
    TaxRatePatch,
    TenantCreate,
    UnitCreate,
)
from backend.models_deposits import ItemInput, TakeoverRequest
from backend.models_service_contracts import ServiceContractInvoiceFields, UnitPrice
from backend.repositories import SQLAlchemyStore
from backend.services import invoice_review
from backend.services.maintenance_rows import Rows, registry
from backend.storage import InMemoryStore


@pytest.fixture(params=["memory", "sqlite"])
def estate(request, tmp_path):
    registry()
    engine = session = None
    target: Any = InMemoryStore()
    if request.param == "sqlite":
        engine = create_engine(f"sqlite:///{(tmp_path / 'finance-cutoff.db').as_posix()}")
        schema_state.initialise_empty(engine)
        session = Session(engine)
        target = SQLAlchemyStore(session)
    portfolio = target.create_portfolio(PortfolioCreate(name="Cutoff"))
    prop = target.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="residential"))
    account = target.create_account(AccountCreate(portfolio_id=portfolio.id, name="Bank", account_type="bank"))
    yield target, prop, account
    if session is not None:
        session.close()
    if engine is not None:
        engine.dispose()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", 1e100, -1e100, 10_000_000_000])
@pytest.mark.parametrize("model", [ReceivableCreate, ReceivablePatch])
def test_receivable_request_refuses_nonfinite_and_unstorable_money(model, value):
    fields = {"amount_due": value}
    if model is ReceivableCreate:
        fields.update(contract_id="contract", due_date=date(2026, 1, 1))
    with pytest.raises(ValueError):
        model(**fields)


@pytest.mark.parametrize(("value", "expected"), [
    (0.005, 0.01), (-0.005, -0.01), (2.675, 2.68), (-2.675, -2.68),
    ("2.675", 2.68), ("-2675e-3", -2.68), ("5e-3", 0.01),
    ("9999999999.994", 9999999999.99), ("-9999999999.994", -9999999999.99),
    (-0.004, 0.0),
])
def test_request_money_rounds_once_before_storage(value, expected):
    result = ReceivablePatch(amount_due=value).amount_due
    assert result is not None
    assert result == expected
    if not result:
        assert math.copysign(1, result) == 1


@pytest.mark.parametrize("value", [True, "9999999999.995", "-9999999999.995", "1e999999"])
def test_invalid_input_cannot_cross_column_limit_when_rounded(value):
    with pytest.raises(ValueError):
        ReceivablePatch(amount_due=value)


def test_request_guards_do_not_change_exact_prices_legacy_records_or_aggregate_limits():
    assert UnitPrice.model_validate({"label": "Strom", "unit": "kWh", "price": "0.324789"}).price == Decimal("0.324789")
    assert Receivable(id="old", contract_id="contract", due_date=date(2026, 1, 1),
        amount_due=2.675).amount_due == 2.675
    assert money_sum(["9999999999.99", "0.02"]) == Decimal("10000000000.01")
    # The takeover service deliberately rejects fractional cents rather than
    # silently changing a historical balance. Preserve its original evidence.
    assert TakeoverRequest.model_validate({"base_revision": "r", "carried_amount": 500.005}).carried_amount == 500.005
    with pytest.raises(ValueError):
        ItemInput.model_validate({"kind": "other", "description": "Schaden", "amount": "Infinity"})
    exact_settlement = {"expected_revision": "r", "idempotency_key": "strict-cents-123",
                        "booking_id": "booking", "effective_date": date(2026, 1, 1),
                        "reason": "Zahlung zuordnen"}
    with pytest.raises(ValueError):
        SettlementCommand.model_validate({**exact_settlement, "amount": "2.675"})
    assert SettlementCommand.model_validate({**exact_settlement, "amount": "2.67"}).amount == Decimal("2.67")


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e9999"])
def test_handover_meter_requests_cannot_introduce_nonfinite_billing_measurements(value):
    with pytest.raises(ValueError):
        MeterReadingCreate(handover_id="handover", meter_type="water", reading_value=value)
    with pytest.raises(ValueError):
        MeterReadingPatch(reading_value=value)
    with pytest.raises(ValueError):
        StandaloneMeterReadingPatch(value=value)
    with pytest.raises(ValueError):
        TaxRateCreate(name="MwSt", rate=value)
    with pytest.raises(ValueError):
        TaxRatePatch(rate=value)
    with pytest.raises(ValueError):
        ServiceContractInvoiceFields(period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31), consumption=value)


def test_physical_quantities_and_percentages_keep_their_precision():
    assert StandaloneMeterReadingPatch(value=12.345678).value == 12.345678
    assert TaxRateCreate(name="MwSt", rate=12.3456).rate == 12.3456
    assert ServiceContractInvoiceFields(period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31), consumption=12.345678).consumption == 12.345678


def test_receivable_api_rejects_invalid_money_without_mutation_and_normalizes_valid_money(estate, monkeypatch):
    from backend.routers import receivables

    store, prop, _ = estate
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="1", unit_type="residential"))
    tenant = store.create_tenant(TenantCreate(full_name="Testmieter"))
    contract = store.create_contract(ContractCreate(contract_number="1", property_id=prop.id,
        unit_id=unit.id, tenant_id=tenant.id, start_date=date(2026, 1, 1)))
    monkeypatch.setattr(receivables, "store", store)
    app = FastAPI()
    app.include_router(receivables.router)
    with TestClient(app) as client:
        values = {"contract_id": contract.id, "due_date": "2026-01-31", "amount_due": 12.34}
        response = client.post("/receivables", json=values)
        assert response.status_code == 201, response.text
        claim_id = response.json()["id"]
        before = [r.model_dump(mode="json") for r in store.list_receivables()]
        for method in ("post", "put", "patch"):
            url = "/receivables" if method == "post" else f"/receivables/{claim_id}"
            for invalid in ("NaN", "Infinity", "-Infinity", "1e100", "9999999999.995"):
                body = {"amount_due": invalid} if method == "patch" else {**values, "amount_due": invalid}
                rejected = getattr(client, method)(url, json=body)
                assert rejected.status_code == 422, (method, invalid, rejected.text)
                assert [r.model_dump(mode="json") for r in store.list_receivables()] == before
        # A small credit is legal. Both repositories must keep and return the
        # same half-up cent amount, including after a second read.
        for amount, expected in (("-2.675", -2.68), ("5e-3", 0.01)):
            updated = client.patch(f"/receivables/{claim_id}", json={"amount_due": amount})
            assert updated.status_code == 200, updated.text
            assert updated.json()["amount_due"] == expected
            assert client.get(f"/receivables/{claim_id}").json()["amount_due"] == expected


def test_meter_api_rejects_nonfinite_measurements_before_persistence(estate, monkeypatch):
    from backend.routers import meters_standalone

    store, prop, _ = estate
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="1", unit_type="residential"))
    meter = store.create_meter(MeterCreate(unit_id=unit.id, meter_type="cold_water", serial_number="W-1"))
    monkeypatch.setattr(meters_standalone, "store", store)
    app = FastAPI()
    app.include_router(meters_standalone.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        path = f"/meters/{meter.id}/readings"
        for invalid in ("Infinity", "NaN", "-Infinity", "1e1000"):
            result = client.post(path, json={"meter_id": meter.id, "reading_date": "2026-01-01", "value": invalid})
            assert result.status_code == 422, (invalid, result.status_code, result.text)
            assert store.list_standalone_meter_readings() == []
        valid = client.post(path, json={"meter_id": meter.id, "reading_date": "2026-01-01", "value": 12.3456})
        assert valid.status_code == 201, valid.text
        assert valid.json()["value"] == 12.3456
        assert client.get(f"/meters/{meter.id}/history").status_code == 200


def test_default_invoice_settlement_uses_today_before_reading_future_cash(estate, monkeypatch):
    store, prop, account = estate
    today = date(2026, 1, 31)
    monkeypatch.setattr(invoice_review, "local_today", lambda: today)
    invoice = store.create_invoice(InvoiceCreate(property_id=prop.id, supplier="Lieferant",
        invoice_date=date(2026, 1, 1), net_amount=100, vat_rate=0, gross_amount=100))
    booking = store.create_booking(BookingCreate(account_id=account.id, booking_date=date(2026, 2, 1), amount=-100))
    rows = Rows.reading(store)
    rows.add("invoice_payments", InvoicePayment(id="future-payment", invoice_id=invoice.id,
        booking_id=booking.id, amount=100))
    if hasattr(store, "db"):
        store.db.commit()
    explicit = invoice_review.settlements(rows, [invoice], today)[invoice.id]
    implicit = invoice_review.settlements(rows, [invoice])[invoice.id]
    assert explicit.paid == Decimal("0.00")
    assert implicit.paid == explicit.paid
    assert implicit.open == explicit.open == Decimal("100.00")
    assert invoice_review.settlements(rows, [invoice], date(2026, 2, 1))[invoice.id].paid == Decimal("100.00")


def test_default_invoice_settlement_excludes_future_credit_note(estate, monkeypatch):
    store, prop, _ = estate
    today = date(2026, 1, 31)
    monkeypatch.setattr(invoice_review, "local_today", lambda: today)
    original = store.create_invoice(InvoiceCreate(property_id=prop.id, supplier="Lieferant",
        invoice_date=date(2026, 1, 1), net_amount=100, vat_rate=0, gross_amount=100))
    note = store.create_invoice(InvoiceCreate(property_id=prop.id, supplier="Lieferant",
        invoice_date=date(2026, 2, 1), net_amount=20, vat_rate=0, gross_amount=20))
    rows = Rows.reading(store)
    rows.add("invoice_reviews", InvoiceReview(id="future-credit", invoice_id=note.id,
        received_on=today, kind="credit_note", credit_for_invoice_id=original.id,
        status="approved", approved_amount=20))
    if hasattr(store, "db"):
        store.db.commit()
    current = invoice_review.settlements(rows, [original])[original.id]
    assert current.open == current.payable == Decimal("100.00")
    later = invoice_review.settlements(rows, [original], date(2026, 2, 1))[original.id]
    assert later.open == later.payable == Decimal("80.00")


def test_default_invoice_settlement_excludes_future_reversal(estate, monkeypatch):
    store, prop, account = estate
    today = date(2026, 1, 31)
    monkeypatch.setattr(invoice_review, "local_today", lambda: today)
    invoice = store.create_invoice(InvoiceCreate(property_id=prop.id, supplier="Lieferant",
        invoice_date=date(2026, 1, 1), net_amount=100, vat_rate=0, gross_amount=100))
    cash = store.create_booking(BookingCreate(account_id=account.id, booking_date=date(2026, 1, 2), amount=-100))
    rows = Rows.reading(store)
    rows.add("invoice_payments", InvoicePayment(id="paid-before-return", invoice_id=invoice.id,
        booking_id=cash.id, amount=100))
    if hasattr(store, "db"):
        store.db.commit()
    store.create_booking(BookingCreate(account_id=account.id, booking_date=date(2026, 2, 1),
        amount=100, reverses_booking_id=cash.id))
    current = invoice_review.settlements(rows, [invoice])[invoice.id]
    assert current.paid == Decimal("100.00") and current.open == Decimal("0.00")
    later = invoice_review.settlements(rows, [invoice], date(2026, 2, 1))[invoice.id]
    assert later.paid == Decimal("0.00") and later.open == Decimal("100.00")
