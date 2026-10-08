"""Portfolio boundaries on a real PostgreSQL server: SQL filters, direct IDs and the commit fence.

Opt in with IMMO_TEST_POSTGRES_ADMIN_URL (see test_document_versions_postgres.py).
"""

import pytest
from archive_helpers import lease_with_document
from fastapi import HTTPException
from sqlalchemy.orm import Session
from test_document_versions_postgres import postgres  # noqa: F401  (fixture: own database per test)

from backend import auth
from backend.models import ContactCreate
from backend.repositories import SQLAlchemyStore
from backend.repositories.base import NotFoundError
from backend.services.portfolio_scope import scope_context, scope_from_user


def _store(engine):
    return SQLAlchemyStore(Session(engine))


def _scope(user):
    stored = auth.get_user_by_id(user.id)
    assert stored is not None
    return scope_from_user(stored)


def test_restricted_reads_on_postgres(postgres):  # noqa: F811
    engine, _ = postgres
    seed = _store(engine)
    north = lease_with_document(seed, number="N-1", file_url="/uploads/documents/n.pdf")
    south = lease_with_document(seed, number="S-1", file_url="/uploads/documents/s.pdf")
    seed.db.close()
    staff = auth.register_user("staff", "s@example.com", "Staff", "Secret123", "verwalter",
                               portfolio_access="selected", portfolio_ids=[north["portfolio"].id])

    target = _store(engine)
    with scope_context(_scope(staff)):
        assert {p.id for p in target.list_properties()} == {north["property"].id}
        assert {t.id for t in target.list_tenants()} == {north["tenant"].id}      # tenants through contracts
        assert {d.id for d in target.list_documents()} == {north["document"].id}
        assert {c.id for c in target.list_contracts()} == {north["contract"].id}
        with pytest.raises(NotFoundError):
            target.get_contract(south["contract"].id)
        with pytest.raises(NotFoundError):
            target.get_document(south["document"].id)
    target.db.close()


def test_a_withdrawn_assignment_stops_a_write_before_its_commit(postgres):  # noqa: F811
    engine, _ = postgres
    seed = _store(engine)
    north = lease_with_document(seed, number="N-1")
    seed.db.close()
    staff = auth.register_user("staff", "s@example.com", "Staff", "Secret123", "verwalter",
                               portfolio_access="selected", portfolio_ids=[north["portfolio"].id])
    scope = _scope(staff)

    from backend.db.orm_models import ContactORM

    writer = _store(engine)
    with scope_context(scope):
        # the change is flushed (checked, bound to the portfolio) but not yet committed ...
        writer.db.add(ContactORM(contact_type="supplier", company_name="Heizung Nord GmbH"))
        writer.db.flush()
    # ... when the owner (another request) withdraws the assignment
    auth.update_user(staff.id, {"portfolio_access": "selected", "portfolio_ids": []})
    with scope_context(scope):
        with pytest.raises(HTTPException) as refused:
            writer.db.commit()
        assert refused.value.status_code == 403
        writer.db.rollback()
    writer.db.close()

    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM contacts").scalar() == 0
        assert connection.exec_driver_sql("SELECT count(*) FROM resource_portfolio_grants").scalar() == 0

    # with the assignment in place the same write commits, bound to the portfolio
    auth.update_user(staff.id, {"portfolio_access": "selected", "portfolio_ids": [north["portfolio"].id]})
    again = _store(engine)
    with scope_context(_scope(staff)):
        created = again.create_contact(ContactCreate(contact_type="supplier", company_name="Heizung Nord GmbH"))
    again.db.close()
    with engine.connect() as connection:
        bound = connection.exec_driver_sql(
            "SELECT portfolio_id FROM resource_portfolio_grants WHERE resource_id = %s", (created.id,)).scalars().all()
    assert bound == [north["portfolio"].id]


def test_global_search_on_postgres(postgres):  # noqa: F811
    from backend.services import global_search

    engine, _ = postgres
    seed = _store(engine)
    north = lease_with_document(seed, number="N-100%")
    south = lease_with_document(seed, number="S-100%")
    seed.db.close()
    staff = auth.register_user("staff", "s@example.com", "Staff", "Secret123", "verwalter",
                               portfolio_access="selected", portfolio_ids=[north["portfolio"].id])

    reader = _store(engine)
    for spec in global_search.SEARCH_TYPES:  # every type, numeric columns included, runs on PostgreSQL
        global_search.search_page(reader, spec, "1", limit=5)
    with scope_context(_scope(staff)):
        page = global_search.search_page(reader, global_search.get_type("contract"), "100%", limit=5)
    assert [hit["id"] for hit in page.items] == [north["contract"].id] and page.total == 1
    assert south["contract"].id not in {hit["id"] for hit in page.items}
    reader.db.close()
