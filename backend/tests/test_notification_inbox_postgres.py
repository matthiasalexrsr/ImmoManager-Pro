"""Prepared genuine PG live-inbox parity; explicit dedicated URL, never skips."""

import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import MetaData, create_engine, event, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from backend import auth
from backend.db.access_models import ResourcePortfolioORM, UserAccessORM
from backend.db.document_version_models import DocumentVersionORM
from backend.db.notification_inbox_models import NotificationReadStateORM
from backend.db.operational_models import OperationalDispatchORM
from backend.db.orm_models import Base, NotificationORM, PortfolioORM, PropertyORM, UnitORM
from backend.models import NotificationCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.notification_inbox import list_inbox
from backend.services.notification_inbox_types import InboxQuery
from backend.services.portfolio_scope import scope_context, scope_from_user


def _dedicated_url():
    source = os.environ.get("TEST_SERVER_DATABASE_URL")
    if not source:
        pytest.fail("An explicit dedicated TEST_SERVER_DATABASE_URL is required; no skip/fallback")
    url = make_url(source)
    if (url.get_backend_name() != "postgresql" or url.host != "127.0.0.1"
            or url.port != 58112 or url.database != "immo_ci" or url.username != "immo_ci"
            or set(url.query) - {"options"}):
        pytest.fail("PG inbox parity requires the dedicated local immo_ci target on port 58112")
    return url


def _engine(url, schema, *, size):
    return create_engine(
        url.update_query_dict({"options": (
            f"-csearch_path={schema} -ctimezone=UTC -cstatement_timeout=20000 -clock_timeout=5000"
        )}),
        hide_parameters=True, pool_size=size, max_overflow=0, pool_timeout=5,
        connect_args={"connect_timeout": 5},
    )


@pytest.fixture
def postgres_inbox(monkeypatch, request):
    url = _dedicated_url()  # Validate before any connection or DDL.
    schema = "inbox_pg_" + uuid4().hex
    admin = _engine(url, "pg_catalog", size=1)
    engines, db, created, leaked = [], None, False, []
    try:
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            created = True
        engine = _engine(url, schema, size=3)
        engines.append(engine)
        probe = _engine(url, schema, size=1)
        engines.append(probe)
        # This explicit feature fixture registers required real FK metadata.
        # create_all here proves models, not migration/registry/runtime activation.
        assert DocumentVersionORM.__tablename__ in Base.metadata.tables
        if getattr(request, "param", False):
            # PG requires notifications to exist before the read-pair FK DDL.
            legacy = NotificationORM.__table__.to_metadata(MetaData())
            legacy.c.created_at.nullable = True
            legacy.create(engine)
        Base.metadata.create_all(engine)
        assert NotificationORM.__table__.c.created_at.nullable is False
        with engine.connect() as first, probe.connect() as second:
            actual = [connection.execute(text(
                "SELECT current_database(), current_schema(), pg_backend_pid(), "
                "current_setting('TimeZone')"
            )).one() for connection in (first, second)]
        assert all(row[0] == "immo_ci" and row[1] == schema and row[3] == "UTC" for row in actual)
        assert actual[0][2] != actual[1][2]
        with scope_context(None), engine.begin() as connection:
            connection.execute(PortfolioORM.__table__.insert(), [
                {"id": "p-one", "name": "Synthetic PG allowed"},
                {"id": "p-two", "name": "Synthetic PG other"},
            ])
            connection.execute(PropertyORM.__table__.insert(), [
                {"id": "property-one", "portfolio_id": "p-one", "name": "Synthetic one",
                 "property_type": "apartment"},
                {"id": "property-two", "portfolio_id": "p-two", "name": "Synthetic two",
                 "property_type": "apartment"},
            ])
            connection.execute(UnitORM.__table__.insert(), [
                {"id": "unit-one", "property_id": "property-one", "label": "Synthetic A",
                 "unit_type": "apartment"},
                {"id": "unit-two", "property_id": "property-two", "label": "Synthetic B",
                 "unit_type": "apartment"},
            ])
        factory = sessionmaker(bind=engine)
        accounts = auth.SQLUserStore(factory)
        monkeypatch.setattr(auth, "_user_store", accounts)
        monkeypatch.setattr(auth, "_auth_session_factory", factory)
        for identifier, role, mode, portfolios in (
            ("owner", "eigentuemer", "all", []),
            ("reader-a", "readonly", "selected", ["p-one"]),
            ("reader-b", "readonly", "selected", ["p-one"]),
        ):
            with scope_context(None):
                accounts.create({
                    "id": identifier, "username": identifier,
                    "email": identifier + "@example.invalid", "full_name": "Synthetic " + identifier,
                    "hashed_password": "unused-synthetic-hash", "role": role, "is_active": True,
                    "portfolio_access": mode, "portfolio_ids": portfolios,
                    "portfolio_access_origin": "owner_assignment",
                })
        db = factory()
        yield SimpleNamespace(engine=engine, probe=probe, db=db, accounts=accounts,
                              store=SQLAlchemyStore(db), schema=schema)
    finally:
        try:
            if db is not None:
                db.close()
        finally:
            try:
                for selected in engines:
                    if selected.pool.checkedout():
                        leaked.append(selected.pool.checkedout())
                    selected.dispose()
            finally:
                try:
                    if created:
                        assert re.fullmatch(r"inbox_pg_[0-9a-f]{32}", schema)
                        with admin.begin() as connection:
                            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
                finally:
                    admin.dispose()
        assert not leaked, f"Own PostgreSQL inbox connections were not returned: {leaked}"


@contextmanager
def _actor(box, identifier):
    # Actual persisted identity, Access and Grants; no replacement auth getter.
    user = box.accounts.get_by_id(identifier)
    assert user is not None and user["is_active"]
    with scope_context(scope_from_user(user)):
        yield


def _notice(identifier, **values):
    return {"id": identifier, "notification_type": "task_due", "title": identifier,
            "content": "Synthetic PG inbox proof", "severity": "info", "status": "unread",
            "entity_type": "unit", "entity_id": "unit-one", **values}


def _insert(box, values):
    with scope_context(None), box.probe.begin() as connection:
        connection.execute(NotificationORM.__table__.insert(), values)


def _historical_reads(box, pairs):
    # Actual historical-state fixture; never a positive stage_read/capability claim.
    with scope_context(None), box.probe.begin() as connection:
        connection.execute(NotificationReadStateORM.__table__.insert(), [
            {"actor_id": actor, "notification_id": notice, "read_at": datetime(2026, 10, 3, 12)}
            for actor, notice in pairs
        ])


def _walk(box, query, expected, *, full_count, unread_count):
    seen, cursor, pages = [], None, 0
    while True:
        page = list_inbox(box.store, query.model_copy(update={"after": cursor}))
        pages += 1
        assert page.full_count == full_count and page.unread_count == unread_count
        assert len(page.items) <= query.limit
        assert page.snapshot_token is None and page.consistency == "live"
        assert page.actions.mark_all_read is False
        assert all(item.actions.mark_read is False for item in page.items)
        seen.extend(item.id for item in page.items)
        assert page.has_more == (len(seen) < len(expected))
        if not page.has_more:
            assert page.next_cursor is None
            break
        assert page.next_cursor is not None and page.next_cursor != cursor
        cursor = page.next_cursor
        assert pages <= len(expected) // query.limit + 1, "Keyset failed to terminate"
    assert seen == expected and len(set(seen)) == len(expected)
    return pages


def test_postgres_10002_personal_counts_and_all_live_keysets(postgres_inbox, monkeypatch):
    box = postgres_inbox
    count, stamp = 10002, datetime(2026, 10, 3, 12)
    notices = [_notice(
        f"bulk-{index:05d}", created_at=stamp,
        status="read" if index % 2 else "unread", read_at=stamp if index % 2 else None,
        notification_type="task_due" if index % 2 == 0 else "contract_expiry",
        severity="warning" if index % 4 == 0 else "info",
    ) for index in range(count)]
    notices[-1].update(entity_type=None, entity_id=None)
    _insert(box, notices)
    _insert(box, [
        _notice("foreign", entity_id="unit-two"), _notice("broken", entity_id="missing-unit"),
        _notice("unknown", entity_type="unknown"), _notice("unlinked", entity_type=None, entity_id=None),
        _notice("incomplete-assigned", entity_id=None), _notice("other-role"),
        _notice("archived", status="archived"),
    ])
    with box.probe.begin() as connection:
        connection.execute(ResourcePortfolioORM.__table__.insert(), [
            {"resource_type": "notifications", "resource_id": identifier, "portfolio_id": "p-one"}
            for identifier in ("bulk-10001", "incomplete-assigned")
        ])
        connection.execute(OperationalDispatchORM.__table__.insert(), [
            {"key": "1" * 64, "notification_id": "other-role", "target_role": "verwalter",
             "family": "task_due", "entity_type": "unit", "entity_id": "unit-one"},
            {"key": "2" * 64, "notification_id": "bulk-10000", "target_role": "readonly",
             "family": "task_due", "entity_type": "unit", "entity_id": "unit-one"},
        ])
    _historical_reads(box, [("reader-a", "bulk-00000"), ("reader-a", "bulk-00004"),
                            ("reader-b", "bulk-00000")])

    def forbidden_stock():
        pytest.fail("Personal inbox must not materialize a stock repository")

    monkeypatch.setattr(box.store, "list_notifications", forbidden_stock)
    projection_limits = []

    @event.listens_for(box.engine, "before_cursor_execute")
    def bounded_read_only(connection, cursor, statement, parameters, context, executemany):
        assert not statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER"))
        compiled = getattr(context, "compiled", None)
        selected = getattr(getattr(compiled, "statement", None), "selected_columns", None)
        if selected is not None and "content" in selected.keys():
            limit = getattr(compiled.statement, "_limit_clause", None)
            assert limit is not None, "Actual Notification projection was unbounded"
            projection_limits.append(limit.value)

    expected = [f"bulk-{index:05d}" for index in range(count - 1, -1, -1)]
    a_read = {"bulk-00000", "bulk-00004"}
    filtered = [identifier for identifier in expected if int(identifier[5:]) % 4 == 0]
    page_count = 0
    try:
        with _actor(box, "reader-a"):
            for query, ids, full, unread in (
                (InboxQuery(status="all", limit=100), expected, count, count - 2),
                (InboxQuery(status="unread", limit=100),
                 [identifier for identifier in expected if identifier not in a_read], count - 2, count - 2),
                (InboxQuery(status="read", limit=100),
                 [identifier for identifier in expected if identifier in a_read], 2, count - 2),
                (InboxQuery(status="all", notification_type="task_due", severity="warning", limit=100),
                 filtered, 2501, 2499),
                (InboxQuery(status="unread", notification_type="task_due", severity="warning", limit=100),
                 [identifier for identifier in filtered if identifier not in a_read], 2499, 2499),
                (InboxQuery(status="read", notification_type="task_due", severity="warning", limit=100),
                 [identifier for identifier in filtered if identifier in a_read], 2, 2499),
            ):
                page_count += _walk(box, query, ids, full_count=full, unread_count=unread)
        with _actor(box, "reader-b"):
            other = list_inbox(box.store, InboxQuery(status="all", limit=100))
            assert other.full_count == count and other.unread_count == count - 1
    finally:
        event.remove(box.engine, "before_cursor_execute", bounded_read_only)
    assert projection_limits == [101] * (page_count + 1)
    with box.probe.connect() as connection:
        table = NotificationORM.__table__
        assert connection.scalar(select(func.count()).where(table.c.status == "read")) == 5001
        assert connection.execute(select(table.c.status, table.c.read_at).where(
            table.c.id == "bulk-00001")).one() == ("read", stamp)
        assert connection.scalar(select(func.count()).select_from(NotificationReadStateORM)) == 3


def test_postgres_actual_actor_grant_and_origin_cursor_bindings(postgres_inbox):
    box = postgres_inbox
    _insert(box, [_notice(f"notice-{index}", created_at=datetime(2026, 10, 3, 12)) for index in range(7)])
    _insert(box, [_notice("foreign", entity_id="unit-two")])
    old_scope = scope_from_user(box.accounts.get_by_id("reader-a"))
    with _actor(box, "reader-a"):
        first = list_inbox(box.store, InboxQuery(status="all", limit=2))
        assert first.next_cursor is not None
        for query in (
            InboxQuery(status="all", limit=3), InboxQuery(status="read", limit=2),
            InboxQuery(status="all", notification_type="task_due", limit=2),
            InboxQuery(status="all", severity="info", limit=2),
        ):
            with pytest.raises(HTTPException) as denied:
                list_inbox(box.store, query.model_copy(update={"after": first.next_cursor}))
            assert denied.value.status_code == 422
    with _actor(box, "reader-b"), pytest.raises(HTTPException) as denied:
        list_inbox(box.store, InboxQuery(status="all", limit=2, after=first.next_cursor))
    assert denied.value.status_code == 422
    with _actor(box, "owner"):
        changed = box.accounts.update("reader-a", {"portfolio_access": "selected", "portfolio_ids": ["p-two"]},
                                      actor_id="owner")
    assert changed["portfolio_ids"] == ["p-two"]
    with scope_context(old_scope), pytest.raises(HTTPException) as denied:
        list_inbox(box.store)
    assert denied.value.status_code == 403
    with _actor(box, "reader-a"):
        with pytest.raises(HTTPException) as denied:
            list_inbox(box.store, InboxQuery(status="all", limit=2, after=first.next_cursor))
        assert denied.value.status_code == 422
        assert [item.id for item in list_inbox(box.store).items] == ["foreign"]

    before = box.accounts.get_by_id("owner")
    with _actor(box, "owner"):
        owner_page = list_inbox(box.store, InboxQuery(status="all", limit=2))
    assert owner_page.next_cursor is not None and before["portfolio_access_origin"] == "owner_assignment"
    # Actual independent stored provenance change to an existing migration value.
    # This is a native data fixture, not a claimed account-management HTTP command.
    with box.probe.begin() as connection:
        changed = connection.execute(update(UserAccessORM.__table__).where(
            UserAccessORM.__table__.c.user_id == "owner").values(origin="legacy_all"))
        assert changed.rowcount == 1
    after = box.accounts.get_by_id("owner")
    assert after["portfolio_access_origin"] == "legacy_all"
    assert scope_from_user(before) == scope_from_user(after)
    with _actor(box, "owner"), pytest.raises(HTTPException) as denied:
        list_inbox(box.store, InboxQuery(status="all", limit=2, after=owner_page.next_cursor))
    assert denied.value.status_code == 422


@pytest.mark.parametrize("postgres_inbox", [True], indirect=True, ids=["legacy-null-schema"])
def test_postgres_native_ties_microseconds_and_legacy_null_keysets(postgres_inbox):
    box, table = postgres_inbox, NotificationORM.__table__
    ids = ["notice-A", "notice-z", "notice-é", "notice-b", "notice-d"]
    with box.probe.begin() as connection:
        # Genuine one-statement func.now default, no bound current-time clone.
        connection.execute(table.insert().values([_notice(identifier) for identifier in ids]))
        rows = dict(connection.execute(select(table.c.id, table.c.created_at)).all())
    assert len(rows) == 5 and len(set(rows.values())) == 1
    stamp = rows[ids[0]]
    assert isinstance(stamp, datetime) and stamp.tzinfo is None
    zero = stamp.replace(microsecond=0)
    additions = [
        _notice("notice-Z", created_at=stamp), _notice("notice-ä", created_at=stamp),
        _notice("micro", created_at=stamp + timedelta(microseconds=1)),
        _notice("zero-Z", created_at=zero), _notice("zero-é", created_at=zero),
        _notice("zero-micro", created_at=zero + timedelta(microseconds=1)),
        _notice("null-b", created_at=None), _notice("null-a", created_at=None),
    ]
    _insert(box, additions)
    rows.update({row["id"]: row["created_at"] for row in additions})
    expected = sorted(rows, key=lambda identifier: (
        rows[identifier] is not None, rows[identifier] or datetime.min, identifier.encode("utf-8")
    ), reverse=True)
    with _actor(box, "reader-a"):
        _walk(box, InboxQuery(status="all", limit=2), expected,
              full_count=len(rows), unread_count=len(rows))
    with box.probe.connect() as connection:
        actual = dict(connection.execute(select(table.c.id, table.c.created_at)).all())
    assert actual == rows and actual["zero-micro"].microsecond == 1


def _utc_clock(box):
    with box.probe.connect() as connection:
        return connection.execute(text("SELECT timezone('UTC', clock_timestamp())")).scalar_one()


@pytest.mark.parametrize("zone", ["Europe/Berlin", "America/New_York"])
def test_postgres_create_notification_default_is_naive_utc_in_session_zone(postgres_inbox, zone):
    box = postgres_inbox
    # Retain this physical writer connection across the repository's real commit
    # so final zone cleanup cannot reset an unrelated pooled connection instead.
    with box.engine.connect() as writer_connection:
        assert not writer_connection.in_transaction()
        db = Session(bind=writer_connection)
        try:
            before = _utc_clock(box)  # Before writer BEGIN, not after transaction now().
            with _actor(box, "owner"):
                configured = db.execute(text(
                    "SELECT set_config('TimeZone', :zone, false)"
                ), {"zone": zone}).scalar_one()
                assert configured == zone
                item = SQLAlchemyStore(db).create_notification(NotificationCreate(
                    notification_type="general", title="Synthetic UTC default " + zone,
                    content="Actual store create without a caller timestamp",
                    entity_type="unit", entity_id="unit-one",
                ))
            assert not db.in_transaction() and not writer_connection.in_transaction()
            after = _utc_clock(box)
            with box.probe.connect() as connection:
                stored = connection.execute(select(NotificationORM.__table__.c.created_at).where(
                    NotificationORM.__table__.c.id == item.id)).scalar_one()
            with _actor(box, "owner"):
                page = list_inbox(box.store, InboxQuery(status="all"))
            assert len(page.items) == 1 and page.items[0].id == item.id
            assert all(value.tzinfo is None for value in (item.created_at, stored, page.items[0].created_at))
            assert item.created_at == stored == page.items[0].created_at
            assert before <= stored <= after, (
                f"Actual create_notification default in {zone} violated naiveUTC: "
                f"UTC window {before.isoformat()}..{after.isoformat()}, stored {stored.isoformat()}"
            )
        finally:
            db.rollback()
            writer_connection.rollback()
            try:
                writer_connection.execute(text("SELECT set_config('TimeZone', 'UTC', false)"))
                writer_connection.commit()
            finally:
                db.close()
