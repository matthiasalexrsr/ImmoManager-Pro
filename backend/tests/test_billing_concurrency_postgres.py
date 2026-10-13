"""Finalization and cost writes share one transaction boundary on PostgreSQL."""

import threading
from datetime import date
from functools import partial

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import scoped_session, sessionmaker
from test_document_versions_postgres import postgres  # noqa: F401

from backend.models import (
    AllocationKeyCreate,
    BillingPeriodCreate,
    ContactCreate,
    ContractCreate,
    CostItemCreate,
    CostItemPatch,
    InvoiceCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)
from backend.repositories import SQLAlchemyStore
from backend.routers import billing


def _draft(target):
    portfolio = target.create_portfolio(PortfolioCreate(name="Billing concurrency"))
    prop = target.create_property(PropertyCreate(
        portfolio_id=portfolio.id, name="House", property_type="residential"))
    unit = target.create_unit(UnitCreate(property_id=prop.id, label="Flat", unit_type="residential", area_sqm=50))
    tenant = target.create_tenant(TenantCreate(full_name="Tenant"))
    target.create_contract(ContractCreate(
        property_id=prop.id, unit_id=unit.id, tenant_id=tenant.id,
        contract_number="B-1", start_date=date(2020, 1, 1)))
    key = target.create_allocation_key(AllocationKeyCreate(property_id=prop.id, name="Area", key_type="area_sqm"))
    period = target.create_billing_period(BillingPeriodCreate(
        property_id=prop.id, label="2025", start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)))
    payload = CostItemCreate(billing_period_id=period.id, description="Tax", amount=100, allocation_key_id=key.id)
    target.create_cost_item(payload)
    billing.generate_utility_statements(period.id)
    return period, payload


@pytest.mark.parametrize("kind", ["cost", "move", "regenerate", "service", "invoice"])
def test_cost_write_waits_for_finalization_and_then_rejects(postgres, monkeypatch, kind):  # noqa: F811
    engine, _ = postgres
    sessions = scoped_session(sessionmaker(engine))
    target = SQLAlchemyStore(sessions)
    monkeypatch.setattr(billing, "store", target)
    period, payload = _draft(target)
    write_cost = partial(billing.create_cost_item, payload.model_copy(update={"description": "Late cost"}))
    if kind == "move":
        source = target.create_billing_period(BillingPeriodCreate(
            property_id=period.property_id, label="Other", start_date=period.start_date, end_date=period.end_date))
        cost = target.create_cost_item(payload.model_copy(update={"billing_period_id": source.id}))
        write_cost = partial(billing.patch_cost_item, cost.id, CostItemPatch(billing_period_id=period.id))
    elif kind == "regenerate":
        write_cost = partial(billing.generate_utility_statements, period.id)
    elif kind == "service":
        from test_service_contracts_postgres import _request

        from backend.models_service_contracts import CostTransferRequest, InvoiceLinkRequest
        from backend.services import service_contracts

        prop = target.get_property(period.property_id)
        provider = target.create_contact(ContactCreate(contact_type="supplier", company_name="Provider"))
        contract = service_contracts.create_contract(target, _request({"provider": provider, "house": prop}, "house"))
        service_contracts.add_bill(target, contract.id, InvoiceLinkRequest.model_validate({
            "period_start": "2025-01-01", "period_end": "2025-12-31",
            "invoice": {"supplier": "Provider", "invoice_date": "2026-01-15", "net_amount": 30, "gross_amount": 30}}))
        request = CostTransferRequest(billing_period_id=period.id, allocation_key_id=payload.allocation_key_id)
        write_cost = partial(service_contracts.transfer_costs, target, contract.id, request)
    elif kind == "invoice":
        from test_invoice_review_postgres import _approved

        from backend import auth
        from backend.invoice_review_models import CostTransferRequest
        from backend.services import invoice_review

        owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
        invoice = target.create_invoice(InvoiceCreate(
            property_id=period.property_id, supplier="Provider", invoice_date=date(2025, 5, 1),
            net_amount=30, gross_amount=30))
        _approved(engine, {"owner": owner}, invoice, recoverable=True)
        request = CostTransferRequest(billing_period_id=period.id, allocation_key_id=payload.allocation_key_id)
        write_cost = partial(invoice_review.transfer_cost, target, invoice.id, request, owner.id)
    sessions.remove()
    freezing, resume, written = threading.Event(), threading.Event(), threading.Event()
    outcomes = {}
    original = billing._live_statement_document

    def pause_after_validation(*args):
        freezing.set()
        assert resume.wait(10)
        return original(*args)

    monkeypatch.setattr(billing, "_live_statement_document", pause_after_validation)

    def finalize():
        try:
            outcomes["finalize"] = billing.finalize_billing_period(period.id).status
        except BaseException as error:
            outcomes["finalize"] = error
        finally:
            sessions.remove()

    def write():
        try:
            write_cost()
            outcomes["write"] = "saved"
        except HTTPException as error:
            outcomes["write"] = error.status_code
        except BaseException as error:
            outcomes["write"] = error
        finally:
            written.set()
            sessions.remove()

    finalizer = threading.Thread(target=finalize)
    writer = threading.Thread(target=write)
    try:
        finalizer.start()
        assert freezing.wait(10), outcomes
        writer.start()
        completed_before_finalization = written.wait(0.5)
    finally:
        resume.set()
        finalizer.join(15)
        if writer.ident is not None:
            writer.join(15)
        sessions.remove()

    assert not completed_before_finalization, outcomes
    assert outcomes == {"finalize": "finalized", "write": 409}
    assert len([row for row in target.list_cost_items() if row.billing_period_id == period.id]) == 1
    assert billing.get_billing_period_preflight(period.id).metrics["final_version_intact"]
    sessions.remove()


def test_concurrent_receivable_generation_bills_each_statement_once(postgres, monkeypatch):  # noqa: F811
    engine, _ = postgres
    sessions = scoped_session(sessionmaker(engine))
    target = SQLAlchemyStore(sessions)
    monkeypatch.setattr(billing, "store", target)
    period, _ = _draft(target)
    billing.finalize_billing_period(period.id)
    sessions.remove()
    writing, resume, second_done = threading.Event(), threading.Event(), threading.Event()
    outcomes = []
    create = target.create_receivable

    def pause_first(payload):
        if not writing.is_set():
            writing.set()
            assert resume.wait(10)
        return create(payload)

    monkeypatch.setattr(target, "create_receivable", pause_first)

    def generate(second=False):
        try:
            outcomes.append(billing.create_receivables_from_period(period.id)["created_receivables"])
        except BaseException as error:
            outcomes.append(error)
        finally:
            if second:
                second_done.set()
            sessions.remove()

    first = threading.Thread(target=generate)
    second = threading.Thread(target=generate, args=(True,))
    try:
        first.start()
        assert writing.wait(10), outcomes
        second.start()
        finished_early = second_done.wait(0.5)
    finally:
        resume.set()
        first.join(15)
        if second.ident is not None:
            second.join(15)
    assert not finished_early, outcomes
    assert sorted(outcomes, key=str) == [0, 1]
    assert len(target.list_receivables()) == 1
    sessions.remove()
