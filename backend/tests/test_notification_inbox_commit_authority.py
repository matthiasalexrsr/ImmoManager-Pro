"""Prepared native SQLUser/Sid writer cases; execute only in a Root-approved slot.

Positive cases require Root's real INTERNAL registration; no fixture replaces
that missing shared prerequisite. Race/HTTP/PG release evidence remains separate.
"""

from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, event, func, select, update
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.db.access_models import ResourcePortfolioORM, UserAccessORM, UserPortfolioORM
from backend.db.auth_models import AuthSetupORM
from backend.db.document_version_models import DocumentVersionORM
from backend.db.notification_inbox_models import NotificationReadStateORM
from backend.db.operational_models import OperationalDispatchORM, OperationalLockORM
from backend.db.orm_models import Base, NotificationORM, PortfolioORM, PropertyORM, TaskORM, UnitORM, UserORM
from backend.db.session_models import AuthSessionORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import auth_sessions, notification_inbox as inbox
from backend.services import notification_inbox_commit_authority as writer
from backend.services.notification_inbox_types import InboxPrincipal
from backend.services.notification_inbox_validation import TABLE
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.request_authority import request_authority


@pytest.fixture
def read_installation(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "native-read.sqlite").as_posix()
    engine, probe = create_engine(url, hide_parameters=True), create_engine(url, hide_parameters=True)
    returned_timeouts = []

    @event.listens_for(engine, "connect")
    def configure(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=4321")

    @event.listens_for(engine, "checkin")
    def timeout_after_lease(connection, record):
        if connection is not None:
            cursor = connection.execute("PRAGMA busy_timeout")
            try:
                returned_timeouts.append(cursor.fetchone()[0])
            finally:
                cursor.close()

    db = None
    try:
        # Explicit own model fixture; this is not a migration/startup assertion.
        assert DocumentVersionORM.__tablename__ in Base.metadata.tables
        Base.metadata.create_all(engine)
        with scope_context(None), engine.begin() as connection:
            connection.execute(PortfolioORM.__table__.insert(), [
                {"id": "p-one", "name": "Synthetic permitted"},
                {"id": "p-two", "name": "Synthetic foreign"},
            ])
            connection.execute(PropertyORM.__table__.insert(), [
                {"id": "property-one", "portfolio_id": "p-one", "name": "Synthetic A",
                 "property_type": "apartment"},
                {"id": "property-two", "portfolio_id": "p-two", "name": "Synthetic B",
                 "property_type": "apartment"},
            ])
            connection.execute(UnitORM.__table__.insert(), [
                {"id": "unit-one", "property_id": "property-one", "label": "Synthetic A",
                 "unit_type": "apartment"},
                {"id": "unit-two", "property_id": "property-two", "label": "Synthetic B",
                 "unit_type": "apartment"},
            ])
            connection.execute(TaskORM.__table__.insert(), {
                "id": "task-one", "title": "Synthetic actual task", "unit_id": "unit-one",
                "property_id": "property-one",
            })
            # Fixture seeds the preexisting tick singleton; product never does.
            connection.execute(OperationalLockORM.__table__.insert(), {"id": 1, "generation": 0})
        factory = sessionmaker(bind=engine)
        accounts = auth.SQLUserStore(factory)
        monkeypatch.setattr(auth, "_user_store", accounts)
        monkeypatch.setattr(auth, "_auth_session_factory", factory)
        tokens = {}
        for actor, role, mode, grants in (
            ("owner", "eigentuemer", "all", []),
            ("all-reader", "readonly", "all", []),
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
        db = factory()
        yield SimpleNamespace(engine=engine, probe=probe, factory=factory, accounts=accounts,
                              db=db, store=SQLAlchemyStore(db), tokens=tokens,
                              returned_timeouts=returned_timeouts)
    finally:
        try:
            if db is not None:
                db.close()
            assert not writer._issued, "Issued proofs survived their owned transaction"
            assert engine.pool.checkedout() == probe.pool.checkedout() == 0
            assert returned_timeouts and set(returned_timeouts) == {4321}
        finally:
            probe.dispose()
            engine.dispose()


@contextmanager
def _actor(box, actor):
    actual = box.accounts.get_by_id(actor)
    assert actual is not None and actual["is_active"]
    with scope_context(scope_from_user(actual)):
        yield


def _registered():
    assert TABLE in writer.INTERNAL, (
        "Root must first register the real read-pair family as INTERNAL; "
        "this positive source never mocks the scope interceptor or registration"
    )


def _notice(identifier, **values):
    return {"id": identifier, "title": identifier, "content": "Synthetic owned writer",
            "notification_type": "task_due", "severity": "info", "status": "unread",
            "entity_type": "unit", "entity_id": "unit-one", **values}


def _insert(box, notices):
    with scope_context(None), box.probe.begin() as connection:
        connection.execute(NotificationORM.__table__.insert(), notices)


def _read_rows(box):
    with box.probe.connect() as connection:
        table = NotificationReadStateORM.__table__
        return connection.execute(select(table).order_by(table.c.actor_id, table.c.notification_id)).all()


def _commit(box, actor, identifier="notice"):
    with _actor(box, actor):
        return writer.commit_notification_read(box.store, identifier, access_token=box.tokens[actor])


@pytest.mark.parametrize("kind,identifier", [
    ("unit", "unit-one"), ("task", "task-one"), ("unknown", "missing"),
    ("tenant", "missing-tenant"), (None, "incomplete"), ("unknown", None), (None, None),
], ids=["unit", "task", "unknown", "tenant", "partial-id", "partial-type", "unlinked"])
def test_unrestricted_all_subjects_use_real_auth_and_insert_once(read_installation, kind, identifier):
    _registered()
    box = read_installation
    _insert(box, [_notice("notice", entity_type=kind, entity_id=identifier)])
    with _actor(box, "owner"), request_authority(box.tokens["owner"]):
        first = writer.commit_notification_read(box.store, "notice")
    second = _commit(box, "owner")
    other = _commit(box, "all-reader")
    assert first == second and first.read_at.tzinfo is None and other.read_at.tzinfo is None
    rows = _read_rows(box)
    assert {(row.actor_id, row.notification_id) for row in rows} == {
        ("owner", "notice"), ("all-reader", "notice"),
    }
    assert next(row.read_at for row in rows if row.actor_id == "owner") == first.read_at
    with box.probe.connect() as connection:
        assert connection.execute(select(NotificationORM.__table__.c.status,
            NotificationORM.__table__.c.read_at)).one() == ("unread", None)


@pytest.mark.parametrize("subject", ["portfolio", "property", "unit", "unlinked"])
def test_selected_actual_parents_and_resourcegrant_are_personal(read_installation, subject):
    _registered()
    box = read_installation
    kind, key = {
        "portfolio": ("portfolio", "p-one"), "property": ("property", "property-one"),
        "unit": ("unit", "unit-one"), "unlinked": (None, None),
    }[subject]
    _insert(box, [_notice("notice", entity_type=kind, entity_id=key)])
    if subject == "unlinked":
        with box.probe.begin() as connection:
            connection.execute(ResourcePortfolioORM.__table__.insert(), {
                "resource_type": "notifications", "resource_id": "notice", "portfolio_id": "p-one",
            })
    result = _commit(box, "reader-a")
    assert result.notification_id == "notice" and result.read_at.tzinfo is None
    assert [(row.actor_id, row.notification_id) for row in _read_rows(box)] == [("reader-a", "notice")]
    with _actor(box, "reader-b"):
        page = inbox.list_inbox(box.store)
    assert page.full_count == page.unread_count == 1
    assert page.items[0].actions.mark_read is False


def test_unrestricted_dispatch_role_is_checked_but_owner_bypasses(read_installation):
    _registered()
    box = read_installation
    _insert(box, [_notice("notice", entity_type="unknown", entity_id="missing")])
    with box.probe.begin() as connection:
        connection.execute(OperationalDispatchORM.__table__.insert(), {
            "key": "a" * 64, "notification_id": "notice", "target_role": "verwalter",
            "family": "task_due", "entity_type": "unknown", "entity_id": "missing",
        })
    with pytest.raises(HTTPException) as denied:
        _commit(box, "all-reader")
    assert denied.value.status_code == 404 and _read_rows(box) == []
    assert _commit(box, "owner").notification_id == "notice"


def test_owned_writer_does_not_commit_a_dirty_caller_session(read_installation):
    _registered()
    box = read_installation
    _insert(box, [_notice("notice")])
    pending = NotificationORM(**_notice("foreign-pending"))
    box.db.add(pending)  # No caller DML/physical writer; never flush this object.
    caller_transaction = box.db.get_transaction()
    assert _commit(box, "owner").notification_id == "notice"
    assert pending in box.db.new and box.db.get_transaction() is caller_transaction
    with box.probe.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(NotificationORM).where(
            NotificationORM.id == "foreign-pending")) == 0
    box.db.rollback()


def test_wrapper_rejects_legacy_sid_and_wrong_real_actor_before_read_dml(read_installation):
    box = read_installation
    _insert(box, [_notice("notice")])
    with _actor(box, "owner"), pytest.raises(HTTPException) as denied:
        writer.commit_notification_read(box.store, "notice", access_token=auth.create_access_token("owner"))
    assert denied.value.status_code == 401
    with _actor(box, "reader-a"), pytest.raises(HTTPException) as denied:
        writer.commit_notification_read(box.store, "notice", access_token=box.tokens["owner"])
    assert denied.value.status_code == 403 and _read_rows(box) == []


def test_nominal_constructor_subclass_and_unregistered_forges_are_denied(read_installation):
    box = read_installation
    _insert(box, [_notice("notice")])
    with pytest.raises(TypeError):
        writer.NotificationReadCommitAuthority()
    with pytest.raises(TypeError):
        type("FakeAuthority", (writer.NotificationReadCommitAuthority,), {})
    forged = object.__new__(writer.NotificationReadCommitAuthority)
    dto = InboxPrincipal(actor_id="owner", role="eigentuemer", unrestricted=True,
        portfolio_access="all", portfolio_access_origin="owner_assignment", portfolio_ids=())
    with _actor(box, "owner"):
        box.db.connection()
        for proof in (forged, True, lambda: True, dto, SimpleNamespace(actor_id="owner")):
            with pytest.raises(HTTPException) as denied:
                inbox.stage_read(box.db, "notice", authority=proof)
            assert denied.value.status_code == 403
        box.db.rollback()
    assert _read_rows(box) == []


@pytest.mark.parametrize("model", [AuthSetupORM, OperationalLockORM])
def test_missing_existing_singleton_is_not_seeded(read_installation, model):
    _registered()
    box = read_installation
    _insert(box, [_notice("notice")])
    with box.probe.begin() as connection:
        connection.execute(delete(model.__table__).where(model.__table__.c.id == 1))
    with pytest.raises(HTTPException) as denied:
        _commit(box, "owner")
    assert denied.value.status_code == 503 and _read_rows(box) == []
    with box.probe.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(model)) == 0


def test_actual_other_auth_target_is_closed_without_touching_it(read_installation, tmp_path, monkeypatch):
    _registered()
    box = read_installation
    _insert(box, [_notice("notice")])
    foreign = create_engine("sqlite:///" + (tmp_path / "other-synthetic-auth.sqlite").as_posix())
    try:
        Base.metadata.create_all(foreign)
        # Persist an actual other SQLUserStore, not an auth getter/actor stub.
        with scope_context(None):
            other = auth.SQLUserStore(sessionmaker(bind=foreign))
        with _actor(box, "owner"):
            monkeypatch.setattr(auth, "_user_store", other)
            with pytest.raises(HTTPException) as denied:
                writer.commit_notification_read(box.store, "notice", access_token=box.tokens["owner"])
        assert denied.value.status_code == 503 and _read_rows(box) == []
        with foreign.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(AuthSetupORM)) == 0
            assert connection.scalar(select(func.count()).select_from(NotificationReadStateORM)) == 0
        assert foreign.pool.checkedout() == 0
    finally:
        foreign.dispose()


def test_selected_actual_task_branch_remains_explicitly_unfenced(read_installation):
    _registered()
    box = read_installation
    _insert(box, [_notice("notice", entity_type="task", entity_id="task-one")])
    with _actor(box, "reader-a"):
        assert inbox.list_inbox(box.store).items[0].id == "notice"
    with pytest.raises(HTTPException) as denied:
        _commit(box, "reader-a")
    assert denied.value.status_code == 503
    assert denied.value.detail["code"] == "inbox_subject_fence_not_yet_supported"
    assert _read_rows(box) == []


@pytest.mark.parametrize("change", ["sid", "expiry", "active", "grant", "origin", "parent", "target", "dispatch"])
def test_actual_same_connection_change_after_read_dml_rolls_back(read_installation, monkeypatch, change):
    _registered()
    box = read_installation
    _insert(box, [_notice("notice")])
    original = inbox.stage_read
    statements = []

    @event.listens_for(box.engine, "before_cursor_execute")
    def trace(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    def after_real_stage(db, identifier, *, authority):
        result = original(db, identifier, authority=authority)
        connection = db.connection()
        assert connection.scalar(select(func.count()).select_from(NotificationReadStateORM)) == 1
        if change in {"sid", "expiry"}:
            claims = auth.decode_signed_token(box.tokens["reader-a"])
            values = {"revoked_at": auth_sessions.now()} if change == "sid" else {
                "expires_at": auth_sessions.now() - timedelta(seconds=1)}
            connection.execute(update(AuthSessionORM.__table__).where(AuthSessionORM.id == claims.sid).values(**values))
        elif change == "active":
            connection.execute(update(UserORM.__table__).where(UserORM.id == "reader-a").values(is_active=False))
        elif change == "grant":
            connection.execute(delete(UserPortfolioORM.__table__).where(UserPortfolioORM.user_id == "reader-a"))
        elif change == "origin":
            connection.execute(update(UserAccessORM.__table__).where(UserAccessORM.user_id == "reader-a")
                               .values(origin="legacy_all"))
        elif change == "parent":
            connection.execute(update(UnitORM.__table__).where(UnitORM.id == "unit-one")
                               .values(property_id="property-two"))
        elif change == "target":
            connection.execute(update(NotificationORM.__table__).where(NotificationORM.id == identifier)
                               .values(entity_id="unit-two"))
        else:
            connection.execute(OperationalDispatchORM.__table__.insert(), {
                "key": "b" * 64, "notification_id": identifier, "target_role": "verwalter",
                "family": "task_due", "entity_type": "unit", "entity_id": "unit-one",
            })
        return result

    monkeypatch.setattr(inbox, "stage_read", after_real_stage)  # Own failure transition; actual auth/proof unchanged.
    try:
        with pytest.raises(HTTPException) as denied:
            _commit(box, "reader-a")
        assert denied.value.status_code in {401, 403, 404, 409}
        assert _read_rows(box) == []
        assert any(sql.lstrip().upper().startswith("INSERT INTO NOTIFICATION_READ_STATES") for sql in statements)
        with box.probe.connect() as connection:
            assert connection.scalar(select(UnitORM.property_id).where(UnitORM.id == "unit-one")) == "property-one"
            assert connection.scalar(select(UserORM.is_active).where(UserORM.id == "reader-a")) is True
            assert connection.scalar(select(UserAccessORM.origin).where(UserAccessORM.user_id == "reader-a")) == "owner_assignment"
            assert connection.scalar(select(func.count()).select_from(UserPortfolioORM).where(
                UserPortfolioORM.user_id == "reader-a")) == 1
            assert connection.scalar(select(func.count()).select_from(OperationalDispatchORM)) == 0
            assert connection.scalar(select(NotificationORM.entity_id).where(NotificationORM.id == "notice")) == "unit-one"
            claims = auth.decode_signed_token(box.tokens["reader-a"])
            family = connection.execute(select(AuthSessionORM.__table__.c.revoked_at,
                AuthSessionORM.__table__.c.expires_at).where(AuthSessionORM.id == claims.sid)).one()
            assert family.revoked_at is None and family.expires_at > auth_sessions.now()
    finally:
        event.remove(box.engine, "before_cursor_execute", trace)


@pytest.mark.parametrize("failure", ["session_commit", "connection_commit", "savepoint", "second_stage", "raise"])
def test_closed_commit_boundaries_roll_back_actual_first_read_dml(read_installation, monkeypatch, failure):
    _registered()
    box = read_installation
    _insert(box, [_notice("notice")])
    original = inbox.stage_read
    captured = []

    def fault(db, identifier, *, authority):
        captured.append((db, authority))
        result = original(db, identifier, authority=authority)
        assert db.connection().scalar(select(func.count()).select_from(NotificationReadStateORM)) == 1
        if failure == "session_commit":
            db.commit()
        elif failure == "connection_commit":
            db.connection().commit()
        elif failure == "savepoint":
            db.begin_nested()
        elif failure == "second_stage":
            original(db, identifier, authority=authority)
        else:
            raise HTTPException(409, "Synthetic failure after real read DML")
        return result

    monkeypatch.setattr(inbox, "stage_read", fault)
    with pytest.raises(HTTPException) as denied:
        _commit(box, "reader-a")
    assert denied.value.status_code in {403, 409, 503}
    assert captured and _read_rows(box) == [] and not writer._issued
    ended_db, ended_proof = captured[0]
    with pytest.raises(HTTPException) as denied:
        writer.require_notification_read_authority(ended_db, "notice", ended_proof)
    assert denied.value.status_code == 403


def test_actual_proof_is_bound_to_target_and_owned_session(read_installation, monkeypatch):
    _registered()
    box = read_installation
    _insert(box, [_notice("notice"), _notice("other")])
    original = inbox.stage_read
    examined = []

    def inspect_real_proof(db, identifier, *, authority):
        assert type(authority) is writer.NotificationReadCommitAuthority
        examined.append(authority)
        with pytest.raises(HTTPException) as denied:
            writer.require_notification_read_authority(db, "other", authority)
        assert denied.value.status_code == 403
        with pytest.raises(HTTPException) as denied:
            writer.require_notification_read_authority(box.db, identifier, authority)
        assert denied.value.status_code == 403
        return original(db, identifier, authority=authority)

    monkeypatch.setattr(inbox, "stage_read", inspect_real_proof)
    assert _commit(box, "reader-a").notification_id == "notice"
    assert examined and not writer._issued and len(_read_rows(box)) == 1


def test_begin_immediate_precedes_actual_auth_snapshots_and_pool_timeout_is_restored(read_installation):
    _registered()
    box = read_installation
    _insert(box, [_notice("notice")])
    commands, physical_writers = [], []
    with _actor(box, "reader-a"):
        @event.listens_for(box.engine, "before_cursor_execute")
        def trace(connection, cursor, statement, parameters, context, executemany):
            commands.append(statement)
            if statement.lstrip().upper().startswith("INSERT INTO NOTIFICATION_READ_STATES"):
                physical_writers.append(id(connection.connection.driver_connection))
        try:
            writer.commit_notification_read(box.store, "notice", access_token=box.tokens["reader-a"])
        finally:
            event.remove(box.engine, "before_cursor_execute", trace)
    begin = next(index for index, sql in enumerate(commands) if sql.upper() == "BEGIN IMMEDIATE")
    first_auth = next(index for index, sql in enumerate(commands) if "FROM auth_setup" in sql)
    assert begin < first_auth and len(set(physical_writers)) == len(physical_writers) == 1
    assert set(box.returned_timeouts) == {4321}
    assert box.engine.pool.checkedout() == 0
