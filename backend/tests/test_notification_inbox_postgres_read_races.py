"""Source-only independent native races; run only with a Root-approved PG slot.

Needs actual Root INTERNAL registration and corrected owned PG proposal support.
No fake capability, auth getter, provider, ambient DB URL or server lifecycle.
"""

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Event, Thread, current_thread
from time import monotonic
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session, sessionmaker

from backend import auth
from backend.db.access_models import UserPortfolioORM
from backend.db.document_version_models import DocumentVersionORM
from backend.db.notification_inbox_models import NotificationReadStateORM
from backend.db.operational_models import OperationalDispatchORM, OperationalLockORM
from backend.db.orm_models import Base, NotificationORM, PortfolioORM, PropertyORM, UnitORM
from backend.db.session_models import AuthSessionORM
from backend.models import PropertyCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import auth_sessions, operational_schedule
from backend.services import notification_inbox as inbox
from backend.services import notification_inbox_commit_authority as writer
from backend.services.notification_inbox_types import InboxQuery
from backend.services.notification_inbox_validation import TABLE
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.request_authority import request_authority
from backend.tests.notification_inbox_pg_proposal_support import (
    CLEANUP_SECONDS,
    NODE_SECONDS,
    _close,
    _engine,
    dedicated_url,
    postgres_proposal_database,
    remaining,
)


class _Job:
    def __init__(self, name, action):
        self.value = self.error = None
        self.done = Event()
        self.thread = Thread(target=self._run, args=(action,), name=name, daemon=False)

    def _run(self, action):
        try:
            self.value = action()
        except BaseException as error:
            self.error = error
        finally:
            self.done.set()

    def start(self):
        self.thread.start()


@dataclass
class _Race:
    family: str
    order: str
    ready: Event = field(default_factory=Event)
    mutation_ready: Event = field(default_factory=Event)
    release_reader: Event = field(default_factory=Event)
    release_mutator: Event = field(default_factory=Event)
    reader_pid: int | None = None
    mutator_pid: int | None = None
    staged_at: object = None
    reader_handle: object = None
    reader: object = None
    mutator: object = None


def _await(box, signal, job=None):
    while not signal.wait(min(0.02, remaining(box.deadline))):
        if job is not None and job.done.is_set():
            if job.error is not None:
                raise job.error
            raise AssertionError("Owned worker ended before the required native boundary")


def _native_pid(connection):
    # Direct owned cursor avoids recursion inside SQLAlchemy event observation.
    cursor = connection.connection.driver_connection.cursor()
    try:
        cursor.execute("SELECT pg_catalog.pg_backend_pid()")
        return cursor.fetchone()[0]
    finally:
        cursor.close()


def _stop_jobs(box, race):
    race.release_reader.set()
    race.release_mutator.set()
    jobs = [job for job in (race.reader, race.mutator) if job and job.thread.ident is not None]
    deadline = monotonic() + CLEANUP_SECONDS
    for job in jobs:
        job.thread.join(timeout=min(2, max(0, deadline - monotonic())))
    if any(job.thread.is_alive() for job in jobs):
        # Cancel only the actual handles recorded by our disposable fixture.
        for owned in box.owned:
            for handle in owned.handles:
                if not handle.closed:
                    handle.cancel()
        if race.reader_handle is not None and not race.reader_handle.closed:
            race.reader_handle.cancel()
        for job in jobs:
            job.thread.join(timeout=max(0, deadline - monotonic()))
    assert all(not job.thread.is_alive() for job in jobs), "Owned PG race thread did not close"


@pytest.fixture
def pg_read_race(monkeypatch):
    source = dedicated_url(os.environ.get("TEST_SERVER_DATABASE_URL"))
    assert TABLE in writer.INTERNAL, "Root's actual INTERNAL registration is required, never mocked"
    # The fixture's existing deadline starts slightly later; our own operations
    # stop at this earlier complete-node boundary, including initial DDL/setup.
    deadline = monotonic() + NODE_SECONDS
    business_handles = []
    with postgres_proposal_database(source) as business:
        owned, db, box = [], None, None
        try:
            with business.connect() as connection:
                schema = connection.execute(text("SELECT current_schema()")).scalar_one()
            selected = {}
            for name in ("accounts", "sid", "mutation", "observer"):
                native = _engine(source, schema, deadline)
                owned.append(native)
                selected[name] = native.engine
            assert DocumentVersionORM.__tablename__ in Base.metadata.tables
            Base.metadata.create_all(business)  # Own model fixture; no M2 migration claim.
            with scope_context(None), business.begin() as connection:
                connection.execute(PortfolioORM.__table__.insert(), [
                    {"id": "p-one", "name": "Synthetic permitted"},
                    {"id": "p-two", "name": "Synthetic other"},
                ])
                connection.execute(PropertyORM.__table__.insert(), [
                    {"id": "property-one", "portfolio_id": "p-one", "name": "Synthetic A",
                     "property_type": "apartment"},
                    {"id": "property-two", "portfolio_id": "p-two", "name": "Synthetic B",
                     "property_type": "apartment"},
                ])
                connection.execute(UnitORM.__table__.insert(), {
                    "id": "unit-one", "property_id": "property-one", "label": "Synthetic A",
                    "unit_type": "apartment",
                })
                connection.execute(NotificationORM.__table__.insert(), {
                    "id": "notice", "notification_type": "general", "title": "Synthetic race",
                    "content": "Actual local native read boundary", "severity": "info",
                    "status": "unread", "entity_type": "unit", "entity_id": "unit-one",
                })
                connection.execute(OperationalLockORM.__table__.insert(), {"id": 1, "generation": 0})
            accounts = auth.SQLUserStore(sessionmaker(bind=selected["accounts"]))
            monkeypatch.setattr(auth, "_user_store", accounts)
            monkeypatch.setattr(auth, "_auth_session_factory", sessionmaker(bind=selected["sid"]))
            tokens = {}
            for actor, role, mode, grants in (
                ("owner", "eigentuemer", "all", []),
                ("reader-a", "readonly", "selected", ["p-one"]),
                ("reader-b", "readonly", "selected", ["p-one"]),
            ):
                with scope_context(None):
                    accounts.create({
                        "id": actor, "username": actor, "email": actor + "@example.invalid",
                        "full_name": "Synthetic " + actor, "hashed_password": "unused-synthetic-hash",
                        "role": role, "is_active": True, "portfolio_access": mode,
                        "portfolio_ids": grants, "portfolio_access_origin": "owner_assignment",
                    })
                    tokens[actor] = auth_sessions.login_pair(actor).access_token
            db = Session(bind=business)
            box = SimpleNamespace(business=business, owned=owned, engines=selected, accounts=accounts,
                db=db, store=SQLAlchemyStore(db), tokens=tokens, deadline=deadline, schema=schema, races=[])
            box.business_handles = business_handles
            yield box
            remaining(deadline)
        finally:
            failures = []
            try:
                if box is not None:
                    for race in box.races:
                        _stop_jobs(box, race)
                if db is not None:
                    db.close()
                assert not writer._issued, "Owned authority remained issued after native boundary"
            finally:
                for native in reversed(owned):
                    _close(native, failures)
                    if any(not handle.closed for handle in native.handles):
                        failures.append("owned_native_handle_open")
                assert not failures, "Owned PG race fixture cleanup failed: " + ",".join(failures)
            # The enclosing corrected helper closes business handles, proves
            # exact namespace OID/owner, and drops ONLY its own UUID schema.
    assert all(handle.closed for handle in business_handles), "Business PG handles survived owned schema cleanup"


@contextmanager
def _actor(box, actor):
    actual = box.accounts.get_by_id(actor)
    assert actual is not None and actual["is_active"]
    with scope_context(scope_from_user(actual)), request_authority(box.tokens[actor]):
        yield


def _read(box, actor="reader-a"):
    db = Session(bind=box.business)
    try:
        with _actor(box, actor):
            return writer.commit_notification_read(SQLAlchemyStore(db), "notice", access_token=box.tokens[actor])
    finally:
        db.close()


def _mutate(box, family):
    if family == "sid":
        return auth_sessions.revoke_from_token(box.tokens["reader-a"])
    if family == "grant":
        with _actor(box, "owner"):
            return box.accounts.update("reader-a", {"portfolio_access": "selected", "portfolio_ids": ["p-two"]},
                                       actor_id="owner")
    db = Session(bind=box.engines["mutation"])
    try:
        store = SQLAlchemyStore(db)
        if family == "property":
            with _actor(box, "owner"):
                original = store.get_property("property-one")
                fields = original.model_dump(include=set(PropertyCreate.model_fields))
                fields["portfolio_id"] = "p-two"
                return store.update_property("property-one", PropertyCreate(**fields))
        assert family == "dispatch"
        with scope_context(None), operational_schedule._transaction(store, captured=None) as native:
            native.db.add(OperationalDispatchORM(key="d" * 64, notification_id="notice",
                target_role="verwalter", family="general", entity_type="unit", entity_id="unit-one"))
    finally:
        db.close()


@contextmanager
def _instrument(box, race, monkeypatch):
    original_stage = inbox.stage_read

    def stage(db, identifier, *, authority):
        if current_thread() is not race.reader.thread or race.order != "read_first":
            return original_stage(db, identifier, authority=authority)
        assert type(authority) is writer.NotificationReadCommitAuthority
        result = original_stage(db, identifier, authority=authority)
        rows = db.connection().execute(select(NotificationReadStateORM.__table__)).all()
        assert len(rows) == 1 and rows[0].actor_id == "reader-a"
        race.staged_at, race.reader_pid = result.read_at, _native_pid(db.connection())
        race.reader_handle = db.connection().connection.driver_connection
        box.business_handles.append(race.reader_handle)
        race.ready.set()
        _await(box, race.release_reader)
        return result

    def reader_boundary(connection, cursor, statement, parameters, context, executemany):
        if (current_thread() is race.reader.thread and race.order == "change_first"
                and "FROM auth_setup" in statement and "FOR UPDATE" in statement
                and not race.ready.is_set()):
            race.reader_pid = _native_pid(connection)
            race.reader_handle = connection.connection.driver_connection
            box.business_handles.append(race.reader_handle)
            race.ready.set()  # Own identity probes are complete; no singleton lock acquired yet.
            _await(box, race.release_reader)

    def mutator_boundary(connection, cursor, statement, parameters, context, executemany):
        if current_thread() is not race.mutator.thread:
            return
        upper = statement.lstrip().upper()
        native_fence = (
            (race.family == "sid" and "FROM auth_sessions" in statement and "FOR UPDATE" in statement)
            or (race.family in {"grant", "property"} and upper.startswith("UPDATE AUTH_SETUP"))
            or (race.family == "dispatch" and "operational_lock" in statement
                and upper.startswith(("INSERT", "UPDATE")))
        )
        if native_fence:
            race.mutator_pid = _native_pid(connection)
            if race.order == "read_first":
                race.mutation_ready.set()  # Server blocking is confirmed separately by observer.

    def mutator_before_commit(db):
        if current_thread() is not race.mutator.thread:
            return
        bound = db.get_bind()
        engine = getattr(bound, "engine", bound)
        if engine not in box.engines.values():
            return
        db.flush()  # Actual mutation DML must exist before claiming change-first boundary.
        actual_pid = _native_pid(db.connection())
        assert race.mutator_pid == actual_pid
        if race.order == "change_first":
            race.mutation_ready.set()
            _await(box, race.release_mutator)

    monkeypatch.setattr(inbox, "stage_read", stage)  # Own boundary observation, never fake authority.
    event.listen(box.business, "before_cursor_execute", reader_boundary)
    for engine in box.engines.values():
        event.listen(engine, "before_cursor_execute", mutator_boundary)
    event.listen(Session, "before_commit", mutator_before_commit)
    try:
        yield
    finally:
        try:
            _stop_jobs(box, race)
        finally:
            monkeypatch.setattr(inbox, "stage_read", original_stage)
            event.remove(box.business, "before_cursor_execute", reader_boundary)
            for engine in box.engines.values():
                event.remove(engine, "before_cursor_execute", mutator_boundary)
            event.remove(Session, "before_commit", mutator_before_commit)


def _blocked(box, waiter, blocker, job):
    assert isinstance(waiter, int) and isinstance(blocker, int) and waiter != blocker
    poll = Event()
    with box.engines["observer"].connect() as connection:
        observer = _native_pid(connection)
        assert observer not in {waiter, blocker}
        while True:
            remaining(box.deadline)
            blockers = connection.execute(text("SELECT pg_catalog.pg_blocking_pids(:pid)"), {"pid": waiter}).scalar_one()
            if blocker in blockers:
                assert not job.done.is_set(), "Required pending worker had already ended"
                return observer
            if job.done.is_set():
                if job.error is not None:
                    raise job.error
                raise AssertionError("Worker completed without the required native blocker")
            poll.wait(min(0.01, remaining(box.deadline)))


def _reads(box):
    with box.engines["observer"].connect() as connection:
        table = NotificationReadStateORM.__table__
        return connection.execute(select(table).order_by(table.c.actor_id)).all()


def _assert_mutation(box, family):
    with box.engines["observer"].connect() as connection:
        if family == "sid":
            claims = auth.decode_signed_token(box.tokens["reader-a"])
            assert connection.scalar(select(AuthSessionORM.revoked_at).where(AuthSessionORM.id == claims.sid)) is not None
        elif family == "grant":
            assert connection.execute(select(UserPortfolioORM.portfolio_id).where(
                UserPortfolioORM.user_id == "reader-a")).scalars().all() == ["p-two"]
        elif family == "property":
            assert connection.scalar(select(PropertyORM.portfolio_id).where(PropertyORM.id == "property-one")) == "p-two"
            assert connection.scalar(select(UnitORM.property_id).where(UnitORM.id == "unit-one")) == "property-one"
        else:
            assert connection.scalar(select(OperationalDispatchORM.target_role).where(
                OperationalDispatchORM.notification_id == "notice")) == "verwalter"
        assert connection.execute(select(NotificationORM.status, NotificationORM.read_at).where(
            NotificationORM.id == "notice")).one() == ("unread", None)


def _closed_native_connections(box, pids):
    assert not writer._issued
    assert box.business.pool.checkedout() == 0
    assert all(native.engine.pool.checkedout() == 0 for native in box.owned)
    actual_pids = set(pids)
    for native in box.owned:
        actual_pids.update(handle.get_backend_pid() for handle in native.handles if not handle.closed)
    with box.business.connect() as connection:
        actual_pids.add(_native_pid(connection))
        box.business_handles.append(connection.connection.driver_connection)
    with box.engines["observer"].connect() as connection:
        # Refresh only pg_catalog stats; inspect our known PIDs and no query text.
        connection.execute(text("SELECT pg_catalog.pg_stat_clear_snapshot()"))
        states = connection.execute(text(
            "SELECT pid,state FROM pg_catalog.pg_stat_activity WHERE pid = ANY(:pids)"
        ), {"pids": list(actual_pids)}).all()
        assert all(state is not None and not state.startswith("idle in transaction") for _pid, state in states)


@pytest.mark.parametrize("family,order", [
    ("sid", "change_first"), ("sid", "read_first"),
    ("grant", "change_first"), ("grant", "read_first"),
    ("property", "change_first"), ("property", "read_first"),
    ("dispatch", "change_first"), ("dispatch", "read_first"),
], ids=["sid-change-first", "sid-read-first", "grant-change-first", "grant-read-first",
        "property-change-first", "property-read-first", "dispatch-change-first", "dispatch-read-first"])
def test_postgres_independent_read_restriction_orders(pg_read_race, monkeypatch, family, order):
    box, race = pg_read_race, _Race(family, order)
    box.races.append(race)
    race.reader = _Job("owned-inbox-reader", _read_action(box))
    race.mutator = _Job("owned-inbox-mutator", _mutation_action(box, family))
    with _instrument(box, race, monkeypatch):
        race.reader.start()
        _await(box, race.ready, race.reader)
        race.mutator.start()
        _await(box, race.mutation_ready, race.mutator)
        if order == "change_first":
            race.release_reader.set()
            observer = _blocked(box, race.reader_pid, race.mutator_pid, race.reader)
            race.release_mutator.set()
        else:
            observer = _blocked(box, race.mutator_pid, race.reader_pid, race.mutator)
            race.release_reader.set()
        _await(box, race.reader.done)
        _await(box, race.mutator.done)
        if race.mutator.error is not None:
            raise race.mutator.error
        _assert_mutation(box, family)
        if order == "change_first":
            assert isinstance(race.reader.error, HTTPException)
            assert race.reader.error.status_code == {"sid": 401, "grant": 403, "property": 404, "dispatch": 404}[family]
            assert race.reader.value is None and _reads(box) == []
        else:
            if race.reader.error is not None:
                raise race.reader.error
            rows = _reads(box)
            assert len(rows) == 1 and rows[0].actor_id == "reader-a"
            assert rows[0].read_at == race.staged_at == race.reader.value.read_at
            # A new real request after the restriction cannot reinterpret the
            # first ordered read as rolled back or create a new receipt.
            with pytest.raises(HTTPException) as denied:
                _read(box)
            assert denied.value.status_code in {401, 403, 404}
            assert _reads(box) == rows
    _closed_native_connections(box, {race.reader_pid, race.mutator_pid, observer})


def _read_action(box):
    def action():
        return _read(box)
    return action


def _mutation_action(box, family):
    def action():
        return _mutate(box, family)
    return action


def test_postgres_native_receipt_is_insert_once_per_real_actor(pg_read_race):
    box = pg_read_race
    first, replay = _read(box), _read(box)
    other = _read(box, "reader-b")
    assert first == replay and first.read_at.tzinfo is None and other.read_at.tzinfo is None
    rows = _reads(box)
    assert [(row.actor_id, row.notification_id) for row in rows] == [("reader-a", "notice"), ("reader-b", "notice")]
    assert rows[0].read_at == first.read_at
    _closed_native_connections(box, set())


def test_postgres_real_lock_timeout_cleans_own_unit_and_retry_succeeds(pg_read_race):
    box = pg_read_race
    blocker = Session(bind=box.engines["mutation"])
    try:
        with _actor(box, "owner"):
            box.accounts._lock_management(blocker)  # Existing actual management boundary; no replacement bool.
        blocking_pid = _native_pid(blocker.connection())
        with pytest.raises(HTTPException) as denied:
            _read(box)
        assert denied.value.status_code == 409 and _reads(box) == [] and not writer._issued
        assert box.business.pool.checkedout() == 0
    finally:
        blocker.rollback()
        blocker.close()
    assert _read(box).notification_id == "notice"
    assert len(_reads(box)) == 1
    _closed_native_connections(box, {blocking_pid})


def _live_get_action(box):
    def action():
        db = Session(bind=box.business)
        try:
            with _actor(box, "reader-a"):
                return inbox.list_inbox(SQLAlchemyStore(db), InboxQuery(status="all", limit=2))
        finally:
            db.close()
    return action


def _actor_binding(box):
    actual = box.accounts.get_by_id("reader-a")
    assert actual is not None and actual["is_active"]
    return scope_from_user(actual), actual["portfolio_access_origin"]


def test_postgres_live_get_rechecks_published_parent_after_actual_owner_move(pg_read_race):
    """Prepared safety assertion, not a previously observed scope-leak result."""
    box, race = pg_read_race, _Race("property", "read_first")
    box.races.append(race)
    race.reader = _Job("owned-inbox-live-get", _live_get_action(box))
    race.mutator = _Job("owned-inbox-get-parent-writer", _mutation_action(box, "property"))
    before = _actor_binding(box)

    def fetched_page(connection, cursor, statement, parameters, context, executemany):
        if current_thread() is not race.reader.thread:
            return
        compiled = getattr(context, "compiled", None)
        columns = getattr(getattr(compiled, "statement", None), "selected_columns", None)
        if columns is None or "content" not in columns.keys() or race.ready.is_set():
            return
        assert compiled.statement._limit_clause.value == 3  # Genuine bounded limit+1 page.
        race.reader_pid = _native_pid(connection)
        race.reader_handle = connection.connection.driver_connection
        box.business_handles.append(race.reader_handle)
        race.ready.set()
        _await(box, race.release_reader)

    def actual_parent_writer(connection, cursor, statement, parameters, context, executemany):
        if (current_thread() is race.mutator.thread
                and statement.lstrip().upper().startswith("UPDATE AUTH_SETUP")):
            race.mutator_pid = _native_pid(connection)

    event.listen(box.business, "after_cursor_execute", fetched_page)
    event.listen(box.engines["mutation"], "before_cursor_execute", actual_parent_writer)
    try:
        race.reader.start()
        _await(box, race.ready, race.reader)
        race.mutator.start()
        _await(box, race.mutator.done)
        if race.mutator.error is not None:
            raise race.mutator.error
        assert isinstance(race.reader_pid, int) and isinstance(race.mutator_pid, int)
        assert race.reader_pid != race.mutator_pid
        _assert_mutation(box, "property")
        assert _actor_binding(box) == before  # Actual unchanged role/grants/origin.
        race.release_reader.set()
        _await(box, race.reader.done)
        if race.reader.error is not None:
            assert isinstance(race.reader.error, HTTPException)
            assert race.reader.error.status_code in {403, 409}
        else:
            page = race.reader.value
            assert page.items == [], "GET published an item after its actual parent left the actor's scope"
            assert page.full_count == page.unread_count == 0
            assert page.consistency == "live" and page.snapshot_token is None
            assert page.actions.mark_all_read is False
        assert _reads(box) == [] and not writer._issued  # This is GET evidence only.
    finally:
        try:
            _stop_jobs(box, race)
        finally:
            event.remove(box.business, "after_cursor_execute", fetched_page)
            event.remove(box.engines["mutation"], "before_cursor_execute", actual_parent_writer)
    _closed_native_connections(box, {race.reader_pid, race.mutator_pid})
