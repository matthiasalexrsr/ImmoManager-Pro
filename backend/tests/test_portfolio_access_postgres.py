"""Independent PostgreSQL sessions use the same predicates and fresh grants."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend import auth, dependencies
from backend.db.orm_models import PropertyORM
from backend.models import PortfolioCreate, PropertyCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.portfolio_scope import refresh_scope, scope_context, scope_from_user, scoped_clause
from backend.tests import test_private_server_concurrency as server_tests

postgres_database = server_tests.postgres_database


def test_postgres_independent_finance_session_and_raw_connection_scope(postgres_database):
    engine, factory, *_ = postgres_database
    with factory() as db:
        store = SQLAlchemyStore(db)
        portfolios = [store.create_portfolio(PortfolioCreate(name=f"Synthetic {index}")) for index in range(2)]
        properties = [
            store.create_property(
                PropertyCreate(portfolio_id=row.id, name=f"Private {index}", property_type="residential")
            )
            for index, row in enumerate(portfolios)
        ]
    scope = scope_from_user(
        {"id": "synthetic", "role": "buchhaltung", "portfolio_access": "selected", "portfolio_ids": [portfolios[0].id]}
    )
    with scope_context(scope), factory() as financial_session:
        assert financial_session.get(PropertyORM, properties[1].id) is None
        assert [row.id for row in financial_session.scalars(select(PropertyORM))] == [properties[0].id]
        with engine.connect() as connection:
            assert connection.execute(
                select(PropertyORM.id).where(scoped_clause(PropertyORM, scope=scope))
            ).scalars().all() == [properties[0].id]
    assert engine.pool.checkedout() == 0


def test_postgres_old_jwt_scope_refresh_rejects_independent_grant_update(postgres_database, monkeypatch):
    engine, factory, *_ = postgres_database
    first, second = auth.SQLUserStore(factory), auth.SQLUserStore(factory)
    monkeypatch.setattr(auth, "_user_store", first)
    with factory() as db:
        store = SQLAlchemyStore(db)
        monkeypatch.setattr(dependencies, "store", store)
        portfolio = store.create_portfolio(PortfolioCreate(name="Synthetic"))
        owner = auth.register_user(
            "scopeowner", "scopeowner@example.test", "Owner", "a synthetic secure passphrase", "eigentuemer"
        )
        user = auth.register_user(
            "scopeuser",
            "scopeuser@example.test",
            "Scoped",
            "a synthetic secure passphrase",
            "verwalter",
            portfolio_access="selected",
            portfolio_ids=[portfolio.id],
        )
        captured = scope_from_user(first.get_by_id(user.id))
        assert refresh_scope(captured) == captured
        second.update(user.id, {"portfolio_access": "selected", "portfolio_ids": []}, actor_id=owner.id)
        with pytest.raises(HTTPException) as error:
            refresh_scope(captured)
        assert error.value.status_code == 403
    assert engine.pool.checkedout() == 0


def test_postgres_csv_references_correlate_to_the_exact_parent(postgres_database):
    from backend.models import ContactCreate, MessageThreadCreate
    from backend.services.portfolio_scope import AccessScope

    engine, factory, *_ = postgres_database
    with factory() as db:
        store = SQLAlchemyStore(db)
        portfolios = [store.create_portfolio(PortfolioCreate(name=f"CSV portfolio {index}")) for index in range(2)]
        properties = [store.create_property(PropertyCreate(portfolio_id=row.id, name=f"CSV property {index}", property_type="residential")) for index, row in enumerate(portfolios)]
        left_scope = AccessScope("synthetic", "verwalter", False, (portfolios[0].id,))
        with scope_context(left_scope):
            left = store.create_contact(ContactCreate(name="Allowed CSV contact"))
            visible = store.create_message_thread(MessageThreadCreate(subject="Allowed", property_id=properties[0].id, participant_ids=left.id))
        with scope_context(AccessScope("other", "verwalter", False, (portfolios[1].id,))):
            right = store.create_contact(ContactCreate(name="Forbidden CSV contact"))
        hidden = store.create_message_thread(MessageThreadCreate(subject="Historical cross-reference", property_id=properties[0].id, participant_ids=right.id))
    with scope_context(left_scope), factory() as independent:
        store = SQLAlchemyStore(independent)
        assert [row.id for row in store.list_message_threads()] == [visible.id]
        with pytest.raises(HTTPException):
            store.create_message_thread(MessageThreadCreate(subject="Bypass", property_id=properties[0].id, participant_ids=f"{left.id}, {right.id}"))
        independent.rollback()
        from backend.storage import NotFoundError
        with pytest.raises(NotFoundError):
            store.get_message_thread(hidden.id)
    assert engine.pool.checkedout() == 0
