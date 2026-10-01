"""Native PostgreSQL NUMERIC sources and concurrent independent annual writers."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi import HTTPException
from sqlalchemy import func, select

from backend.db.tax_models import AnnualTaxProjectionORM, AnnualTaxSourceORM
from backend.models import AccountCreate, CategoryCreate, PortfolioCreate, PropertyCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import annual_tax_storage as service
from backend.tests.test_annual_tax_projection import booking, preflight_command, profile_command, save_command
from backend.tests.test_private_server_concurrency import postgres_database as postgres_database  # noqa: F401 fixture


def test_pg_exact_raw_cash_and_unique_annual_snapshot_across_connections(postgres_database, monkeypatch):
    engine, factory, *_ = postgres_database
    with factory() as db:
        store = SQLAlchemyStore(db)
        portfolio = store.create_portfolio(PortfolioCreate(name="Synthetic PostgreSQL tax"))
        properties = [store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Synthetic", property_type="residential"))]
        accounts = [store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Synthetic cash", account_type="bank"))]
        categories = [store.create_category(CategoryCreate(portfolio_id=portfolio.id, name=name, category_type=kind)) for name, kind in (("Income", "income"), ("Expense", "expense"))]
        fixture = store, engine, portfolio, properties, accounts, categories
        booking(fixture, 0.01)
        booking(fixture, 999999.99)
        booking(fixture, -0.01, category=1)
        version = service.create_profile(store, profile_command(fixture), "actor")
        command = preflight_command(version)
        preview = service.preflight(store, command)
        assert preview["totals"]["income_cents"] == "100000000"
        assert preview["totals"]["expense_cents"] == "1"
    original, barrier = service.compile_projection, Barrier(2)
    def together(*args, **kwargs):
        compiled = original(*args, **kwargs)
        barrier.wait(timeout=30)
        return compiled
    monkeypatch.setattr(service, "compile_projection", together)
    def save(index):
        with factory() as db:
            try:
                result = service.create_projection(SQLAlchemyStore(db), save_command(command, preview, idempotency_key=str(index)), "actor")
                return 201, result["id"]
            except HTTPException as error:
                return error.status_code, None
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(save, range(2)))
    assert sorted(status for status, _ in results) == [201, 409]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AnnualTaxProjectionORM)) == 1
        assert db.scalar(select(func.count()).select_from(AnnualTaxSourceORM)) == 3
        assert len(list(service.saved_sources(SQLAlchemyStore(db), next(identifier for _, identifier in results if identifier)))) == 3
    assert engine.pool.checkedout() == 0
