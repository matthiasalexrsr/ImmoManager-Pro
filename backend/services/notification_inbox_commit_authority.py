"""Owned native single-read transaction; nominal proofs are never request data."""

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock, get_ident
from weakref import WeakKeyDictionary

from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from .. import auth
from ..db.access_models import ResourcePortfolioORM, UserAccessORM, UserPortfolioORM
from ..db.auth_models import AuthSetupORM
from ..db.operational_models import OperationalDispatchORM, OperationalLockORM
from ..db.orm_models import Base, NotificationORM, UserORM
from ..db.session_models import AuthSessionORM
from ..permissions import ROLE_CAPABILITIES
from ..repositories.sql_store import SQLAlchemyStore
from ..storage import ValidationError
from . import notification_inbox as inbox
from .auth_sessions import VERSION, factory as sid_factory
from .contract_occupancy import lock_location
from .measurement_history import lock_measurement_property
from .notification_inbox_read_support import SELECTED_SUBJECT_TABLES, notification_read_subject_hint
from .notification_inbox_types import InboxPrincipal, InboxQuery, NotificationReadResult
from .notification_inbox_validation import TABLE
from .portfolio_references import csv_parents
from .portfolio_scope import INTERNAL, RESOURCE_ALIASES, _parents, current_scope, scoped_clause
from .request_authority import _request_credential

_OPERATION = "notification_inbox.mark_read/1"
_issued = WeakKeyDictionary()
_registry_lock = RLock()


class NotificationReadCommitAuthority:
    """Opaque issuer-registered identity; no public construction or subclass."""

    __slots__ = ("__weakref__",)

    def __new__(cls, *args, **kwargs):
        raise TypeError("Only the owned notification-read writer can issue authority")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("Notification-read authority cannot be subclassed")

    def __reduce__(self):
        raise TypeError("Notification-read authority cannot be serialized")


@dataclass(frozen=True)
class _Node:
    table: str
    identifier: str
    references: tuple


@dataclass(frozen=True)
class _Subject:
    notification: tuple
    nodes: tuple[_Node, ...] = ()
    portfolio_id: str | None = None
    resource_grant: bool = False
    dispatch: tuple | None = None


@dataclass
class _State:
    db: Session
    transaction: object
    connection: object
    native_transaction: object
    accounts: object
    family_factory: object
    target: tuple
    claims: tuple
    principal: InboxPrincipal
    subject: _Subject
    thread: int
    sid_expires: datetime
    operation: str = _OPERATION
    phase: str = "staging"
    checks: int = 0
    valid: bool = True


def _denied():
    return HTTPException(401, "Sitzung abgelaufen oder widerrufen. Bitte erneut anmelden.",
                         headers={"WWW-Authenticate": "Bearer"})


def _closed(code="inbox_commit_authority_unavailable"):
    return inbox._unavailable(code)


def _conflict():
    return HTTPException(409, "Benachrichtigung oder Berechtigungen werden gerade geändert. Neu laden.")


def _signed(token):
    if not isinstance(token, str) or not token:
        raise _denied()
    claims = auth.decode_signed_token(token)
    if (claims.type != "access" or not claims.sub.strip() or not claims.sid
            or type(claims.session_version) is not int or claims.session_version != VERSION
            or claims.exp.tzinfo is None):
        raise _denied()
    # No credential/jti/refresh-generation is stored in a proof or Session.info.
    return claims.sub, claims.sid, claims.session_version, claims.exp.astimezone(timezone.utc).replace(tzinfo=None)


def _unexpired(claims, sid_expires):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if (not isinstance(sid_expires, datetime) or sid_expires.tzinfo is not None
            or claims[3] <= now or sid_expires <= now):
        raise _denied()


def _frame(state, *, physical_commit=False):
    db, connection = state.db, state.connection
    if (not state.valid or state.thread != get_ident() or state.operation != _OPERATION
            or db.get_transaction() is not state.transaction or db.in_nested_transaction()
            or connection.closed or connection.invalidated or not connection.in_transaction()
            or connection.get_transaction() is not state.native_transaction
            or connection.get_nested_transaction() is not None
            or not state.native_transaction.is_active):
        raise HTTPException(403, "Der Transaktionsbeleg ist nicht mehr gültig.")
    # SessionTransaction is PREPARED at Connection.commit, not ACTIVE anymore.
    if not physical_commit and (not db.is_active or not state.transaction.is_active):
        raise HTTPException(403, "Der Transaktionsbeleg ist nicht mehr gültig.")
    if db.new or db.dirty or db.deleted:
        raise _closed()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        raise HTTPException(403, "Die native Transaktion ist bereits beendet.")


def _same_factories(connection, caller, owned, accounts, family):
    actual = inbox._identity(connection)
    for selected in dict.fromkeys((accounts._session_factory, family)):
        checked = selected()
        if not isinstance(checked, Session) or checked is caller or checked is owned:
            # A scoped factory must not lend/close the request's foreign Session.
            raise _closed()
        if checked.in_transaction() or checked.new or checked.dirty or checked.deleted:
            # Do not roll back/close an already borrowed scoped Session either.
            raise _closed()
        try:
            with checked.no_autoflush:
                if inbox._identity(checked.connection()) != actual:
                    raise _closed()
        finally:
            remove = getattr(selected, "remove", None)
            if callable(remove):
                remove()
            else:
                checked.close()
    return actual


def _singleton(connection, model):
    table = model.__table__
    if connection.execute(select(table.c.id).where(table.c.id == 1).with_for_update()).first() is None:
        raise _closed("inbox_required_fence_unavailable")


def _sid(connection, claims, *, lock=False):
    table = AuthSessionORM.__table__
    statement = select(table.c.user_id, table.c.revoked_at, table.c.expires_at).where(table.c.id == claims[1])
    row = connection.execute(statement.with_for_update() if lock else statement).one_or_none()
    if row is None or row.user_id != claims[0] or row.revoked_at is not None:
        raise _denied()
    _unexpired(claims, row.expires_at)
    return row.expires_at


def _actor_access(connection, principal):
    table = UserAccessORM.__table__
    row = connection.execute(select(table.c.mode, table.c.origin).where(
        table.c.user_id == principal.actor_id).with_for_update()).one_or_none()
    if row is None:
        raise _closed("inbox_required_fence_unavailable")
    expected_mode = "all" if principal.role == "eigentuemer" else principal.portfolio_access
    if row.mode != expected_mode or row.origin != principal.portfolio_access_origin:
        raise _conflict()


def _node(connection, name, identifier, principal, *, lock=False):
    if name not in SELECTED_SUBJECT_TABLES or not isinstance(identifier, str) or not identifier:
        raise _closed("inbox_subject_fence_not_yet_supported")
    table = Base.metadata.tables[name]
    if csv_parents(table) or ("entity_type" in table.c and "entity_id" in table.c):
        raise _closed("inbox_subject_fence_not_yet_supported")
    parents = _parents(table)
    if any(parent not in SELECTED_SUBJECT_TABLES for parent in parents.values()):
        raise _closed("inbox_subject_fence_not_yet_supported")
    statement = select(table.c.id, *(table.c[field] for field in sorted(parents))).where(table.c.id == identifier)
    scoped = scoped_clause(table, scope=inbox._scope(principal))
    if scoped is not None:
        statement = statement.where(scoped)
    row = connection.execute(statement.with_for_update() if lock else statement).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "Benachrichtigung nicht gefunden.")
    return _Node(name, identifier, tuple((field, parents[field], row[field]) for field in sorted(parents)))


def _nodes(connection, name, identifier, principal, seen=None):
    seen = set() if seen is None else seen
    if (name, identifier) in seen:
        raise _closed("inbox_subject_fence_not_yet_supported")
    seen.add((name, identifier))
    node = _node(connection, name, identifier, principal)
    nodes = [node]
    for _field, parent, key in node.references:
        if key is not None:
            nodes.extend(_nodes(connection, parent, key, principal, seen))
    return tuple(nodes)


def _notification(connection, principal, identifier, *, lock=False):
    table = NotificationORM.__table__
    statement = select(table.c.id, table.c.status, table.c.entity_type, table.c.entity_id).where(
        table.c.id == identifier, inbox._eligibility(table, principal, InboxQuery()))
    row = connection.execute(statement.with_for_update() if lock else statement).one_or_none()
    if row is None:
        raise HTTPException(404, "Benachrichtigung nicht gefunden.")
    return tuple(row)


def _discover(connection, principal, identifier):
    notice = _notification(connection, principal, identifier)
    if not notification_read_subject_hint(status=notice[1], unrestricted=principal.unrestricted,
            entity_type=notice[2], entity_id=notice[3], resource_aliases=RESOURCE_ALIASES):
        raise _closed("inbox_subject_fence_not_yet_supported")
    if principal.unrestricted:
        return _Subject(notice)
    if notice[2] is None and notice[3] is None:
        grants = ResourcePortfolioORM.__table__
        portfolio = connection.scalar(select(grants.c.portfolio_id).where(
            grants.c.resource_type == "notifications", grants.c.resource_id == identifier,
            grants.c.portfolio_id.in_(principal.portfolio_ids)).order_by(grants.c.portfolio_id).limit(1))
        if portfolio is None:
            raise HTTPException(404, "Benachrichtigung nicht gefunden.")
        return _Subject(notice, (_node(connection, "portfolios", portfolio, principal),), portfolio, True)
    nodes = _nodes(connection, RESOURCE_ALIASES[notice[2]], notice[3], principal)
    portfolios = {node.identifier for node in nodes if node.table == "portfolios"}
    if len(portfolios) != 1:
        raise _closed("inbox_subject_fence_not_yet_supported")
    return _Subject(notice, nodes, next(iter(portfolios)))


def _grant(connection, principal, subject, *, lock=False):
    if principal.unrestricted:
        return
    table = UserPortfolioORM.__table__
    statement = select(table.c.portfolio_id).where(
        table.c.user_id == principal.actor_id, table.c.portfolio_id == subject.portfolio_id)
    if connection.execute(statement.with_for_update() if lock else statement).first() is None:
        raise _conflict()
    if subject.resource_grant:
        table = ResourcePortfolioORM.__table__
        statement = select(table.c.portfolio_id).where(
            table.c.resource_type == "notifications", table.c.resource_id == subject.notification[0],
            table.c.portfolio_id == subject.portfolio_id)
        if connection.execute(statement.with_for_update() if lock else statement).first() is None:
            raise _conflict()


def _dispatch(connection, identifier, *, lock=False):
    table = OperationalDispatchORM.__table__
    statement = select(table.c.key, table.c.target_role, table.c.family,
                       table.c.entity_type, table.c.entity_id).where(table.c.notification_id == identifier).limit(2)
    result = connection.execute(statement.with_for_update() if lock else statement).all()
    if len(result) > 1:
        raise _closed("inbox_required_fence_unavailable")
    return tuple(result[0]) if result else None


def _freeze(db, principal, subject):
    connection, active = db.connection(), SQLAlchemyStore(db)
    # Existing measurement boundary is acquired before Location/parent rows.
    for node in subject.nodes:
        if node.table == "properties":
            lock_measurement_property(active, node.identifier)
    for node in subject.nodes:
        if node.table == "portfolios" and _node(connection, node.table, node.identifier, principal, lock=True) != node:
            raise _conflict()
    units = [node for node in subject.nodes if node.table == "units"]
    if units:
        unit = units[0]
        parent = next(key for field, _table, key in unit.references if field == "property_id")
        try:
            lock_location(active, parent, unit.identifier)
        except ValidationError:
            raise _conflict() from None
    else:
        for node in subject.nodes:
            if node.table == "properties":
                _node(connection, node.table, node.identifier, principal, lock=True)
    _grant(connection, principal, subject, lock=True)
    for node in subject.nodes:
        if _node(connection, node.table, node.identifier, principal) != node:
            raise _conflict()
    if _notification(connection, principal, subject.notification[0], lock=True) != subject.notification:
        raise _conflict()
    return _Subject(subject.notification, subject.nodes, subject.portfolio_id, subject.resource_grant,
                    _dispatch(connection, subject.notification[0], lock=True))


def _refresh(state):
    _frame(state)
    if inbox._accounts() is not state.accounts or sid_factory() is not state.family_factory:
        raise _closed()
    if inbox._identity(state.connection) != state.target:
        raise _closed()
    state.db.expire_all()
    if inbox._principal(state.accounts, state.db, state.principal.actor_id) != state.principal:
        raise _conflict()
    state.sid_expires = _sid(state.connection, state.claims)
    _grant(state.connection, state.principal, state.subject)
    for node in state.subject.nodes:
        if _node(state.connection, node.table, node.identifier, state.principal) != node:
            raise _conflict()
    if (_notification(state.connection, state.principal, state.subject.notification[0]) != state.subject.notification
            or _dispatch(state.connection, state.subject.notification[0]) != state.subject.dispatch):
        raise _conflict()


def require_notification_read_authority(db, notification_id, proof) -> InboxPrincipal:
    if type(proof) is not NotificationReadCommitAuthority:
        raise HTTPException(403, "Ein tatsächlicher CommitAuthoritybeleg ist erforderlich.")
    with _registry_lock:
        state = _issued.get(proof)
        if (state is None or state.db is not db or state.subject.notification[0] != notification_id
                or state.phase != "staging" or state.checks >= 2):
            raise HTTPException(403, "Der Transaktionsbeleg gehört nicht zu diesem Einzelread.")
    _refresh(state)
    with _registry_lock:
        state.checks += 1
    return state.principal


def commit_notification_read(store, notification_id: str, *, access_token=None) -> NotificationReadResult:
    """Own one real transaction; caller never receives the proof or its Session."""
    if not isinstance(notification_id, str) or not notification_id.strip():
        raise HTTPException(404, "Benachrichtigung nicht gefunden.")
    credential = _request_credential.get() if access_token is None else access_token
    claims = _signed(credential)
    captured = current_scope()
    if captured is None or captured.user_id != claims[0]:
        raise HTTPException(403, "Eine tatsächliche Benutzerbindung ist erforderlich.")
    accounts, family = inbox._accounts(), sid_factory()
    caller = getattr(store, "db", None)
    if not isinstance(caller, Session) or family is None or TABLE not in INTERNAL:
        raise _closed("inbox_commit_registration_unavailable")
    bind = caller.get_bind()
    if not isinstance(bind, Engine) or bind.dialect.name not in {"sqlite", "postgresql"}:
        raise _closed()
    db = state = proof = connection = None
    old_busy = None
    session_hooks = connection_hook = False
    committed = False

    def before_commit(selected):
        if selected is not db or state is None or state.phase != "committing" or state.checks != 2:
            raise _closed()
        _frame(state)
        _unexpired(state.claims, state.sid_expires)

    def physical_commit(selected):
        if selected is not connection or state is None or state.phase != "committing":
            raise _closed()
        _frame(state, physical_commit=True)
        _unexpired(state.claims, state.sid_expires)

    def new_transaction(selected, transaction):
        if transaction.nested:
            if state is not None:
                state.valid = False
            raise HTTPException(403, "Savepoints sind für diesen Einzelread nicht zulässig.")

    def ended(selected, transaction):
        if state is not None and transaction is state.transaction:
            state.valid = False

    try:
        # Lease our own physical Connection through cleanup. Session.commit must
        # not return a pooled SQLite connection with this operation's timeout.
        connection = bind.connect()
        if bind.dialect.name == "postgresql":
            connection = connection.execution_options(isolation_level="READ COMMITTED")
        if connection.in_transaction():
            raise _closed()
        db = Session(bind=connection, autoflush=False, expire_on_commit=False)
        event.listen(db, "before_commit", before_commit)
        event.listen(db, "after_transaction_create", new_transaction)
        event.listen(db, "after_transaction_end", ended)
        session_hooks = True
        event.listen(connection, "commit", physical_commit)
        connection_hook = True
        if db.connection() is not connection:
            raise _closed()
        if bind.dialect.name == "sqlite":
            old_busy = connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one()
            connection.exec_driver_sql("PRAGMA busy_timeout=500")
            if connection.connection.driver_connection.in_transaction:
                raise _closed()
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            connection.exec_driver_sql("SET LOCAL lock_timeout='1s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout='5s'")
        target = _same_factories(connection, caller, db, accounts, family)
        inbox._schema(connection)
        _singleton(connection, AuthSetupORM)
        if _signed(credential) != claims:
            raise _denied()
        if db.scalar(select(UserORM.id).where(UserORM.id == claims[0]).with_for_update()) is None:
            raise _denied()
        if _signed(credential) != claims:
            raise _denied()
        expires = _sid(connection, claims, lock=True)
        principal = inbox._principal(accounts, db, claims[0])
        if principal.role not in ROLE_CAPABILITIES:
            raise HTTPException(403, "Die Benutzerrolle erlaubt keinen persönlichen Einzelread.")
        _actor_access(connection, principal)
        _singleton(connection, OperationalLockORM)
        if _signed(credential) != claims:
            raise _denied()
        subject = _freeze(db, principal, _discover(connection, principal, notification_id))
        if _signed(credential) != claims:
            raise _denied()
        state = _State(db, db.get_transaction(), connection, connection.get_transaction(),
                       accounts, family, target, claims, principal, subject, get_ident(), expires)
        _refresh(state)
        proof = object.__new__(NotificationReadCommitAuthority)
        with _registry_lock:
            _issued[proof] = state
        result = inbox.stage_read(db, notification_id, authority=proof)
        if type(result) is not NotificationReadResult or result.notification_id != notification_id or state.checks != 2:
            raise _closed()
        state.phase = "finalizing"
        db.flush()
        if _signed(credential) != claims:
            raise _denied()
        _refresh(state)  # Actual final authority/subject check after flush, then only commit.
        state.phase = "committing"
        db.commit()
        committed = True
        return result
    except DBAPIError as error:
        if db is not None:
            db.rollback()
        sqlite_code = getattr(error.orig, "sqlite_errorcode", 0) & 255
        postgres_code = getattr(error.orig, "sqlstate", getattr(error.orig, "pgcode", None))
        if sqlite_code in {5, 6} or postgres_code in {"55P03", "57014", "40P01", "40001"}:
            raise _conflict() from None
        raise _closed() from None
    except BaseException:
        if db is not None:
            db.rollback()
        raise
    finally:
        if state is not None:
            state.valid = False
        if proof is not None:
            with _registry_lock:
                _issued.pop(proof, None)
        if session_hooks:
            event.remove(db, "before_commit", before_commit)
            event.remove(db, "after_transaction_create", new_transaction)
            event.remove(db, "after_transaction_end", ended)
        try:
            if connection_hook:
                event.remove(connection, "commit", physical_commit)
            if db is not None:
                db.close()
        finally:
            if connection is not None:
                try:
                    if not connection.closed and not connection.invalidated:
                        driver = connection.connection.driver_connection
                        if not committed:
                            # A rejected Connection.commit can deactivate its
                            # SQLAlchemy RootTransaction before DBAPI commit.
                            # Always close our actual failed physical unit too.
                            driver.rollback()
                    if old_busy is not None and not connection.closed and not connection.invalidated:
                        # Restore the exact leased DBAPI connection after end,
                        # without beginning an unrelated SQLAlchemy transaction.
                        cursor = connection.connection.driver_connection.cursor()
                        try:
                            cursor.execute(f"PRAGMA busy_timeout={int(old_busy)}")
                        finally:
                            cursor.close()
                finally:
                    connection.close()
