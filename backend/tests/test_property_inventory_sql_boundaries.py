"""Prepared real connection/rollback/aggregate proofs, not fake auth results."""

import pytest
from fastapi import HTTPException
from sqlalchemy import BigInteger, Column, MetaData, Table, create_engine, event, select
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models import PropertyCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import property_inventory as service
from backend.services.property_inventory_money import ExactCentSum, install_exact_sum
from backend.tests.property_inventory_support import actor, properties, sqlite_engine
from backend.tests.property_inventory_support import property_box as property_box
from backend.tests.test_property_inventory import query


def test_real_sqlite_aggregate_exceeds_int64_and_keeps_own_driver():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    metadata = MetaData()
    cents = Table("synthetic_cents", metadata, Column("amount", BigInteger))
    try:
        metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(cents.insert(), [{"amount": 2**63 - 1}, {"amount": 2**63 - 1}, {"amount": None}])
            with Session(bind=connection) as db:
                assert db.connection() is connection
                driver = connection.connection.driver_connection
                install_exact_sum(db, connection=connection)
                assert db.connection().connection.driver_connection is driver
                assert db.scalar(select(ExactCentSum(cents.c.amount))) == "18446744073709551614"
                assert db.scalar(select(ExactCentSum(cents.c.amount)).where(cents.c.amount < 0)) == "0"
    finally:
        engine.dispose()


def test_shared_sqlite_pool_is_closed_before_read_or_caller_rollback(property_box):
    box = property_box
    engine = create_engine("sqlite://", poolclass=StaticPool)
    table = Table("synthetic_caller", MetaData(), Column("id", BigInteger, primary_key=True))
    try:
        table.create(engine)
        with Session(engine) as caller:
            caller.execute(table.insert().values(id=1))
            driver = caller.connection().connection.driver_connection
            assert driver.in_transaction
            transaction = caller.get_transaction()
            with actor(box), pytest.raises(HTTPException) as error:
                service.property_inventory_page(SQLAlchemyStore(caller), query())
            assert error.value.status_code == 503
            assert caller.get_transaction() is transaction and transaction.is_active and driver.in_transaction
            assert caller.scalar(select(table.c.id)) == 1
            caller.rollback()
            assert caller.scalar(select(table.c.id)) is None
    finally:
        engine.dispose()


def test_actual_scoped_session_registry_keeps_current_session_and_dirty_caller(property_box):
    box = property_box
    if box.engine is None:
        pytest.skip("Actual SQL request registry boundary; not a Memory fixture")
    properties(box, [{"id": "registry-row", "portfolio_id": "eur", "name": "Original", "purchase_price": 0}])
    registry = scoped_session(sessionmaker(bind=box.engine))
    try:
        current = registry()
        with actor(box):
            row = current.get(service.PropertyORM, "registry-row")
            row.name = "Unflushed registry caller"
            transaction = current.get_transaction()
            driver = current.connection().connection.driver_connection
            page = service.property_inventory_page(SQLAlchemyStore(registry), query())
            summary = service.property_inventory_summary(SQLAlchemyStore(registry), query())
            assert len(page.items) == summary.scope_totals.property_count == 1
            assert page.items[0].name == "Original" and page.items[0].purchase_price == 0
            assert registry() is current and row in current.dirty
            assert current.get_transaction() is transaction and transaction.is_active
            assert current.connection().connection.driver_connection is driver
    finally:
        registry.remove()  # Test-owned registry only; product must never remove it.


@pytest.mark.parametrize("operation", ["page", "summary"])
def test_actual_independent_parent_writer_changes_publication(property_box, operation, tmp_path):
    box = property_box
    if box.engine is None:
        pytest.skip("Independent native SQL snapshot case, not a Memory race proof")
    properties(box, [{"id": "moving", "name": "Synthetic moving", "portfolio_id": "eur", "purchase_price": 0}])
    mutation = sqlite_engine(tmp_path / "synthetic-property-inventory.sqlite")
    changed, observed = [], []

    def after_projection(connection, _cursor, sql, _parameters, context, _many):
        if changed or "PROPERTY_INVENTORY_PARENTS" not in sql.upper() or not context.compiled.statement.is_select:
            return
        changed.append(True)
        observed.append(connection.connection.driver_connection)
        with actor(box, "owner"), Session(mutation) as db:
            assert db.connection().connection.driver_connection is not observed[-1]
            store = SQLAlchemyStore(db)
            actual = store.get_property("moving")
            payload = PropertyCreate(**{**actual.model_dump(), "portfolio_id": "usd"})
            result = store.update_property("moving", payload)  # Actual parent fences, credential, commit.
            assert result.portfolio_id == "usd"

    event.listen(box.engine, "after_cursor_execute", after_projection)
    try:
        with actor(box, "reader-eur"), pytest.raises(HTTPException) as error:
            getattr(service, "property_inventory_" + operation)(box.store, query())
        assert changed == [True] and observed and error.value.status_code == 409
    finally:
        event.remove(box.engine, "after_cursor_execute", after_projection)
        assert mutation.pool.checkedout() == 0
        mutation.dispose()
