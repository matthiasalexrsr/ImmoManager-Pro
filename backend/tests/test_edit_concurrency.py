"""Atomic conditional edits; all SQL files/schemas belong to these tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.db.orm_models import Base, PortfolioORM
from backend.dependencies import store
from backend.models import PortfolioCreate, PortfolioPatch, PropertyCreate, TenantCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.concurrency import (
    EditRevision,
    etag,
    next_updated_at,
    parse_revision,
    resource_path,
    revision_scope,
    utc_datetime,
)
from backend.storage import InMemoryStore, ValidationError
from backend.tests import test_private_server_concurrency as postgres_support
from backend.tests.test_payments import payload, seed

# Reuse the existing explicitly configured disposable UUID-schema fixture.
postgres_database = postgres_support.postgres_database


@pytest.fixture(params=["memory", "sql"])
def edit_store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryStore()
        return
    engine = create_engine(f"sqlite:///{tmp_path / 'edits.db'}", connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield SQLAlchemyStore(db)
    engine.dispose()


def revision(record, collection="portfolios"):
    return parse_revision(etag(collection, record.id, record.updated_at))


@pytest.mark.parametrize("operation", ["put", "patch", "delete"])
def test_stale_edit_does_not_overwrite_or_delete_and_next_operation_works(edit_store, operation):
    first = edit_store.create_portfolio(PortfolioCreate(name="Original"))
    latest = edit_store.update_portfolio(first.id, PortfolioCreate(name="Saved by A"))
    with revision_scope(revision(first)), pytest.raises(HTTPException) as failure:
        if operation == "put":
            edit_store.update_portfolio(first.id, PortfolioCreate(name="Draft B"))
        elif operation == "patch":
            edit_store._patch_entity("portfolio", first.id, PortfolioPatch(name="Draft B"))
        else:
            edit_store.delete_portfolio(first.id)
    assert failure.value.status_code == 412
    assert edit_store.get_portfolio(first.id).name == "Saved by A"
    with revision_scope(revision(latest)):
        result = edit_store._patch_entity("portfolio", first.id, PortfolioPatch(name="Reconciled B"))
    assert result.name == "Reconciled B"
    assert utc_datetime(result.updated_at) > utc_datetime(latest.updated_at)


def test_conditional_delete_keeps_cascades_and_deleted_stale_token_conflicts(edit_store):
    parent = edit_store.create_portfolio(PortfolioCreate(name="Parent"))
    child = edit_store.create_property(PropertyCreate(portfolio_id=parent.id, name="Child", property_type="residential"))
    # Native conditional SQL delete uses existing database cascade constraints.
    edit_store.get_property(child.id)
    with revision_scope(revision(parent)):
        edit_store.delete_portfolio(parent.id)
    assert not edit_store.list_portfolios()
    assert not edit_store.list_properties()
    with revision_scope(revision(parent)), pytest.raises(HTTPException) as failure:
        edit_store.delete_portfolio(parent.id)
    assert failure.value.status_code == 412


def test_revisions_are_bound_to_collection_and_id(edit_store):
    first = edit_store.create_portfolio(PortfolioCreate(name="First"))
    second = edit_store.create_portfolio(PortfolioCreate(name="Second"))
    with revision_scope(revision(first)), pytest.raises(HTTPException):
        edit_store.update_portfolio(second.id, PortfolioCreate(name="Incorrect target"))
    wrong_collection = EditRevision("tenants", first.id, utc_datetime(first.updated_at))
    with revision_scope(wrong_collection), pytest.raises(HTTPException):
        edit_store.delete_portfolio(first.id)
    assert [item.name for item in edit_store.list_portfolios()] == ["First", "Second"]


def test_legacy_writes_remain_compatible_and_snapshots_are_monotonic(edit_store):
    old = edit_store.create_tenant(TenantCreate(full_name="Original"))
    assert edit_store.update_tenant(old.id, TenantCreate(full_name="Legacy")).full_name == "Legacy"
    assert edit_store.get_tenant(old.id).id == old.id
    edit_store.delete_tenant(old.id)


def test_payment_backed_guard_is_preserved_even_with_current_revision(edit_store):
    target = seed(edit_store, "rent_charge")
    edit_store.record_payment("rent_charge", target.id, payload())
    current = edit_store.get_rent_charge(target.id)
    with revision_scope(revision(current, "rent-charges")), pytest.raises(ValidationError):
        edit_store.delete_rent_charge(target.id)
    assert len(edit_store.list_payments("rent_charge", target.id)) == 1
    assert edit_store.get_rent_charge(target.id).amount_paid == 40.10


def _parallel_edits(factory, first, second=None, delete=False):
    barrier = Barrier(2)
    def run(index):
        target = second if second is not None and index else first
        active_store, close = factory()
        try:
            # Load each independent session's identity map before either writes.
            active_store.get_portfolio(target.id)
            barrier.wait(timeout=15)
            with revision_scope(revision(target)):
                try:
                    if delete:
                        active_store.delete_portfolio(target.id)
                    else:
                        active_store.update_portfolio(target.id, PortfolioCreate(name=f"Writer {index}"))
                    return 200
                except HTTPException as error:
                    return error.status_code
        finally:
            close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        return sorted(pool.map(run, [0, 1]))


@pytest.mark.parametrize("delete", [False, True])
def test_memory_threads_one_old_revision_has_exactly_one_winner(delete):
    memory = InMemoryStore()
    first = memory.create_portfolio(PortfolioCreate(name="Original"))
    assert _parallel_edits(lambda: (memory, lambda: None), first, delete=delete) == [200, 412]


def _database_race(engine, factory, delete=False):
    with factory() as db:
        active_store = SQLAlchemyStore(db)
        first = active_store.create_portfolio(PortfolioCreate(name="First"))
        second = active_store.create_portfolio(PortfolioCreate(name="Second"))
    def new_store():
        db = factory()
        return SQLAlchemyStore(db), db.close
    assert _parallel_edits(new_store, first, delete=delete) == [200, 412]
    if not delete:
        with factory() as db:
            current = SQLAlchemyStore(db).get_portfolio(first.id)
        assert _parallel_edits(new_store, current, second) == [200, 200]
        with factory() as db:
            assert len(SQLAlchemyStore(db).list_portfolios()) == 2
    assert engine.pool.checkedout() == 0


@pytest.mark.parametrize("delete", [False, True])
def test_sql_independent_sessions_cas_and_rollback(tmp_path, delete):
    engine = create_engine(f"sqlite:///{tmp_path / 'parallel.db'}", connect_args={"check_same_thread": False, "timeout": 15})
    Base.metadata.create_all(engine)
    try:
        _database_race(engine, sessionmaker(bind=engine), delete)
    finally:
        engine.dispose()


@pytest.mark.parametrize("delete", [False, True])
def test_pg_independent_session_conditional_update_delete_and_other_ids(postgres_database, delete):
    engine, factory, _, _ = postgres_database
    _database_race(engine, factory, delete)


def test_sql_get_refreshes_an_already_loaded_identity(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cache.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as a, Session(engine) as b:
        first = SQLAlchemyStore(a).create_portfolio(PortfolioCreate(name="Original"))
        old_orm = b.get(PortfolioORM, first.id)
        SQLAlchemyStore(a).update_portfolio(first.id, PortfolioCreate(name="Fresh"))
        assert old_orm.name == "Original"
        current = SQLAlchemyStore(b).get_portfolio(first.id)
        assert current.name == "Fresh"
        assert utc_datetime(current.updated_at) > utc_datetime(first.updated_at)
    engine.dispose()


def test_utc_tokens_preserve_microseconds_and_clock_never_moves_backwards():
    naive = datetime(2026, 10, 1, 8, 30, 40, 123456)
    aware = naive.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=2)))
    assert etag("properties", "same", naive) == etag("properties", "same", aware)
    assert parse_revision(etag("properties", "same", aware)).updated_at.microsecond == 123456
    assert next_updated_at(aware, naive - timedelta(days=1)) == utc_datetime(aware) + timedelta(microseconds=1)


@pytest.mark.parametrize("bad", ['*', 'W/"immo-v1:portfolios:abc:2026-01-01T00:00:00Z"', '"bad"',
                                 '"immo-v1:unknown:abc:2026-01-01T00:00:00Z"', '"immo-v1:portfolios:abc:not-a-date"',
                                 '"immo-v1:portfolios:abc:2026-01-01T00:00:00Z", "another"'])
def test_invalid_conditional_header_is_rejected(bad):
    with pytest.raises(HTTPException) as failure:
        parse_revision(bad)
    assert failure.value.status_code == 400


def test_only_exact_crud_paths_are_conditional():
    assert resource_path("/api/v1/properties/abc") == ("properties", "abc")
    assert resource_path("/api/v1/notifications/templates/abc") == ("notifications/templates", "abc")
    assert resource_path("/api/v1/handover-protocols/abc/meter-readings/xyz") == ("handover-protocols/meter-readings", "xyz")
    assert resource_path("/api/v1/meters/readings/all") == ("meters/readings", None)
    assert resource_path("/api/v1/rent-charges/abc/payments") is None
    assert resource_path("/api/v1/billing/periods/abc/finalize") is None


@pytest.fixture
def conditional_client():
    store.clear_all()
    clear_users()
    user = register_user("editowner", "edits@example.com", "Edit Owner", "Strong123", role="eigentuemer")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    with TestClient(app) as client:
        yield client, headers
    store.clear_all()
    clear_users()


@pytest.mark.parametrize("collection,payload_a,payload_b", [
    ("portfolios", {"name": "Original"}, {"name": "A saved"}),
    ("tenants", {"full_name": "Original"}, {"full_name": "A saved"}),
    ("contacts", {"company_name": "Original", "contact_type": "other"}, {"company_name": "A saved", "contact_type": "other"}),
])
def test_real_api_list_snapshot_conditional_put_patch_delete_and_recovery(conditional_client, collection, payload_a, payload_b):
    client, auth_headers = conditional_client
    created = client.post(f"/api/v1/{collection}", headers=auth_headers, json=payload_a)
    assert created.status_code == 201, created.text
    item = created.json()
    path = f"/api/v1/{collection}/{item['id']}"
    stale = etag(collection, item["id"], item["updated_at"])
    assert created.headers["etag"] == stale
    response = client.put(path, headers={**auth_headers, "If-Match": stale}, json=payload_b)
    assert response.status_code == 200, response.text
    current_token = response.headers["etag"]
    assert current_token != stale
    assert client.patch(path, headers={**auth_headers, "If-Match": stale}, json=payload_a).status_code == 412
    assert client.delete(path, headers={**auth_headers, "If-Match": stale}).status_code == 412
    assert client.get(path, headers=auth_headers).json() == response.json()
    fresh = client.patch(path, headers={**auth_headers, "If-Match": current_token}, json=payload_a)
    assert fresh.status_code == 200, fresh.text
    listed = client.get(f"/api/v1/{collection}", headers=auth_headers).json()
    assert listed[0]["updated_at"] == fresh.json()["updated_at"]
    assert client.delete(path, headers={**auth_headers, "If-Match": fresh.headers["etag"]}).status_code == 204


def test_api_wrong_target_header_and_financial_command_rejection(conditional_client):
    client, headers = conditional_client
    first = client.post("/api/v1/portfolios", headers=headers, json={"name": "First"})
    second = client.post("/api/v1/portfolios", headers=headers, json={"name": "Second"})
    path = "/api/v1/portfolios/" + second.json()["id"]
    assert client.put(path, headers={**headers, "If-Match": first.headers["etag"]}, json={"name": "Wrong"}).status_code == 412
    assert client.put(path, headers={**headers, "If-Match": "*"}, json={"name": "Wrong"}).status_code == 400
    assert client.patch("/api/v1/tenants/id/archive", headers={**headers, "If-Match": first.headers["etag"]}, json={}).status_code == 400
