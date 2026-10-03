"""Prepared real-auth HTTP proofs. Not yet executed or mounted in the Root app."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from backend import auth, dependencies
from backend.db import document_version_models  # noqa: F401 - complete actual FK metadata
from backend.db.notification_inbox_models import NotificationReadStateORM
from backend.db.operational_models import OperationalDispatchORM
from backend.db.orm_models import Base, NotificationORM, PortfolioORM, PropertyORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import auth as auth_router
from backend.routers import notification_inbox as inbox_router
from backend.routers import notifications as old_notifications
from backend.services import notification_inbox
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.services.portfolio_scope import scope_context
from backend.storage import InMemoryStore

PATH = "/api/v1/notifications/inbox"


def _notice(identifier, **values):
    return {
        "id": identifier, "notification_type": "task_due", "title": identifier,
        "content": "Synthetic HTTP inbox", "severity": "info",
        "entity_type": "property", "entity_id": "property-one", "status": "unread",
        "created_at": datetime(2026, 10, 3, 12), **values,
    }


@pytest.fixture
def http_installation(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + (tmp_path / "readonly-inbox.sqlite").as_posix(),
        connect_args={"check_same_thread": False}, hide_parameters=True,
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    accounts = auth.SQLUserStore(factory)
    monkeypatch.setattr(auth, "_user_store", accounts)
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    with scope_context(None), engine.begin() as connection:
        connection.execute(PortfolioORM.__table__.insert(), [
            {"id": "p-one", "name": "Synthetic permitted"},
            {"id": "p-two", "name": "Synthetic other"},
        ])
        connection.execute(PropertyORM.__table__.insert(), [
            {"id": "property-one", "portfolio_id": "p-one", "name": "Synthetic one", "property_type": "apartment"},
            {"id": "property-two", "portfolio_id": "p-two", "name": "Synthetic two", "property_type": "apartment"},
        ])
    for identifier, role, mode, portfolios in [
        ("owner", "eigentuemer", "all", []),
        ("reader-a", "readonly", "selected", ["p-one"]),
        ("reader-b", "readonly", "selected", ["p-one"]),
    ]:
        accounts.create({
            "id": identifier, "username": identifier, "email": identifier + "@example.invalid",
            "full_name": "Synthetic " + identifier, "hashed_password": "unused-synthetic-hash",
            "role": role, "is_active": True, "portfolio_access": mode,
            "portfolio_ids": portfolios, "portfolio_access_origin": "owner_assignment",
        })
    db = factory()
    store = SQLAlchemyStore(db)
    # Actual get_store resolves this binding; no auth/dependency override.
    monkeypatch.setattr(dependencies, "store", store)
    headers = {
        name: {"Authorization": "Bearer " + auth.create_access_token(name)}
        for name in ("owner", "reader-a", "reader-b")
    }
    application = FastAPI()
    application.include_router(auth_router.router, prefix="/api/v1")
    application.include_router(inbox_router.router, prefix="/api/v1")
    # The old /{notification_id} must not capture /inbox.
    application.include_router(old_notifications.router, prefix="/api/v1")
    box = SimpleNamespace(
        engine=engine, factory=factory, accounts=accounts, db=db, store=store,
        headers=headers, application=application,
    )
    try:
        with TestClient(PortfolioScopeMiddleware(application), base_url="http://127.0.0.1") as client:
            box.client = client
            yield box
    finally:
        db.close()
        assert engine.pool.checkedout() == 0
        engine.dispose()


def _insert(box, values):
    with scope_context(None), box.engine.begin() as connection:
        connection.execute(NotificationORM.__table__.insert(), values)


def _historical_read(box, actor, notice):
    # Historical own-installation facts; not execution of a write capability.
    with scope_context(None), box.engine.begin() as connection:
        connection.execute(NotificationReadStateORM.__table__.insert(), {
            "actor_id": actor, "notification_id": notice,
            "read_at": datetime(2026, 10, 3, 12, 15),
        })


def _private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Authorization"


def test_http_real_me_store_binding_personal_counts_and_false_actions(http_installation, monkeypatch):
    box = http_installation
    _insert(box, [_notice(f"visible-{index:03d}", status="read" if index % 2 else "unread",
                          read_at=datetime(2026, 10, 2)) for index in range(137)])
    _insert(box, [_notice("foreign", entity_id="property-two"), _notice("archived", status="archived")])
    _historical_read(box, "reader-a", "visible-000")

    def forbidden_stock():
        pytest.fail("HTTP inbox must use complete native projections, not a stock list")

    monkeypatch.setattr(box.store, "list_notifications", forbidden_stock)
    statements = []

    @event.listens_for(box.engine, "before_cursor_execute")
    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    me = box.client.get("/api/v1/auth/me", headers=box.headers["reader-a"])
    a = box.client.get(PATH, headers=box.headers["reader-a"], params={"limit": "11"})
    b = box.client.get(PATH, headers=box.headers["reader-b"])
    read = box.client.get(PATH, headers=box.headers["reader-a"], params={"status": "read"})
    assert me.status_code == a.status_code == b.status_code == read.status_code == 200
    assert me.json()["id"] == "reader-a" and me.json()["portfolio_ids"] == ["p-one"]
    assert a.json()["full_count"] == a.json()["unread_count"] == 136
    assert len(a.json()["items"]) == 11 and a.json()["has_more"]
    assert b.json()["full_count"] == b.json()["unread_count"] == 137
    assert read.json()["full_count"] == 1 and read.json()["unread_count"] == 136
    for response in (a, b, read):
        _private(response)
        body = response.json()
        assert body["actions"] == {"mark_all_read": False}
        assert body["snapshot_token"] is None and body["consistency"] == "live"
        assert all(item["actions"] == {"mark_read": False} for item in body["items"])
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER"))
                   for sql in statements)
    with box.engine.connect() as connection:
        assert connection.execute(select(NotificationORM.status).where(
            NotificationORM.id == "visible-001")).scalar_one() == "read"
        assert connection.execute(select(NotificationReadStateORM.actor_id)).all() == [("reader-a",)]


def test_http_scope_target_role_and_exact_filter_counts(http_installation):
    box = http_installation
    _insert(box, [_notice("visible"), _notice("warning", severity="warning"),
                  _notice("other-role"), _notice("foreign", entity_id="property-two")])
    with box.engine.begin() as connection:
        connection.execute(OperationalDispatchORM.__table__.insert(), {
            "key": "2" * 64, "notification_id": "other-role", "target_role": "verwalter",
            "family": "task_due", "entity_type": "property", "entity_id": "property-one",
        })
    all_items = box.client.get(PATH, headers=box.headers["reader-a"], params={"status": "all"})
    warnings = box.client.get(PATH, headers=box.headers["reader-a"], params={"severity": "warning"})
    assert all_items.status_code == warnings.status_code == 200
    assert all_items.json()["full_count"] == 2
    assert {item["id"] for item in all_items.json()["items"]} == {"visible", "warning"}
    assert warnings.json()["full_count"] == warnings.json()["unread_count"] == 1


def test_http_query_rejects_request_authority_and_invalid_limits(http_installation):
    box = http_installation
    for params in ({"actor_id": "owner"}, {"read_actions_enabled": "true"},
                   {"snapshot_token": "invented"}, {"limit": "0"}, {"limit": "101"},
                   {"limit": "true"}, {"after": ""}, {"status": "archived"}):
        response = box.client.get(PATH, headers=box.headers["reader-a"], params=params)
        assert response.status_code == 422, (params, response.text)


def test_http_cursor_is_actor_bound_and_grants_are_checked_at_publication(http_installation, monkeypatch):
    box = http_installation
    _insert(box, [_notice(f"notice-{index}") for index in range(7)])
    first = box.client.get(PATH, headers=box.headers["reader-a"], params={"limit": "2"})
    assert first.status_code == 200
    cursor = first.json()["next_cursor"]
    foreign = box.client.get(PATH, headers=box.headers["reader-b"], params={"limit": "2", "after": cursor})
    assert foreign.status_code == 422
    actual_list = notification_inbox.list_inbox

    def revoke_after_actual_read(*args, **kwargs):
        page = actual_list(*args, **kwargs)
        with scope_context(None):
            box.accounts.update("reader-a", {"portfolio_access": "selected", "portfolio_ids": []}, actor_id="owner")
        return page

    # Timing hook only: actual SQL read and actual independent management commit.
    monkeypatch.setattr(notification_inbox, "list_inbox", revoke_after_actual_read)
    denied = box.client.get(PATH, headers=box.headers["reader-a"])
    assert denied.status_code == 403 and "items" not in denied.json()


def test_http_missing_family_is_fixed_private_503_not_an_empty_page(http_installation):
    box = http_installation
    with box.engine.begin() as connection:
        NotificationReadStateORM.__table__.drop(connection)
    response = box.client.get(PATH, headers=box.headers["reader-a"])
    assert response.status_code == 503
    _private(response)
    assert response.headers["retry-after"] == "2"
    assert response.json()["error"]["code"] == "inbox_schema_unavailable"
    assert "items" not in response.json() and "full_count" not in response.json()
    assert "readonly-inbox.sqlite" not in response.text


def test_http_memory_store_has_no_sql_or_stock_fallback(http_installation, monkeypatch):
    box = http_installation
    monkeypatch.setattr(dependencies, "store", InMemoryStore())
    response = box.client.get(PATH, headers=box.headers["reader-a"])
    assert response.status_code == 503
    _private(response)
    assert response.json()["error"]["code"] == "inbox_persistence_unavailable"
    assert "items" not in response.json()


def test_http_memory_accounts_cannot_authorize_a_sql_inbox(http_installation, monkeypatch):
    box = http_installation
    accounts = auth.InMemoryUserStore()
    accounts.create(box.accounts.get_by_id("reader-a"))
    monkeypatch.setattr(auth, "_user_store", accounts)
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    me = box.client.get("/api/v1/auth/me", headers=box.headers["reader-a"])
    response = box.client.get(PATH, headers=box.headers["reader-a"])
    assert me.status_code == 200 and me.json()["id"] == "reader-a"
    assert response.status_code == 503
    _private(response)
    assert response.json()["error"]["code"] == "inbox_persistence_unavailable"


def test_http_actual_auth_in_a_different_database_fails_closed(http_installation, monkeypatch, tmp_path):
    box = http_installation
    other = create_engine("sqlite:///" + (tmp_path / "other-auth.sqlite").as_posix(),
                          connect_args={"check_same_thread": False}, hide_parameters=True)
    try:
        Base.metadata.create_all(other)
        factory = sessionmaker(bind=other)
        accounts = auth.SQLUserStore(factory)
        with scope_context(None), other.begin() as connection:
            connection.execute(PortfolioORM.__table__.insert(), {"id": "p-one", "name": "Other actual installation"})
        for identifier in ("owner", "reader-a"):
            accounts.create(box.accounts.get_by_id(identifier))
        monkeypatch.setattr(auth, "_user_store", accounts)
        monkeypatch.setattr(auth, "_auth_session_factory", factory)
        me = box.client.get("/api/v1/auth/me", headers=box.headers["reader-a"])
        response = box.client.get(PATH, headers=box.headers["reader-a"])
        assert me.status_code == 200 and me.json()["id"] == "reader-a"
        assert response.status_code == 503
        _private(response)
        assert response.json()["error"]["code"] == "inbox_persistence_unavailable"
        assert "other-auth.sqlite" not in response.text and "full_count" not in response.json()
    finally:
        assert other.pool.checkedout() == 0
        other.dispose()


def test_http_no_read_write_endpoints_or_readstate_side_effects(http_installation):
    box = http_installation
    _insert(box, [_notice("one")])
    for method, path in (("post", PATH), ("patch", PATH),
                         ("post", PATH + "/one/read"), ("post", PATH + "/read-all")):
        response = getattr(box.client, method)(path, headers=box.headers["reader-a"], json={"actor_id": "owner"})
        assert response.status_code in {404, 405}
    assert box.client.get(PATH).status_code == 401
    with box.engine.connect() as connection:
        assert connection.execute(select(NotificationReadStateORM.actor_id)).first() is None
        assert connection.execute(select(NotificationORM.status).where(NotificationORM.id == "one")).scalar_one() == "unread"
