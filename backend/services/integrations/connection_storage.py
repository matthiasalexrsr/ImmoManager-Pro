"""Shared private persistence for connection services; no implicit network activity."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError

from ...config import settings
from ...db.integration_connection_models import IntegrationConnectionEventORM
from .. import business_qol as commands
from .. import document_versions as archive
from ..portfolio_scope import scope_context, scope_from_user
from ..secret_box import SecretBox, SecretError, default_secret_box
from ..workspace_contexts import bound_actor

STEP_BYTES_DEFAULT = 4 * 1024 * 1024
BLOCK_BYTES = 64 * 1024


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def stamp(value: datetime) -> str:
    return commands.utc(value).isoformat()


def canonical(value: Any, *, enforce_budget: bool = True) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise HTTPException(422, "Die Angaben enthalten nicht unterstützte oder ungültige Werte.") from None
    budget = getattr(settings, "integration_step_max_bytes", STEP_BYTES_DEFAULT)
    if enforce_budget and len(raw) > budget:
        raise HTTPException(413, "Dieser Arbeitsschritt ist zu groß. Bitte die Quelle in fortsetzbaren Abschnitten übernehmen.")
    return raw


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def seal(value: Any, context: str, box: SecretBox | None = None) -> str:
    raw = canonical(value)
    try:
        return (box or default_secret_box()).seal(raw.decode("utf-8"), context)
    except (SecretError, OSError):
        raise HTTPException(503, "Geschützte Verbindungsdaten konnten nicht sicher gespeichert werden.") from None


def unseal(token: str, context: str, box: SecretBox | None = None) -> Any:
    try:
        return json.loads((box or default_secret_box()).open(token, context))
    except (SecretError, OSError, ValueError, RecursionError):
        raise HTTPException(503, "Geschützte Verbindungsdaten sind nicht lesbar. Bitte Schlüssel und Wiederherstellung prüfen.") from None


@contextmanager
def work(store, actor_id: str, *, write: bool = False, command_key: str | None = None):
    try:
        with archive.work(store, actor_id, write_areas=("/integrations",) if write else ()) as unit:
            scope = scope_from_user(unit.user)
            if not scope.unrestricted:
                raise HTTPException(403, "Diese Verbindungen betreffen die ganze Installation und benötigen Zugriff auf alle Portfolios.")
            if write and command_key is not None and unit.db is not None and unit.db.get_bind().dialect.name == "postgresql":
                # The account fence is a shared lock. Serialize a command key
                # separately, BEFORE any connection/source row lock, so two
                # creates cannot both pass the absent-receipt check.
                key = hashlib.sha256(("immo:business-command:" + actor_id + ":" + command_key).encode()).digest()
                identifier = int.from_bytes(key[:8], "big", signed=True)
                unit.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": identifier})
            with bound_actor(unit.user), scope_context(scope):
                yield unit
    except SQLAlchemyError:
        # The SQL driver may include values and credentials in its exception.
        raise HTTPException(503, "Der Verbindungsstand konnte nicht sicher gelesen oder gespeichert werden.") from None


def memory(unit, model) -> dict:
    state = unit.store.__dict__.setdefault("_integration_connections", {})
    return state.setdefault(model.__tablename__, {})


def values(row) -> dict[str, Any]:
    return {column.key: deepcopy(getattr(row, column.key)) for column in row.__table__.c}


def row(unit, model, identifier: str, *, lock: bool = False, required: bool = True):
    if unit.db is None:
        result = memory(unit, model).get(identifier)
    else:
        query = select(model).where(model.id == identifier)
        result = unit.db.scalar(query.with_for_update() if lock else query)
    if result is None and required:
        raise HTTPException(404, "Verbindung oder Vorgang nicht gefunden.")
    return result


def find_one(unit, model, *, lock: bool = False, **filters):
    if unit.db is None:
        return next((item for item in memory(unit, model).values()
                     if all(getattr(item, name) == value for name, value in filters.items())), None)
    query = select(model).filter_by(**filters)
    return unit.db.scalar(query.with_for_update() if lock else query)


def put(unit, model, data: dict):
    identifier = data["id"]
    if unit.db is None:
        result = model(**deepcopy(data))
        unit.insert(memory(unit, model), identifier, result)
    else:
        result = row(unit, model, identifier, required=False)
        if result is None:
            result = model(**data)
            unit.db.add(result)
        else:
            for name, value in data.items():
                setattr(result, name, deepcopy(value))
        unit.db.flush()
    return result


def remove(unit, model, identifier: str) -> None:
    current = row(unit, model, identifier)
    if unit.db is None:
        unit.remove(memory(unit, model), identifier)
    else:
        unit.db.delete(current)
        unit.db.flush()


def revision(current, expected: int) -> None:
    if current.revision != expected:
        raise HTTPException(409, "Der Stand wurde zwischenzeitlich geändert. Bitte neu laden und die Eingaben vergleichen.")


def record_event(unit, connection_id: str, event_type: str, detail: dict,
                 *, run_id: str | None = None, box: SecretBox | None = None) -> str:
    identifier = str(uuid4())
    moment = now()
    identity = {"id": identifier, "connection_id": connection_id, "run_id": run_id,
                "actor_id": unit.actor_id, "event_type": event_type, "created_at": stamp(moment)}
    envelope = {"format": "immomanager-connection-event/2", "identity": identity, "detail": detail}
    put(unit, IntegrationConnectionEventORM, {**identity, "created_at": moment,
        "detail_token": seal(envelope, f"connection-event/{identifier}", box)})
    return identifier


def event_detail(item, box: SecretBox | None = None) -> tuple[dict, str]:
    value = unseal(item.detail_token, f"connection-event/{item.id}", box)
    if isinstance(value, dict) and value.get("format") == "immomanager-connection-event/2":
        identity = {name: getattr(item, name) for name in ("id", "connection_id", "run_id", "actor_id", "event_type")}
        identity["created_at"] = stamp(item.created_at)
        if value.get("identity") != identity or not isinstance(value.get("detail"), dict):
            raise HTTPException(503, "Der Ereignisnachweis wurde verändert oder einem anderen Vorgang zugeordnet.")
        return value["detail"], "metadata-bound"
    if not isinstance(value, dict):
        raise HTTPException(503, "Der Ereignisnachweis ist nicht lesbar.")
    return value, "legacy-id-only"


def replay(unit, operation: str, payload) -> dict | None:
    return commands.replay(unit, unit.actor_id, "connection:" + operation, payload)


def receipt(unit, operation: str, payload, connection_id: str, response: dict) -> None:
    context = {"kind": "integration_connection", "entity_id": connection_id, "property_id": None}
    commands.save_command(unit, unit.actor_id, "connection:" + operation, payload, context, response)


def page(unit, model, actor_id: str, *, cursor: str | None = None, limit: int = 50,
         sql_condition=None, memory_condition=None, **filters) -> dict:
    if not 1 <= limit <= 250:
        raise HTTPException(422, "Die Seitengröße muss zwischen 1 und 250 liegen.")
    namespace = ["connection-page-v1", model.__tablename__, actor_id, filters]
    decoded = commands.cursor_decode(cursor, namespace)
    anchor = None
    if decoded is not None:
        try:
            if len(decoded) != 2 or not all(isinstance(value, str) for value in decoded) or not decoded[1]:
                raise ValueError
            anchor = (commands.utc(datetime.fromisoformat(decoded[0])).replace(tzinfo=None), decoded[1])
        except (ValueError, TypeError):
            raise HTTPException(422, "Ungültige Fortsetzung. Bitte die Liste neu laden.") from None
    selected: list[Any]
    if unit.db is None:
        selected = [item for item in memory(unit, model).values()
                    if all(getattr(item, name) == value for name, value in filters.items())
                    and (memory_condition is None or memory_condition(item))]
        total = len(selected)
        selected = [item for item in selected if anchor is None or (item.created_at, item.id) < anchor]
        selected.sort(key=lambda item: (item.created_at, item.id), reverse=True)
        selected = selected[:limit + 1]
    else:
        query = select(model).filter_by(**filters)
        count_query = select(func.count()).select_from(model).filter_by(**filters)
        if sql_condition is not None:
            query = query.where(sql_condition)
            count_query = count_query.where(sql_condition)
        total = unit.db.scalar(count_query)
        if anchor:
            query = query.where(or_(model.created_at < anchor[0], and_(model.created_at == anchor[0], model.id < anchor[1])))
        selected = list(unit.db.scalars(query.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)))
    has_more = len(selected) > limit
    selected = selected[:limit]
    continuation = commands.cursor_encode(namespace, [stamp(selected[-1].created_at), selected[-1].id]) if has_more else None
    return {"items": selected, "total": total, "next_cursor": continuation, "has_more": has_more}


def field_manifest(value: Any) -> list[dict]:
    """Describe observed shape only. A discovered field is not a mapped business value."""
    output = []
    stack = [("$", value)]
    while stack:
        path, item = stack.pop()
        kind = "null" if item is None else "boolean" if isinstance(item, bool) else "object" if isinstance(item, dict) \
            else "array" if isinstance(item, list) else "number" if isinstance(item, (int, float)) else "string"
        output.append({"path": path, "type": kind, "status": "observed"})
        if isinstance(item, dict):
            stack.extend((path + "/" + str(key).replace("~", "~0").replace("/", "~1"), child) for key, child in reversed(list(item.items())))
        elif isinstance(item, list):
            stack.extend((path + "/" + str(index), child) for index, child in reversed(list(enumerate(item))))
    return output


def secret_references(connection) -> dict[str, str]:
    references = connection.secret_refs
    if not isinstance(references, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in references.items()):
        raise HTTPException(503, "Die Geheimnisreferenzen dieser Verbindung sind beschädigt.")
    return dict(references)
