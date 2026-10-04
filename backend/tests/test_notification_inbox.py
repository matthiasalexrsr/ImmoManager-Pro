"""Prepared actual SQLite/SQLUserStore source gates; no HTTP-release claim."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import MetaData, create_engine, event, select
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.db import document_version_models  # noqa: F401 — actual FK metadata, own fixture
from backend.db.access_models import ResourcePortfolioORM
from backend.db.notification_inbox_models import NotificationReadStateORM
from backend.db.operational_models import OperationalDispatchORM
from backend.db.orm_models import Base, NotificationORM, PortfolioORM, PropertyORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.notification_inbox import list_inbox, stage_read
from backend.services.notification_inbox_types import InboxPrincipal, InboxQuery
from backend.services.portfolio_scope import scope_context, scope_from_user


@pytest.fixture
def installation(tmp_path, monkeypatch, request):
    engine = create_engine("sqlite:///" + (tmp_path / "personal-inbox.sqlite").as_posix())
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
    if getattr(request, "param", False):
        # Actual legacy-null table copy; shared Base metadata remains unchanged.
        Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables
                                               if table.name != "notifications"])
        legacy = NotificationORM.__table__.to_metadata(MetaData())
        legacy.c.created_at.nullable = True
        legacy.create(engine)
    else:
        Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    accounts = auth.SQLUserStore(factory)
    monkeypatch.setattr(auth, "_user_store", accounts)
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    with engine.begin() as connection:
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
            "role": role, "is_active": True, "portfolio_access": mode, "portfolio_ids": portfolios,
            "portfolio_access_origin": "owner_assignment",
        })
    db = factory()
    box = SimpleNamespace(engine=engine, db=db, factory=factory, accounts=accounts,
                          store=SQLAlchemyStore(db))
    try:
        yield box
    finally:
        db.close()
        assert engine.pool.checkedout() == 0
        engine.dispose()


@contextmanager
def _actor(box, identifier):
    # Actual fresh native account, never a replacement auth getter/actor mock.
    with scope_context(scope_from_user(box.accounts.get_by_id(identifier))):
        yield


def _notice(identifier, **values):
    return {"id": identifier, "notification_type": "task_due", "title": identifier,
            "content": "Synthetic personal inbox evidence", "severity": "info",
            "entity_type": "property", "entity_id": "property-one", "status": "unread", **values}


def _insert(box, values):
    with scope_context(None), box.engine.begin() as connection:
        connection.execute(NotificationORM.__table__.insert(), values)


def _read_fixture(box, actor, notice):
    # Historical personal-state fixture, NOT proof of the uncomposed writehelper.
    with scope_context(None), box.engine.begin() as connection:
        connection.execute(NotificationReadStateORM.__table__.insert(), {
            "actor_id": actor, "notification_id": notice, "read_at": datetime(2026, 10, 3, 12),
        })


def test_sqlite_full_personal_counts_ignore_global_reads_and_never_scan_stock(installation, monkeypatch):
    box = installation
    _insert(box, [_notice(f"visible-{index:03d}", status="read" if index % 2 else "unread",
                          read_at=datetime(2026, 10, 2)) for index in range(137)])
    _insert(box, [_notice("foreign", entity_id="property-two"), _notice("archived", status="archived")])
    _read_fixture(box, "reader-a", "visible-000")
    def forbidden_stock():
        pytest.fail("Inbox may not materialize the stock repository")
    monkeypatch.setattr(box.store, "list_notifications", forbidden_stock)
    commands = []
    @event.listens_for(box.engine, "before_cursor_execute")
    def trace(connection, cursor, statement, parameters, context, executemany):
        commands.append(statement)
    with _actor(box, "reader-a"):
        a = list_inbox(box.store)
        read = list_inbox(box.store, InboxQuery(status="read"))
        enabled_metadata = list_inbox(box.store, read_actions_enabled=True)
    with _actor(box, "reader-b"):
        b = list_inbox(box.store)
    event.remove(box.engine, "before_cursor_execute", trace)
    assert a.full_count == a.unread_count == 136 and len(a.items) == 10 and a.has_more
    assert read.full_count == 1 and read.unread_count == 136
    assert b.full_count == b.unread_count == 137
    assert all(item.read_at is None for item in a.items + b.items)
    assert all(item.actions.mark_read is False for item in a.items + read.items + b.items)
    assert all(item.actions.mark_read is True for item in enabled_metadata.items)
    assert a.snapshot_token is None and a.consistency == "live" and not a.actions.mark_all_read
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER"))
                   for sql in commands)
    with box.engine.connect() as connection:
        assert connection.execute(select(NotificationORM.__table__.c.status).where(
            NotificationORM.__table__.c.id == "visible-001")).scalar_one() == "read"


def test_sqlite_scope_dispatch_and_exact_filter_counts_share_eligibility(installation):
    box = installation
    _insert(box, [_notice("ordinary"), _notice("warning", severity="warning"),
                  _notice("other-role"), _notice("other-portfolio", entity_id="property-two"),
                  _notice("broken", entity_id="missing"), _notice("unknown", entity_type="unknown"),
                  _notice("unlinked", entity_type=None, entity_id=None),
                  _notice("assigned-unlinked", entity_type=None, entity_id=None),
                  _notice("assigned-incomplete", entity_id=None)])
    with box.engine.begin() as connection:
        connection.execute(ResourcePortfolioORM.__table__.insert(), [
            {"resource_type": "notifications", "resource_id": identifier, "portfolio_id": "p-one"}
            for identifier in ("assigned-unlinked", "assigned-incomplete")
        ])
        connection.execute(OperationalDispatchORM.__table__.insert(), {
            "key": "1" * 64, "notification_id": "other-role", "target_role": "verwalter",
            "family": "task_due", "entity_type": "property", "entity_id": "property-one",
        })
    with _actor(box, "reader-a"):
        page = list_inbox(box.store, InboxQuery(status="all"))
        warning = list_inbox(box.store, InboxQuery(status="all", severity="warning"))
    assert {item.id for item in page.items} == {"ordinary", "warning", "assigned-unlinked"}
    assert page.full_count == page.unread_count == 3
    assert warning.full_count == warning.unread_count == 1


def test_sqlite_cursor_binds_real_actor_query_and_changed_grants(installation):
    box = installation
    _insert(box, [_notice(f"notice-{index}", created_at=datetime(2026, 10, 3, 12))
                  for index in range(7)])
    with _actor(box, "reader-a"):
        first = list_inbox(box.store, InboxQuery(limit=2))
        seen, cursor = [item.id for item in first.items], first.next_cursor
        while cursor:
            page = list_inbox(box.store, InboxQuery(limit=2, after=cursor))
            seen.extend(item.id for item in page.items)
            cursor = page.next_cursor
        assert seen == sorted([f"notice-{index}" for index in range(7)], reverse=True)
        with pytest.raises(HTTPException) as denied:
            list_inbox(box.store, InboxQuery(limit=3, after=first.next_cursor))
        assert denied.value.status_code == 422
    with _actor(box, "reader-b"):
        with pytest.raises(HTTPException) as denied:
            list_inbox(box.store, InboxQuery(limit=2, after=first.next_cursor))
        assert denied.value.status_code == 422
    box.accounts.update("reader-a", {"portfolio_access": "selected", "portfolio_ids": []}, actor_id="owner")
    with _actor(box, "reader-a"):
        with pytest.raises(HTTPException) as denied:
            list_inbox(box.store, InboxQuery(limit=2, after=first.next_cursor))
        assert denied.value.status_code == 422
        assert list_inbox(box.store).unread_count == 0


@pytest.mark.parametrize("installation", [True], indirect=True, ids=["legacy-null-schema"])
def test_sqlite_current_timestamp_zero_fraction_microsecond_and_null_keysets(installation):
    box = installation
    ids = ["notice-A", "notice-z", "notice-é", "notice-b", "notice-d"]
    with box.engine.begin() as connection:
        # Native one-statement CURRENT_TIMESTAMP, not a bound cloned fixture.
        connection.execute(NotificationORM.__table__.insert().values([_notice(item) for item in ids]))
        stamp = connection.execute(select(NotificationORM.__table__.c.created_at).limit(1)).scalar_one()
        raw = dict(connection.exec_driver_sql("SELECT id,created_at FROM notifications").all())
    assert all(len(raw[item]) == 19 for item in ids)
    bound = ["notice-Z", "notice-ä", "notice-c"]
    _insert(box, [_notice(item, created_at=stamp) for item in bound])
    _insert(box, [_notice("micro", created_at=stamp + timedelta(microseconds=1)),
                  _notice("null-b", created_at=None), _notice("null-a", created_at=None)])
    expected = ["micro"] + sorted(ids + bound, key=lambda item: item.encode("utf-8"), reverse=True) + ["null-b", "null-a"]
    with _actor(box, "reader-a"):
        seen, cursor = [], None
        for _ in range(len(expected)):
            page = list_inbox(box.store, InboxQuery(limit=2, after=cursor))
            seen.extend(item.id for item in page.items)
            cursor = page.next_cursor
            if not page.has_more:
                break
        else:
            pytest.fail("Inbox keyset did not terminate")
    assert seen == expected and len(set(seen)) == len(expected)


def test_sqlite_memory_or_different_auth_database_has_no_stock_fallback(installation, monkeypatch, tmp_path):
    box = installation
    with pytest.raises(HTTPException) as denied:
        list_inbox(SimpleNamespace())
    assert denied.value.status_code == 503
    actual_scope = scope_from_user(box.accounts.get_by_id("reader-a"))
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    with scope_context(actual_scope), pytest.raises(HTTPException) as denied:
        list_inbox(box.store)
    assert denied.value.status_code == 503
    other = create_engine("sqlite:///" + (tmp_path / "different-auth.sqlite").as_posix())
    try:
        monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(sessionmaker(bind=other)))
        with scope_context(actual_scope), pytest.raises(HTTPException) as denied:
            list_inbox(box.store)
        assert denied.value.status_code == 503
    finally:
        other.dispose()


def test_sqlite_staged_write_rejects_fake_capabilities_before_read_dml(installation):
    box = installation
    _insert(box, [_notice("target")])
    with _actor(box, "reader-a"):
        user = box.accounts.get_by_id("reader-a")
        data_only = InboxPrincipal(user["id"], user["role"], False, user["portfolio_access"],
                                   user["portfolio_access_origin"], tuple(user["portfolio_ids"]))
        for proof in (True, lambda: True, object(), data_only):
            with pytest.raises(HTTPException) as denied, box.db.begin():
                stage_read(box.db, "target", authority=proof)
            assert denied.value.status_code in {403, 503}
    with box.engine.connect() as connection:
        assert connection.execute(select(NotificationReadStateORM.__table__)).first() is None
        assert connection.execute(select(NotificationORM.__table__.c.status).where(
            NotificationORM.__table__.c.id == "target")).scalar_one() == "unread"
