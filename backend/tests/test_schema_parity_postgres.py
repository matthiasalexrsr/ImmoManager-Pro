"""A new installation and an upgraded one have the same schema on PostgreSQL too."""

import os
from uuid import uuid4

import pytest
import sqlalchemy as sa
from test_schema_parity import build_fresh, build_upgraded, differences


@pytest.fixture
def two_databases():
    admin_url = os.getenv("IMMO_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("set IMMO_TEST_POSTGRES_ADMIN_URL for real PostgreSQL schema checks")
    url = sa.engine.make_url(admin_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("PostgreSQL schema checks require an explicitly configured loopback server")
    names = [f"immoqa_parity_{uuid4().hex}" for _ in range(2)]
    admin = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    created = []
    try:
        with admin.connect() as connection:
            for name in names:
                connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
                created.append(name)
        yield [url.set(database=name).render_as_string(hide_password=False) for name in names]
    finally:
        with admin.connect() as connection:
            for name in created:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


def test_new_and_upgraded_postgres_databases_have_the_same_schema(two_databases):
    fresh, upgraded = two_databases
    build_fresh(fresh)
    build_upgraded(upgraded)

    assert differences(fresh, upgraded, "postgresql") == []


def test_upgrade_clears_invoice_references_to_deleted_documents(two_databases):
    """The reference to the source document was missing; a deleted document left a dangling id."""
    from alembic import command

    from backend.db.schema_state import alembic_config

    url = two_databases[1]
    command.upgrade(alembic_config(url), "c7e9a1b3d5f7")
    engine = sa.create_engine(url)
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO documents (id, title, file_url, created_at, updated_at) "
                                   "VALUES ('d1', 'Rechnung', '/uploads/x.pdf', now(), now())"))
        for key, document in (("i1", "d1"), ("i2", "deleted")):
            connection.execute(sa.text("INSERT INTO invoices (id, supplier, invoice_date, net_amount, vat_amount, "
                                       "gross_amount, status, source_document_id, created_at, updated_at) VALUES "
                                       "(:id, 'Firma', '2026-01-02', 100, 19, 119, 'open', :document, now(), now())"),
                               {"id": key, "document": document})
    engine.dispose()

    build_upgraded(url)

    engine = sa.create_engine(url)
    with engine.connect() as connection:
        rows = connection.execute(sa.text("SELECT id, source_document_id FROM invoices ORDER BY id")).all()
        keys = sa.inspect(connection).get_foreign_keys("invoices")
    engine.dispose()
    assert rows == [("i1", "d1"), ("i2", None)]
    assert any(key["constrained_columns"] == ["source_document_id"] and key["options"].get("ondelete") == "SET NULL"
               for key in keys)
