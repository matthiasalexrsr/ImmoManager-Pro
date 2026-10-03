"""SQL-only personal live inbox; writes require Root's native commit capability."""

import importlib
import os
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import String, and_, case, cast, func, literal, or_, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from .. import auth
from ..db.booking_order import bytewise_id
from ..db.notification_inbox_models import NotificationReadStateORM
from ..db.operational_models import OperationalDispatchORM
from ..db.orm_models import NotificationORM, UserORM
from .booking_export import _snapshot
from .notification_inbox_types import (
    InboxItemActions,
    InboxPage,
    InboxPrincipal,
    InboxQuery,
    NotificationInboxItem,
    NotificationReadResult,
)
from .notification_inbox_validation import (
    InboxIntegrityError,
    validate_notification_inbox_schema,
)
from .portfolio_scope import AccessScope, current_scope, scope_from_user, scoped_clause
from .tenancy_workflow import decode_cursor, encode_cursor

_AUTHORITY_MODULE = "backend.services.notification_inbox_commit_authority"


def _unavailable(code="inbox_persistence_unavailable"):
    return HTTPException(
        503, {"code": code, "detail": "Die persönliche Inbox ist derzeit nicht verfügbar."},
        headers={"Retry-After": "2"},
    )


def _accounts():
    selected = auth._user_store
    if not isinstance(selected, auth.SQLUserStore):
        raise _unavailable()
    return selected


def _identity(connection):
    """Verify the actual target, not an assumed URL or unrelated default DB."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        rows = connection.exec_driver_sql("PRAGMA database_list")
        try:
            filename = next((row[2] for row in rows if row[1] == "main"), "")
        finally:
            rows.close()
        if not filename:
            raise _unavailable()
        return dialect, os.path.normcase(os.path.realpath(filename))
    if dialect == "postgresql":
        value = connection.execute(text(
            "SELECT current_database(), inet_server_addr()::text, "
            "inet_server_port(), current_schema()"
        )).one()
        if value[1] is None or value[2] is None or value[3] is None:
            raise _unavailable()
        return dialect, *value
    raise _unavailable()


def _scope(principal):
    return AccessScope(
        principal.actor_id, principal.role, principal.unrestricted, principal.portfolio_ids
    )


def _principal(accounts, db, actor_id):
    # Reuse the actual SQLUserStore's conversion, including native Access/Grants.
    row = db.get(UserORM, actor_id, populate_existing=True)
    if row is None or not row.is_active:
        raise HTTPException(403, "Die Benutzerbindung ist nicht mehr gültig.")
    user = accounts._to_dict(row)
    actual = scope_from_user(user)
    captured = current_scope()
    if captured is None or actual != captured:
        raise HTTPException(403, "Berechtigungen wurden geändert. Inbox neu laden.")
    return InboxPrincipal(
        actor_id=actual.user_id, role=actual.role, unrestricted=actual.unrestricted,
        portfolio_access=user["portfolio_access"],
        portfolio_access_origin=user["portfolio_access_origin"],
        portfolio_ids=actual.portfolio_ids,
    )


def _fresh_principal(connection, business_db):
    captured = current_scope()
    if captured is None:
        raise HTTPException(403, "Eine geprüfte Benutzerbindung ist erforderlich.")
    accounts = _accounts()
    db = accounts._session_factory()
    if not isinstance(db, Session) or db is business_db:
        # Do not close/borrow a caller-owned scoped session or its transaction.
        raise _unavailable()
    try:
        if db.new or db.dirty or db.deleted:
            raise _unavailable()
        with db.no_autoflush:
            if _identity(db.connection()) != _identity(connection):
                raise _unavailable()
            return _principal(accounts, db, captured.user_id)
    finally:
        accounts._finalize_session(db)


def _schema(connection):
    try:
        if not validate_notification_inbox_schema(connection):
            raise _unavailable("inbox_schema_unavailable")
    except InboxIntegrityError:
        raise _unavailable("inbox_schema_unavailable") from None


def _read_exists(table, principal):
    reads = NotificationReadStateORM.__table__
    return select(1).where(
        reads.c.notification_id == table.c.id, reads.c.actor_id == principal.actor_id
    ).exists()


def _eligibility(table, principal, query):
    criterion = table.c.status.in_(("unread", "read"))
    scoped = scoped_clause(table, scope=_scope(principal))
    if scoped is not None:
        criterion &= scoped
        # An explicit unlinked resource grant does not repair a broken pair.
        criterion &= or_(
            and_(table.c.entity_type.is_(None), table.c.entity_id.is_(None)),
            and_(table.c.entity_type.is_not(None), table.c.entity_id.is_not(None)),
        )
    if principal.role != "eigentuemer":
        dispatch = OperationalDispatchORM.__table__
        criterion &= ~select(1).where(
            dispatch.c.notification_id == table.c.id,
            dispatch.c.target_role.is_not(None),
            dispatch.c.target_role != "",
            dispatch.c.target_role != principal.role,
        ).exists()
    if query.notification_type is not None:
        criterion &= table.c.notification_type == query.notification_type
    if query.severity is not None:
        criterion &= table.c.severity == query.severity
    return criterion


def _status(table, principal, query):
    read = _read_exists(table, principal)
    return ~read if query.status == "unread" else read if query.status == "read" else literal(True)


def _binding(principal, query):
    return {
        "kind": "notification-inbox-live/1",
        "actor": principal.binding(),
        "query": {"status": query.status, "notification_type": query.notification_type,
                  "severity": query.severity, "limit": query.limit},
        "sort": "created-desc-null-last-byte-id-desc",
        "consistency": "live",
    }


def _position(principal, query):
    point = decode_cursor(query.after, _binding(principal, query))
    if point is None:
        return None
    try:
        if len(point) != 2 or not isinstance(point[1], str) or not point[1]:
            raise ValueError
        if point[0] is not None and not isinstance(point[0], str):
            raise ValueError
        stamp = datetime.fromisoformat(point[0]) if point[0] is not None else None
        if stamp is not None and stamp.tzinfo is not None:
            raise ValueError
        return stamp, point[1]
    except (ValueError, TypeError):
        raise HTTPException(422, "Ungültige Inboxseite. Erste Seite neu laden.") from None


def _order(connection, table, point):
    day, identifier = table.c.created_at, bytewise_id(table.c.id)
    if connection.dialect.name == "sqlite":
        # Same lossless representation as the reviewed native B1 fix.
        raw = cast(day, String)
        day = case((func.length(raw) == 19, raw + ".000000"), else_=raw)
        if point is not None and point[0] is not None:
            point = point[0].isoformat(sep=" ", timespec="microseconds"), point[1]
    return day, identifier, point


def _counts(connection, principal, query):
    table = NotificationORM.__table__
    unread = ~_read_exists(table, principal)
    row = connection.execute(select(
        func.coalesce(func.sum(case((_status(table, principal, query), 1), else_=0)), 0)
            .label("full_count"),
        func.coalesce(func.sum(case((unread, 1), else_=0)), 0).label("unread_count"),
    ).where(_eligibility(table, principal, query))).mappings().one()
    return int(row["full_count"]), int(row["unread_count"])


def _page(connection, principal, query, point):
    table, reads = NotificationORM.__table__, NotificationReadStateORM.__table__
    read_at = select(reads.c.read_at).where(
        reads.c.notification_id == table.c.id, reads.c.actor_id == principal.actor_id
    ).scalar_subquery().label("read_at")
    statement = select(
        table.c.id, table.c.notification_type, table.c.title, table.c.content,
        table.c.severity, table.c.entity_type, table.c.entity_id, table.c.created_at, read_at,
    ).where(_eligibility(table, principal, query), _status(table, principal, query))
    day, identifier, point = _order(connection, table, point)
    if point is not None:
        value, last_id = point
        statement = statement.where(
            (day.is_(None) & (identifier < last_id)) if value is None else
            or_(day.is_(None), day < value, (day == value) & (identifier < last_id))
        )
    return [dict(row) for row in connection.execute(
        statement.order_by(day.desc().nulls_last(), identifier.desc()).limit(query.limit + 1)
    ).mappings()]


def list_inbox(
    store, query: InboxQuery | None = None, *, read_actions_enabled: bool = False
) -> InboxPage:
    """Only bounded native projections; actor derives from fresh actual SQL auth."""
    query = query or InboxQuery()
    if not isinstance(query, InboxQuery):
        raise TypeError("InboxQuery required")
    if type(read_actions_enabled) is not bool:
        raise TypeError("read_actions_enabled must be an internal boolean")
    db = getattr(store, "db", None)
    if not isinstance(db, Session):
        raise _unavailable()
    if db.get_bind().dialect.name not in {"sqlite", "postgresql"}:
        raise _unavailable()
    try:
        with db.no_autoflush, _snapshot(db.get_bind()) as connection:
            principal = _fresh_principal(connection, db)
            _schema(connection)
            point = _position(principal, query)
            full, unread = _counts(connection, principal, query)
            rows = _page(connection, principal, query, point)
            if _fresh_principal(connection, db) != principal:
                raise HTTPException(403, "Berechtigungen wurden geändert. Inbox neu laden.")
        # A parent can move while the immutable first read snapshot remains
        # open without changing the actor's account/grants. Establish a fresh
        # publication point after closing it, including actual current parents,
        # dispatches, personal state, page projection and complete counts.
        with db.no_autoflush, _snapshot(db.get_bind()) as connection:
            if _fresh_principal(connection, db) != principal:
                raise HTTPException(403, "Berechtigungen wurden geändert. Inbox neu laden.")
            _schema(connection)
            current_counts = _counts(connection, principal, query)
            current_rows = _page(connection, principal, query, point)
            if current_counts != (full, unread) or current_rows != rows:
                raise HTTPException(409, {
                    "code": "inbox_changed",
                    "detail": "Die Inbox wurde zwischenzeitlich geändert. Bitte neu laden.",
                })
            if _fresh_principal(connection, db) != principal:
                raise HTTPException(403, "Berechtigungen wurden geändert. Inbox neu laden.")
        selected = rows[:query.limit]
        more = len(rows) > query.limit
        cursor = None
        if more:
            last = selected[-1]
            stamp = last["created_at"]
            cursor = encode_cursor(
                _binding(principal, query),
                [stamp.isoformat(timespec="microseconds") if stamp is not None else None, last["id"]],
            )
        return InboxPage(
            # This internal release flag is UI metadata, never a write capability.
            items=[NotificationInboxItem(**row, actions=InboxItemActions(
                mark_read=read_actions_enabled
            )) for row in selected], full_count=full,
            unread_count=unread, has_more=more, next_cursor=cursor,
        )
    except DBAPIError:
        raise _unavailable() from None


def _authority(db, notification_id, proof):
    """No structural interface, boolean, lambda or local 'checked' substitute."""
    try:
        shared = importlib.import_module(_AUTHORITY_MODULE)
    except ModuleNotFoundError as error:
        if error.name == _AUTHORITY_MODULE:
            raise _unavailable("inbox_commit_authority_unavailable") from None
        raise
    if type(proof) is not shared.NotificationReadCommitAuthority:
        raise HTTPException(403, "Ein tatsächlicher CommitAuthoritybeleg ist erforderlich.")
    principal = shared.require_notification_read_authority(db, notification_id, proof)
    if type(principal) is not InboxPrincipal:
        raise _unavailable("inbox_commit_authority_unavailable")
    return principal


def stage_read(db: Session, notification_id: str, *, authority: object) -> NotificationReadResult:
    """Caller owns the real fenced transaction and final commit/rollback."""
    if not isinstance(db, Session) or not db.in_transaction():
        raise _unavailable("inbox_commit_authority_unavailable")
    if not isinstance(notification_id, str) or not notification_id:
        raise HTTPException(404, "Benachrichtigung nicht gefunden.")
    principal = _authority(db, notification_id, authority)
    accounts = _accounts()
    try:
        with db.no_autoflush:
            _schema(db.connection())
            if _principal(accounts, db, principal.actor_id) != principal:
                raise HTTPException(403, "Berechtigungen wurden geändert. Inbox neu laden.")
            table = NotificationORM.__table__
            if db.execute(select(table.c.id).where(
                table.c.id == notification_id, _eligibility(table, principal, InboxQuery())
            )).first() is None:
                raise HTTPException(404, "Benachrichtigung nicht gefunden.")
            reads = NotificationReadStateORM.__table__
            dialect = db.get_bind().dialect.name
            if dialect == "sqlite":
                from sqlalchemy.dialects.sqlite import insert
                stamp = func.strftime("%Y-%m-%d %H:%M:%f", "now")
            elif dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
                stamp = func.timezone("UTC", func.clock_timestamp())
            else:
                raise _unavailable()
            db.execute(insert(reads).values(
                actor_id=principal.actor_id, notification_id=notification_id, read_at=stamp
            ).on_conflict_do_nothing(index_elements=["actor_id", "notification_id"]))
            read_at = db.execute(select(reads.c.read_at).where(
                reads.c.actor_id == principal.actor_id, reads.c.notification_id == notification_id
            )).scalar_one()
            if _authority(db, notification_id, authority) != principal:
                raise HTTPException(403, "Berechtigungen wurden geändert. Inbox neu laden.")
            return NotificationReadResult(notification_id=notification_id, read_at=read_at)
    except DBAPIError:
        # Caller must roll back; this helper never commits/rolls back a foreign unit.
        raise _unavailable() from None
