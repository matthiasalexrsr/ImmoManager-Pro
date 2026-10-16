"""Per-account inbox, source routing and atomic complete-inbox acknowledgement."""
import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import cast

from fastapi import HTTPException
from sqlalchemy import Table, and_, case, func, or_, select, true
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.sql.elements import Case
from sqlalchemy.sql.selectable import Join

from ..db.daily_models import DailyStateORM, InboxEpochORM
from ..db.orm_models import NotificationORM
from ..models import Notification
from . import daily_state as state
from . import document_versions as archive
from . import workspace_contexts as contexts
from .portfolio_scope import scope_context, scope_from_user


def target(store, notice, actor_id, *, lock=False):
    if not notice.entity_type or not notice.entity_id:
        return None
    return contexts.resolve_context(store, notice.entity_type, notice.entity_id, actor_id, lock=lock)


def public(unit, notice, email_preference=None):
    receipt = state.get(unit, "notice:" + notice.id)
    payload = receipt["payload"]
    item = notice.model_dump(mode="json")
    item.update(legacy_status=notice.status, legacy_read_at=item.get("read_at"),
                status="archived" if payload.get("archived_at") else "read" if payload.get("read_at") else "unread",
                read_at=payload.get("read_at"), archived_at=payload.get("archived_at"), revision=receipt["revision"])
    try:
        source = target(unit.store, notice, unit.actor_id)
        item["target"] = {key: source[key] for key in ("kind", "entity_id", "href", "revision", "title")} if source else None
        item["target_error"] = None if source else "Dieser ältere Hinweis besitzt keinen eindeutigen Aktenbezug."
    except HTTPException as exc:
        if exc.status_code not in (403, 404, 422):
            raise
        item["target"] = None
        item["target_error"] = "Die Quelle ist gelöscht oder aktuell nicht zugänglich. Der Hinweis bleibt erhalten."
    from .settings_catalogue import effective, email_policy
    preference = email_preference if email_preference is not None else {key: effective(unit, key)[0] for key in ("email_notifications", "quiet_start", "quiet_end")}
    item["email_eligible"] = email_policy(preference, notice.severity)
    direct = set(contexts.RESOURCE_ALIASES)
    if item["target"] and item["target"]["kind"] in direct:
        href = item["target"]["href"]
        if item["target"]["kind"] == "utility_statement":
            href += "&filter=statements"
        item["open_href"] = href + ("&" if "?" in href else "?") + "notice_id=" + notice.id
    else:
        item["open_href"] = "/notifications/open/" + notice.id
    return item


def _joined(unit) -> tuple[Table, Table, Join, Case[str]]:
    n, r = cast(Table, NotificationORM.__table__), cast(Table, DailyStateORM.__table__)
    join = n.outerjoin(r, and_(r.c.owner_id == unit.actor_id, r.c.key == 'notice:' + n.c.id))
    status = case((r.c.payload['archived_at'].as_string().is_not(None), 'archived'),
                  (r.c.payload['read_at'].as_string().is_not(None), 'read'), else_='unread')
    return n, r, join, status


def _filters(n, personal_status, status, severity, kind):
    clauses = []
    if status:
        clauses.append(personal_status == status)
    if severity:
        clauses.append(n.c.severity == severity)
    if kind:
        aliases = [key for key, value in contexts.KIND_ALIASES.items() if value == kind]
        clauses.append(n.c.entity_type.in_([kind, *aliases]))
    return clauses


def _stats(unit, status=None, severity=None, kind=None):
    """Only aggregate scalars cross the SQL boundary, never inbox/source rows."""
    if unit.db is None:
        rows = unit.store.list_notifications()
        summaries = [(n, state.get(unit, 'notice:' + n.id)) for n in rows]
        def own_status(r):
            return 'archived' if r['payload'].get('archived_at') else 'read' if r['payload'].get('read_at') else 'unread'
        selected = sum((not status or own_status(r) == status) and (not severity or n.severity == severity)
                       and (not kind or contexts.KIND_ALIASES.get(n.entity_type, n.entity_type) == kind) for n, r in summaries)
        version = [(n.id, str(n.updated_at), r['revision']) for n, r in sorted(summaries, key=lambda pair: pair[0].id)]
        return selected, sum(own_status(r) == 'unread' for _, r in summaries), state.digest('inbox', version)
    n, r, joined, sql_status = _joined(unit)
    sql_selected = and_(*_filters(n, sql_status, status, severity, kind)) if any((status, severity, kind)) else true()
    row = unit.db.execute(select(func.count(), func.sum(case((sql_status == 'unread', 1), else_=0)),
        func.sum(case((sql_selected, 1), else_=0)), func.max(n.c.updated_at), func.max(n.c.created_at),
        func.max(n.c.id), func.coalesce(func.sum(r.c.revision), 0)).select_from(joined)).one()
    # Receipt revisions are monotonic, including reopen; modified receipts cannot
    # disappear behind an unchanged unread count. The boundary covers ALL filters.
    epoch = unit.db.scalar(select(InboxEpochORM.revision).where(InboxEpochORM.id == 1))
    scope = scope_from_user(unit.user)
    return int(row[2] or 0), int(row[1] or 0), state.digest('inbox', [str(v) for v in (row[0], *row[3:], epoch, scope.unrestricted, sorted(scope.portfolio_ids))])


def _encode(value):
    from ..auth import SECRET_KEY
    raw = json.dumps(value, separators=(',', ':')).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=') + '.' + hmac.new(SECRET_KEY.encode(), raw, hashlib.sha256).hexdigest()


def _decode(value):
    try:
        if not isinstance(value, str) or len(value) > 4096:
            raise ValueError()
        from ..auth import SECRET_KEY
        encoded, signature = value.split('.')
        raw = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
        if not hmac.compare_digest(signature, hmac.new(SECRET_KEY.encode(), raw, hashlib.sha256).hexdigest()):
            raise ValueError()
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(422, 'Ungültiger Seitencursor. Bitte die erste Seite laden.') from exc


def _page(unit, status, severity, kind, limit, offset=0, after=None):
    if unit.db is None:
        rows = sorted(unit.store.list_notifications(), key=lambda n: (n.created_at, n.id), reverse=True)
        result = []
        for notice in rows:
            receipt = state.get(unit, 'notice:' + notice.id)['payload']
            own_status = 'archived' if receipt.get('archived_at') else 'read' if receipt.get('read_at') else 'unread'
            if status and status != own_status or severity and severity != notice.severity or kind and kind != contexts.KIND_ALIASES.get(notice.entity_type, notice.entity_type):
                continue
            if after and (notice.created_at.replace(tzinfo=None), notice.id) >= (datetime.fromisoformat(after[0]).replace(tzinfo=None), after[1]):
                continue
            if offset:
                offset -= 1
                continue
            result.append(notice)
            if len(result) == limit:
                break
        return result
    n, r, joined, sql_status = _joined(unit)
    query = select(*n.c, r.c.revision.label('receipt_revision'), r.c.payload.label('receipt_payload')).select_from(joined).where(
        *_filters(n, sql_status, status, severity, kind))
    if after:
        stamp = datetime.fromisoformat(after[0]).replace(tzinfo=None)
        query = query.where(or_(n.c.created_at < stamp, and_(n.c.created_at == stamp, n.c.id < after[1])))
    query = query.order_by(n.c.created_at.desc(), n.c.id.desc()).limit(limit)
    if offset:  # Explicit APIv1 compatibility only. New clients use the tuple cursor.
        query = query.offset(offset)
    records = unit.db.execute(query).mappings().all()
    unit._daily_receipts = {'notice:' + row['id']: {'revision': row['receipt_revision'] or 0, 'payload': row['receipt_payload'] or {}} for row in records}
    return [Notification.model_validate({c.name: row[c.name] for c in n.c}) for row in records]


def snapshot(rows):
    return hashlib.sha256(json.dumps([(n["id"], n["revision"], n["updated_at"], n["target"]) for n in rows], sort_keys=True).encode()).hexdigest()


def inbox(store, actor_id, status=None, offset=0, limit=50, expected_snapshot=None, severity=None, kind=None, cursor=None):
    if status not in (None, 'unread', 'read', 'archived') or severity not in (None, 'info', 'warning', 'error', 'critical') or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
        raise HTTPException(422, 'Ungültiger Eingangsfilter oder Seitenbereich.')
    if kind:
        kind = contexts.canonical_kind(kind)
    with archive.work(store, actor_id) as unit, contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
        total, unread, boundary = _stats(unit, status, severity, kind)
        after = None
        if cursor is not None:
            data = _decode(cursor)
            if set(data) != {'v', 'owner', 'filters', 'snapshot', 'after'} or data['v'] != 1 or data['owner'] != actor_id or data['filters'] != [status, severity, kind] or offset:
                raise HTTPException(422, 'Seitencursor passt nicht zu Benutzer oder Filtern.')
            after = data['after']
            try:
                if not isinstance(after, list) or len(after) != 2 or not isinstance(after[1], str) or not after[1]:
                    raise ValueError()
                datetime.fromisoformat(after[0])
            except (ValueError, TypeError):
                raise HTTPException(422, 'Ungültige Seitengrenze.') from None
            expected_snapshot = data['snapshot']
        if expected_snapshot is not None and expected_snapshot != boundary:
            raise HTTPException(409, "Der Eingang wurde geaendert. Bitte ab der ersten Seite neu laden.")
        records = _page(unit, status, severity, kind, limit + 1, offset, after)
        visible = records[:limit]
        from .settings_catalogue import effective
        preference = {key: effective(unit, key)[0] for key in ('email_notifications', 'quiet_start', 'quiet_end')}
        more = len(records) > limit
        next_cursor = _encode(dict(v=1, owner=actor_id, filters=[status, severity, kind], snapshot=boundary,
                                   after=[visible[-1].created_at.isoformat(), visible[-1].id])) if more else None
        return {'items': [public(unit, n, preference) for n in visible], 'total': total, 'unread_count': unread,
                'snapshot': boundary, 'read_all_preview': {'unread_count': unread, 'boundary': boundary},
                'next_cursor': next_cursor, 'next_offset': offset + limit if more else None}


def open_source(store, actor_id, identifier):
    with archive.work(store, actor_id) as unit, contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
        notice = unit.store.get_notification(identifier)
        source = target(unit.store, notice, actor_id)
        if source is None:
            raise HTTPException(409, "Kein eindeutiges Ziel vorhanden. Bitte den Hinweis im Eingang prüfen.")
        return {"notice": public(unit, notice), "source": source}


def _mutate(store, actor_id, identifier, body):
    fingerprint = state.digest("notice:" + identifier, body)
    with archive.work(store, actor_id, write_areas=("/workspace",)) as unit, contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
        if identifier != "all":
            if unit.db is not None:
                unit.db.scalar(select(NotificationORM.id).where(NotificationORM.id == identifier).with_for_update())
            notice = unit.store.get_notification(identifier)
            # Current visibility is mandatory even for replay. Once committed,
            # replay no longer depends on a historical source revision/name.
            saved = state.replay(unit, body['idempotency_key'], fingerprint)
            if saved is not None:
                if notice.entity_type and notice.entity_id:
                    target(unit.store, notice, actor_id, lock=True)
                return saved
            if body["action"] == "landed":
                source = target(unit.store, notice, actor_id, lock=True)
                if not source or source["revision"] != body.get("source_revision"):
                    raise HTTPException(409, "Die Quelle wurde geändert. Bitte erneut öffnen.")
                if source["kind"] != body.get("source_kind") or source["entity_id"] != body.get("source_id"):
                    raise HTTPException(409, "Das geöffnete Ziel passt nicht zum Hinweis.")
        saved = state.replay(unit, body["idempotency_key"], fingerprint)
        if saved is not None:
            if identifier == 'all' and 'grants' in saved:
                if saved['grants'] != state.digest('inbox-grants', [unit.user['role'], scope_from_user(unit.user).__dict__]):
                    raise HTTPException(403, 'Die Eingangsberechtigung wurde geändert. Bitte neu laden.')
                return saved['response']
            return saved
        stamp = datetime.now(timezone.utc).isoformat()
        if identifier == "all":
            _, unread, boundary = _stats(unit)
            epoch = unit.db.scalar(select(InboxEpochORM.revision).where(InboxEpochORM.id == 1)) if unit.db is not None else None
            if body["action"] != "read_all" or body.get("snapshot") != boundary:
                raise HTTPException(409, "Der Eingang wurde geändert. Bitte neu laden.")
            count = 0
            after = None
            # A single atomic operation, bounded 256-row windows, no cap. Every
            # window uses current SQL scope. The locked actor serializes tabs.
            while True:
                records = _page(unit, 'unread', None, None, 256, after=after)
                if not records:
                    break
                state.put_notice_batch(unit, records, {'read_at': stamp, 'archived_at': stamp})
                count += len(records)
                after = [records[-1].created_at.isoformat(), records[-1].id]
            _, remaining, _ = _stats(unit)
            # Inserts, removed sources/grants or competing changes during the
            # command must never produce a successful partial 'all' response.
            current_epoch = unit.db.scalar(select(InboxEpochORM.revision).where(InboxEpochORM.id == 1)) if unit.db is not None else None
            if count != unread or remaining or current_epoch != epoch:
                raise HTTPException(409, 'Der Eingang wurde während der Bestätigung geändert. Bitte neu laden.')
            result = {"acknowledged": count, "unread_count": remaining}
        else:
            receipt = state.get(unit, "notice:" + identifier)
            action = body["action"]
            if action not in ("landed", "reopen"):
                raise HTTPException(422, "Unzulässige persönliche Aktion.")
            payload = ({"read_at": receipt["payload"].get("read_at") or stamp, "archived_at": stamp}
                       if action == "landed" else {"read_at": None, "archived_at": None})
            result = state.put(unit, "notice:" + identifier, payload, body["base_revision"])
        remembered = {'response': result, 'grants': state.digest('inbox-grants', [unit.user['role'], scope_from_user(unit.user).__dict__])} if identifier == 'all' else result
        state.remember(unit, body["idempotency_key"], fingerprint, remembered)
        return result


def mutate(store, actor_id, identifier, body):
    try:
        return _mutate(store, actor_id, identifier, body)
    except IntegrityError as exc:
        raise HTTPException(409, "Gleichzeitige Änderung im Eingang. Bitte neu laden.") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Lesebestätigung nicht bestätigt. Bitte denselben Befehl erneut versuchen.") from exc
