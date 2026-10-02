"""Real multipart HTTP, authorization changes, account scope and persisted previews."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import scoped_session, sessionmaker

from backend import auth, dependencies
from backend.db.bank_import_schema import ensure_bank_import_schema
from backend.db.orm_models import Base
from backend.models import AccountCreate, AccountPatch, PortfolioCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import reports
from backend.routers.bank_imports import router
from backend.services import bank_import
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.services.portfolio_scope import scope_context
from backend.storage import InMemoryStore


@pytest.fixture(params=["memory", "sql"])
def bank_http(request, monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'http.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        ensure_bank_import_schema(connection)
    factory = sessionmaker(engine)
    registry = scoped_session(factory, scopefunc=dependencies.session_scope_key)
    store = SQLAlchemyStore(registry) if request.param == "sql" else InMemoryStore()
    monkeypatch.setattr(dependencies, "store", store)
    monkeypatch.setattr(reports, "store", store)
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory) if request.param == "sql" else auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", factory if request.param == "sql" else None)
    with scope_context(None):
        portfolios = [store.create_portfolio(PortfolioCreate(name=f"Synthetic {index}")) for index in range(2)]
        accounts = [store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Test bank", account_type="bank")) for portfolio in portfolios]
        owner = auth.register_user("owner", "owner@example.test", "Owner", "StrongPass123!", "eigentuemer")
        member = auth.register_user("member", "member@example.test", "Finance", "StrongPass123!", "buchhaltung",
                                    portfolio_access="selected", portfolio_ids=[portfolios[0].id])
        readonly = auth.register_user("reader", "reader@example.test", "Reader", "StrongPass123!", "readonly")
    def headers(user):
        return {"Authorization": "Bearer " + auth.create_access_token(user.id)}
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.include_router(reports.router, prefix="/api/v1")
    with TestClient(PortfolioScopeMiddleware(app)) as client:
        yield client, store, headers(owner), headers(member), headers(readonly), member, accounts, portfolios, engine
    registry.remove()
    if hasattr(store, "_bank_import_engine"):
        store._bank_import_engine.dispose()
    engine.dispose()


def upload(client, account_id, headers, content="date;amount;text\n2026-01-01;1.01;Synthetic\n"):
    return client.post("/api/v1/bookings/imports", headers=headers,
        data={"account_id": account_id, "mapping": json.dumps({"format": "csv"})},
        files={"file": ("sample.csv", content.encode(), "text/csv")})


def test_http_upload_requires_login_finance_and_authorized_account(bank_http):
    client, store, owner, finance, readonly, member, accounts, _, _ = bank_http
    assert upload(client, accounts[0].id, {}).status_code == 401
    assert upload(client, accounts[0].id, readonly).status_code == 403
    assert upload(client, accounts[1].id, finance).status_code == 404
    response = upload(client, accounts[0].id, finance)
    assert response.status_code == 201
    job = response.json()
    assert job["state"] == "ready"
    assert not store.list_bookings()
    assert client.get(f"/api/v1/bookings/imports/{job['id']}/preview", headers=finance).json()["items"][0]["amount_cents"] == 101
    auth.update_user(member.id, {"portfolio_access": "selected", "portfolio_ids": [accounts[1].portfolio_id]})
    assert client.get(f"/api/v1/bookings/imports/{job['id']}/preview", headers=finance).status_code == 404
    assert client.post(f"/api/v1/bookings/imports/{job['id']}/confirm", headers=finance,
        json={"revision": job["revision"], "preview_hash": job["preview_hash"]}).status_code == 404
    assert not store.list_bookings()
    # Authorized owner can recover and explicitly approve the same durable job.
    approved = client.post(f"/api/v1/bookings/imports/{job['id']}/confirm", headers=owner,
        json={"revision": job["revision"], "preview_hash": job["preview_hash"]})
    assert approved.status_code == 200 and approved.json()["published_count"] == 1


def test_legacy_http_import_has_atomic_errors_and_preserves_account_status(bank_http):
    client, store, _, finance, _, _, accounts, _, _ = bank_http
    body = {"account_id": accounts[1].id, "csv_content": "date;amount;text\n2026-01-01;1;Foreign\n"}
    foreign = client.post("/api/v1/reports/bookings/import", headers=finance, json=body)
    assert foreign.status_code == 404
    body = {"account_id": accounts[0].id, "csv_content": "date;amount;text\n2026-01-01;1;Valid\ninvalid;2;Bad date\n"}
    invalid = client.post("/api/v1/reports/bookings/import", headers=finance, json=body)
    assert invalid.status_code == 200
    assert invalid.json()["imported"] == 0 and invalid.json()["errors"] == 1
    assert invalid.json()["state"] == "invalid" and not store.list_bookings()


def test_http_role_revocation_and_stale_revision_are_recoverable(bank_http):
    client, store, owner, finance, _, member, accounts, _, _ = bank_http
    job = upload(client, accounts[0].id, finance).json()
    auth.update_user(member.id, {"role": "readonly"})
    confirmation = {"revision": job["revision"], "preview_hash": job["preview_hash"]}
    assert client.post(f"/api/v1/bookings/imports/{job['id']}/confirm", headers=finance, json=confirmation).status_code == 403
    response = client.post(f"/api/v1/bookings/imports/{job['id']}/confirm", headers=owner, json={**confirmation, "revision": 100})
    assert response.status_code == 409 and response.json()["error"]["code"] == "BANK_IMPORT_STALE"
    assert not store.list_bookings()
    assert client.post(f"/api/v1/bookings/imports/{job['id']}/confirm", headers=owner, json=confirmation).status_code == 200


def test_actual_account_move_after_preview_blocks_publication(bank_http):
    client, store, owner, _, _, _, accounts, portfolios, _ = bank_http
    job = upload(client, accounts[0].id, owner).json()
    with scope_context(None):
        original = store.get_account(accounts[0].id)
        store.update_account(original.id, AccountCreate(**{**original.model_dump(include=set(AccountCreate.model_fields)), "portfolio_id": portfolios[1].id}))
    response = client.post(f"/api/v1/bookings/imports/{job['id']}/confirm", headers=owner,
        json={"revision": job["revision"], "preview_hash": job["preview_hash"]})
    assert response.status_code == 403 and response.json()["error"]["code"] == "BANK_ACCOUNT_MOVED"
    assert not store.list_bookings()
    listed = client.get(f"/api/v1/bookings/imports?account_id={accounts[0].id}", headers=owner)
    assert listed.status_code == 200 and listed.json()["items"] == []


def test_mt940_account_change_after_preview_blocks_commit_without_raw_iban(bank_http):
    client, store, owner, _, _, _, accounts, _, _ = bank_http
    iban = "DE89370400440532013000"
    with scope_context(None):
        store._patch_entity("account", accounts[0].id, AccountPatch(iban=iban))
    source = f":20:BINDING\n:25:{iban}\n:28C:1/1\n:60F:C260101EUR0,00\n:61:2601020102C1,01NTRFNONREF\n:86:Synthetic\n:62F:C260102EUR1,01\n"
    response = client.post("/api/v1/bookings/imports", headers=owner,
        data={"account_id": accounts[0].id, "mapping": json.dumps({"format": "mt940"})},
        files={"file": ("sample.sta", source.encode(), "application/octet-stream")})
    assert response.status_code == 201
    job = response.json()
    assert job["state"] == "ready" and len(job["mapping"]["account_binding_hash"]) == 64
    assert iban not in json.dumps(job)
    with scope_context(None):
        store._patch_entity("account", accounts[0].id, AccountPatch(iban="DE12500105170648489890"))
    changed = client.post(f"/api/v1/bookings/imports/{job['id']}/confirm", headers=owner,
        json={"revision": job["revision"], "preview_hash": job["preview_hash"]})
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "BANK_ACCOUNT_CHANGED"
    assert not store.list_bookings()


def test_sql_rechecks_permissions_after_work_started_before_commit(bank_http, monkeypatch):
    client, store, owner, finance, _, member, accounts, _, engine = bank_http
    if not hasattr(store, "db"):
        pytest.skip("Real SQL rollback of a publication chunk")
    job = upload(client, accounts[0].id, finance).json()
    original = auth.get_user_by_id
    changed = False
    scoped_updates = []
    def fresh(identifier):
        user = original(identifier)
        return {**user, "role": "readonly"} if changed and identifier == member.id else user
    monkeypatch.setattr(auth, "get_user_by_id", fresh)
    original_clause = bank_import.scoped_clause
    def cte_account_clause(table, *, scope=None):
        # Account currently short-circuits directly on portfolio_id. Exercise
        # the leading WITH shape explicitly using its authoritative predicate,
        # so future shared graph changes cannot revive driver autocommit/-1.
        predicate = original_clause(table, scope=scope)
        if predicate is None:
            return None
        visible = select(table.c.id).where(predicate).cte("bank_test_visible_account")
        return table.c.id.in_(select(visible.c.id))
    monkeypatch.setattr(bank_import, "scoped_clause", cte_account_clause)
    def revoke(_connection, _cursor, statement, _parameters, _context, _many):
        nonlocal changed
        if statement.lstrip().startswith("WITH") and "UPDATE accounts" in statement:
            scoped_updates.append(statement)
        if statement.startswith("INSERT INTO bookings"):
            changed = True
    event.listen(engine, "after_cursor_execute", revoke)
    try:
        response = client.post(f"/api/v1/bookings/imports/{job['id']}/confirm", headers=finance,
            json={"revision": job["revision"], "preview_hash": job["preview_hash"]})
    finally:
        event.remove(engine, "after_cursor_execute", revoke)
    assert response.status_code == 403
    assert scoped_updates, "Exercise real leading WITH DML with the authoritative scope predicate"
    assert not store.list_bookings()
    assert client.get(f"/api/v1/bookings/imports/{job['id']}", headers=owner).json()["revision"] == 0
