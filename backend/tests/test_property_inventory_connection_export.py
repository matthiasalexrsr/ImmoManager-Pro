"""Use an actual connection-bound caller without replacing its transaction."""

import csv
import io

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.orm_models import PropertyORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import property_inventory as service
from backend.services.property_inventory_export import csv_chunks
from backend.tests.property_inventory_support import actor, properties, units
from backend.tests.property_inventory_support import property_box as property_box
from backend.tests.test_property_inventory import query


def test_connection_bound_caller_export_uses_independent_engine(property_box):
    box = property_box
    if box.engine is None:
        pytest.skip("Actual connection-bound SQL caller, separate Memory export cases")
    properties(box, [{"id": "connected", "portfolio_id": "eur", "name": "Original"}])
    units(box, [{"id": "source-unit", "property_id": "connected", "cold_rent": 0.29}])
    with box.engine.connect() as connection, connection.begin() as transaction, Session(bind=connection) as caller:
        driver = connection.connection.driver_connection
        with actor(box, "reader-eur"):
            row = caller.get(PropertyORM, "connected")
            row.name = "Unflushed caller edit"
            store = SQLAlchemyStore(caller)
            page = service.property_inventory_page(store, query())
            assert page.items[0].name == "Original"
            result = b"".join(csv_chunks(store, query(), token=box.tokens["reader-eur"], chunk_size=1))
        exported = list(csv.DictReader(io.StringIO(result.decode("utf-8-sig")), delimiter=";"))
        assert [(item["id"], item["name"], item["unit_cold_rent_sum"]) for item in exported] == [
            ("connected", "Original", "0.29"),
        ]
        assert caller.get_bind() is connection and connection.get_transaction() is transaction
        assert transaction.is_active and connection.connection.driver_connection is driver
        assert row in caller.dirty and row.name == "Unflushed caller edit"
        with box.engine.connect() as independent:
            assert independent.connection.driver_connection is not driver
            assert independent.scalar(select(PropertyORM.name).where(PropertyORM.id == "connected")) == "Original"
