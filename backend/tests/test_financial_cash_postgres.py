"""Actual PostgreSQL cash projections and independent current-source checks."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from backend import auth
from backend.db.orm_models import BookingORM
from backend.models import PortfolioCreate, PropertyCreate
from backend.services import financial_cash as service
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.tests.test_financial_cash import (
    booking,
    setup,
)
from backend.tests.test_financial_cash import (
    test_cash_sources_are_complete_and_detect_changed_source_and_cursor as cash_complete,
)
from backend.tests.test_financial_cash import (
    test_exact_cash_context_and_unassigned_object_costs as cash_exact,
)
from backend.tests.test_financial_cash import (
    test_linked_payment_receipt_does_not_duplicate_its_bank_booking as cash_linked,
)
from backend.tests.test_housing_confirmation_postgres import postgres_housing as postgres_housing


def test_postgres_cash_complete_sources_and_csv(postgres_housing):
    cash_complete(postgres_housing.store)


def test_postgres_cash_exact_contexts(postgres_housing):
    cash_exact(postgres_housing.store)


def test_postgres_cash_linked_payment_has_one_source(postgres_housing):
    cash_linked(postgres_housing.store)


def test_postgres_cash_parent_move_after_first_batch_prevents_publication(postgres_housing, monkeypatch):
    box = postgres_housing
    portfolio, prop, _, account, _ = setup(box.store)
    original = booking(box.store, account, .1, property_id=prop.id)
    foreign = box.store.create_portfolio(PortfolioCreate(name="Hidden cash"))
    hidden = box.store.create_property(PropertyCreate(portfolio_id=foreign.id, name="Hidden source", property_type="residential"))
    accounts = auth._user_store
    accounts.update("actor", {"portfolio_ids": [portfolio.id]})
    captured = scope_from_user(accounts.get_by_id("actor"))
    safe = service._safe_row
    changed = False

    def move():
        with Session(box.engine) as db:
            db.execute(update(BookingORM).where(BookingORM.id == original.id).values(property_id=hidden.id))
            db.commit()

    def observed(row):
        nonlocal changed
        result = safe(row)
        if not changed:
            changed = True
            with ThreadPoolExecutor(max_workers=1) as workers:
                workers.submit(move).result(timeout=10)
        return result

    monkeypatch.setattr(service, "_safe_row", observed)
    with scope_context(captured):
        with pytest.raises(HTTPException) as revoked:
            service.report(box.store, service.CashFilters(account_id=account.id))
        assert revoked.value.status_code == 403
    assert changed
