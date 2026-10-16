"""Durable personal workspace state, with owner isolation, CAS and safe retries."""

from __future__ import annotations

import base64
import hashlib
import json
import unicodedata
from copy import deepcopy
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from ..db.workspace_models import (
    WorkspaceCommandORM,
    WorkspaceDeferralORM,
    WorkspaceDraftORM,
    WorkspaceFavoriteORM,
    WorkspaceRecentORM,
    WorkspaceViewORM,
    WorkspaceViewStateORM,
)
from . import document_versions as archive
from . import workspace_contexts as contexts
from .portfolio_scope import scope_context, scope_from_user

MODELS: dict[str, Any] = {"drafts": WorkspaceDraftORM, "views": WorkspaceViewORM, "recents": WorkspaceRecentORM,
          "favorites": WorkspaceFavoriteORM, "view-state": WorkspaceViewStateORM, "deferrals": WorkspaceDeferralORM}
VIEW_KEYS = {"search", "column_filters", "sort", "visible_columns", "hidden_columns", "column_order", "page_size"}
STATE_KEYS = VIEW_KEYS | {"page_cursor", "page", "scroll_top", "scroll_left", "row_mark"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _stamp(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _memory(store, kind: str) -> dict:
    return store.__dict__.setdefault("_personal_workspace", {}).setdefault(kind, {})


def _get(unit, kind: str, identifier: str, *, lock: bool = False):
    if unit.db is None:
        row = _memory(unit.store, kind).get((unit.actor_id, identifier))
        return deepcopy(row) if row is not None else None
    model = MODELS[kind]
    statement = select(model).where(model.owner_user_id == unit.actor_id, model.id == identifier)
    if lock:
        statement = statement.with_for_update()
    return unit.db.scalar(statement)


def _put(unit, kind: str, identifier: str, context: str, payload: dict, prior, *, deleted: bool = False):
    row: Any
    stamp = _now()
    values = {"id": identifier, "owner_user_id": unit.actor_id, "context": context,
              "revision": prior.revision + 1 if prior else 1, "deleted": deleted,
              "payload": deepcopy(payload), "created_at": prior.created_at if prior else stamp, "updated_at": stamp}
    if kind == "views":
        values["name_key"] = "deleted:" + identifier if deleted else unicodedata.normalize("NFKC", payload["name"]).casefold()
    if unit.db is not None:
        if prior is None:
            row = MODELS[kind](**values)
            unit.db.add(row)
        else:
            row = prior
            for key, value in values.items():
                setattr(row, key, value)
        unit.db.flush()
        return row
    row = SimpleNamespace(**values)
    if kind == "views" and not deleted and any(other.owner_user_id == unit.actor_id and not other.deleted
            and other.context == context and other.name_key == row.name_key and other.id != identifier
            for other in _memory(unit.store, kind).values()):
        raise HTTPException(409, {"code": "view_name_conflict", "message": "Diese Ansicht hat bereits einen Namen."})
    unit.insert(_memory(unit.store, kind), (unit.actor_id, identifier), row)
    return row


def _command(unit, key: str):
    if unit.db is None:
        return _memory(unit.store, "commands").get((unit.actor_id, key))
    return unit.db.scalar(select(WorkspaceCommandORM).where(
        WorkspaceCommandORM.owner_user_id == unit.actor_id, WorkspaceCommandORM.idempotency_key == key))


def _remember(unit, key: str, digest: str, response: dict, authorization: dict):
    values = {"id": hashlib.sha256(f"{unit.actor_id}:{key}".encode()).hexdigest(), "owner_user_id": unit.actor_id,
              "idempotency_key": key, "request_hash": digest,
              "response": {"result": deepcopy(response), "authorization": deepcopy(authorization)}, "created_at": _now()}
    if unit.db is not None:
        unit.db.add(WorkspaceCommandORM(**values))
        unit.db.flush()
    else:
        unit.insert(_memory(unit.store, "commands"), (unit.actor_id, key), SimpleNamespace(**values))


def _source_state(unit, payload: dict) -> dict:
    source = payload.get("source") or payload.get("anchor")
    if not source:
        return {"status": "new", "current_revision": None}
    anchored = not payload.get("source")
    try:
        current = contexts.resolve_context(unit.store, source["kind"], source["id"], unit.actor_id, include_dependencies=True)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        # Distinguish deletion from loss of access without reading any foreign data.
        if _source_exists_unscoped(unit, source):
            raise HTTPException(404, "Arbeitsstand nicht gefunden.") from None
        _check_deleted_anchors(unit, payload)
        return {"status": "deleted", "current_revision": None}
    dependency_key = "_anchor_dependencies" if anchored else "_source_dependencies"
    expected = (payload.get("_anchor_revision") or current["revision"]) if anchored else source["revision"]
    dependencies_changed = payload.get(dependency_key, current["dependencies"]) != current["dependencies"]
    return {"status": "current" if contexts.same_revision(expected, current["revision"]) and not dependencies_changed else "changed",
            "dependencies_changed": dependencies_changed,
            "current_revision": current["revision"], "reference": "anchor" if anchored else "source",
            "kind": current["kind"], "id": current["entity_id"], "title": current["title"]}


def _source_exists_unscoped(unit, source: dict) -> bool:
    """Existence only, never return metadata; enables safe deletion recovery."""
    from ..db.orm_models import Base
    from .portfolio_scope import RESOURCE_ALIASES

    table_name = RESOURCE_ALIASES[contexts.canonical_kind(source["kind"])]
    if unit.db is None:
        return source["id"] in object.__getattribute__(unit.store, "__dict__").get(table_name, {})
    # A separate Core connection is unnecessary and would consume a second pool
    # slot. scope_context(None) is scoped to this one constant existence query.
    table = Base.metadata.tables[table_name]
    with scope_context(None):
        return unit.db.scalar(select(table.c.id).where(table.c.id == source["id"]).limit(1)) is not None


def _check_deleted_anchors(unit, payload: dict):
    user = contexts.actor(unit.actor_id)
    anchors = payload.get("_portfolio_anchors", [])
    if not scope_from_user(user).unrestricted:
        if not anchors or not set(anchors).issubset(set(user.get("portfolio_ids", []))):
            raise HTTPException(404, "Arbeitsstand nicht gefunden.")


def _anchor(unit, anchor: dict | None, *, lock: bool = False):
    if anchor:
        return contexts.resolve_context(unit.store, anchor["kind"], anchor["id"], unit.actor_id, lock=lock)
    return None


def _authorize(unit, kind: str, payload: dict, *, write: bool = False):
    if kind in ("recents", "favorites"):
        contexts.resolve_context(unit.store, payload["kind"], payload["entity_id"], unit.actor_id, lock=write)
        return
    if kind == "deferrals":
        _work_item(unit.store, payload["work_item_key"], unit.actor_id)
        return
    contexts.check_context(unit.actor_id, payload["context"], edit=kind == "drafts")
    if kind == "drafts":
        state = _source_state(unit, payload)
        anchor = payload.get("anchor")
        source = payload.get("source") or anchor
        own_deleted_anchor = state["status"] == "deleted" and anchor and source and (
            contexts.canonical_kind(anchor["kind"]), anchor["id"]) == (
                contexts.canonical_kind(source["kind"]), source["id"])
        if not own_deleted_anchor:
            _anchor(unit, anchor, lock=write)
        if state["status"] != "deleted":
            contexts.validate_references(unit.store, payload.get("values", {}), unit.actor_id)
        # A deleted source may have been the draft's own reference; all saved
        # authorization anchors still apply before returning recovery values.
        else:
            _check_deleted_anchors(unit, payload)
            contexts.validate_references(unit.store, payload.get("values", {}), unit.actor_id, deleted_source=source)
    else:
        _anchor(unit, payload.get("anchor"), lock=write)
        _validate_view(unit, deepcopy(payload.get("config", payload.get("state", {}))),
                       state=kind == "view-state", read=not write)


def _work_item(store, key: str, actor_id: str) -> dict:
    from .workspace_work_items import resolve_work_item
    return resolve_work_item(store, key, actor_id, require_applicable=True)


def _validate_view(unit, config: dict, *, state: bool = False, read: bool = False):
    contexts.validate_json(config)
    if set(config) - (STATE_KEYS if state else VIEW_KEYS):
        raise HTTPException(422, "Unbekannte Ansichtseinstellung.")
    search = config.get("search", "")
    if not isinstance(search, str) or len(search) > 2000:
        raise HTTPException(422, "Ungültiger Suchtext.")
    filters = config.get("column_filters", {})
    if not isinstance(filters, dict) or any(not isinstance(key, str) or not contexts.IDENTIFIER.fullmatch(key) for key in filters):
        raise HTTPException(422, "Ungültige Spaltenfilter.")
    contexts.validate_references(unit.store, filters, unit.actor_id)
    for key in ("visible_columns", "hidden_columns", "column_order"):
        columns = config.get(key, [])
        if not isinstance(columns, list) or len(columns) > 250 or any(
                not isinstance(column, str) or not contexts.IDENTIFIER.fullmatch(column) for column in columns):
            raise HTTPException(422, "Ungültige Spaltenauswahl.")
    sort = config.get("sort")
    if sort is not None and (not isinstance(sort, dict) or set(sort) - {"key", "direction"}
            or not isinstance(sort.get("key"), str) or not contexts.IDENTIFIER.fullmatch(sort["key"])
            or sort.get("direction") not in ("asc", "desc")):
        raise HTTPException(422, "Ungültige Sortierung.")
    if "page_size" in config and (type(config["page_size"]) is not int or not 1 <= config["page_size"] <= 1000):
        raise HTTPException(422, "Ungültige Seitengröße.")
    for key in ("scroll_top", "scroll_left"):
        if key in config and (type(config[key]) not in (int, float) or not 0 <= config[key] <= 1000000000):
            raise HTTPException(422, "Ungültige Scrollposition.")
    if config.get("row_mark"):
        mark = config["row_mark"]
        if not isinstance(mark, dict) or set(mark) != {"kind", "id"}:
            raise HTTPException(422, "Ungültige Zeilenmarkierung.")
        try:
            contexts.resolve_context(unit.store, mark["kind"], mark["id"], unit.actor_id)
        except HTTPException as exc:
            if not read or exc.status_code not in (403, 404):
                raise
            # The former position can be recovered without leaking a revoked row.
            config.pop("row_mark", None)


def _public(unit, kind: str, row) -> dict:
    payload = {key: deepcopy(value) for key, value in row.payload.items() if not key.startswith("_")}
    result = {"id": row.id, "revision": row.revision, "created_at": _stamp(row.created_at),
              "updated_at": _stamp(row.updated_at), **payload}
    if row.deleted:
        return {"id": row.id, "revision": row.revision, "deleted": True}
    if kind == "drafts":
        result["source_state"] = _source_state(unit, row.payload)
        result["anchor_revision"] = row.payload.get("_anchor_revision")
    elif kind in ("recents", "favorites"):
        entity = contexts.resolve_context(unit.store, payload["kind"], payload["entity_id"], unit.actor_id)
        result.update(kind=entity["kind"], title=entity["title"], href=entity["href"])
        result["last_opened_at" if kind == "recents" else "pinned_at"] = _stamp(row.updated_at if kind == "recents" else row.created_at)
    elif kind == "view-state":
        _validate_view(unit, result["state"], state=True, read=True)
    return result


def get_record(store, actor_id: str, kind: str, identifier: str) -> dict:
    if kind not in MODELS:
        raise HTTPException(404, "Arbeitsstand nicht gefunden.")
    with archive.work(store, actor_id) as unit:
        with contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
            row = _get(unit, kind, identifier)
            if row is None or row.deleted:
                raise HTTPException(404, "Arbeitsstand nicht gefunden.")
            _authorize(unit, kind, row.payload)
            return _public(unit, kind, row)


def entity_key(kind: str, identifier: str) -> str:
    return contexts.canonical_kind(kind) + ":" + identifier


def _prepare(unit, kind: str, identifier: str, body: dict, prior, *, delete: bool = False) -> tuple[str, dict]:
    if delete:
        if prior is None or prior.deleted:
            raise HTTPException(404, "Arbeitsstand nicht gefunden.")
        _authorize(unit, kind, prior.payload, write=kind != "view-state")
        return prior.context, deepcopy(prior.payload)
    if kind == "drafts":
        context = contexts.check_context(unit.actor_id, body["context"], edit=True)
        payload = {key: deepcopy(value) for key, value in body.items()
                   if key not in {"base_revision", "idempotency_key"}}
        payload["context"] = context
        supplied_anchor_revision = payload.pop("anchor_revision", None)
        payload["values"] = contexts.recovery_values(payload.get("values", {}))
        if contexts.context_key(context) == "conversation-note" and not payload.get("anchor"):
            raise HTTPException(422, "Eine Gesprächsnotiz braucht einen Bezug.")
        if contexts.context_key(context) != "contract-wizard" and contexts.CONTEXTS[contexts.context_key(context)][1] in contexts.CUSTOM_FIELDS and not (
                payload.get("anchor") or payload.get("source")):
            raise HTTPException(422, "Dieser Arbeitsstand braucht einen Datensatzbezug.")
        if payload.get("mode") == "edit" and not payload.get("source"):
            raise HTTPException(422, "Ein Bearbeitungsentwurf braucht seinen Quelldatensatz.")
        if prior is not None and not prior.deleted:
            for key in ("context", "mode", "source", "anchor", "form_key"):
                if payload.get(key) != prior.payload.get(key):
                    raise HTTPException(409, {"code": "draft_identity_conflict", "message": "Der Formularbezug bleibt unverändert."})
            payload["_portfolio_anchors"] = prior.payload.get("_portfolio_anchors", [])
            payload["_source_dependencies"] = prior.payload.get("_source_dependencies", [])
            payload["_anchor_revision"] = prior.payload.get("_anchor_revision")
            payload["_anchor_dependencies"] = prior.payload.get("_anchor_dependencies", [])
            if supplied_anchor_revision and not contexts.same_revision(supplied_anchor_revision, payload.get("_anchor_revision") or ""):
                raise HTTPException(409, {"code": "draft_identity_conflict", "message": "Der Formularbezug bleibt unverändert."})
        else:
            refs = [_anchor(unit, payload.get("anchor"), lock=True)]
            if payload.get("anchor"):
                anchor = payload["anchor"]
                resolved_anchor = contexts.resolve_context(unit.store, anchor["kind"], anchor["id"], unit.actor_id,
                                                          lock=True, include_dependencies=True)
                payload["_anchor_revision"] = supplied_anchor_revision or resolved_anchor["revision"]
                payload["_anchor_dependencies"] = resolved_anchor["dependencies"]
            if payload.get("source"):
                source = payload["source"]
                resolved = contexts.resolve_context(unit.store, source["kind"], source["id"], unit.actor_id,
                                                    lock=True, include_dependencies=True)
                permitted = {contexts.CONTEXTS[contexts.context_key(context)][0]}
                if contexts.context_key(context) == "meters":
                    permitted |= {"meter_reading", "standalone_reading"}
                if contexts.canonical_kind(source["kind"]) not in permitted:
                    raise HTTPException(422, "Quelldatensatz gehört nicht zum Formular.")
                refs.append(resolved)
                payload["_source_dependencies"] = resolved["dependencies"]
            payload["_portfolio_anchors"] = sorted({pid for ref in refs if ref for pid in ref["portfolio_ids"]})
        deleted_source = (payload.get("source") or payload.get("anchor")) if _source_state(unit, payload)["status"] == "deleted" else None
        contexts.validate_values(unit.store, context, payload.get("values", {}), unit.actor_id,
                                 payload.get("field_keys"), deleted_source=deleted_source)
        _authorize(unit, kind, payload, write=True)
        return context, payload
    if kind == "views":
        context = contexts.check_context(unit.actor_id, body["context"])
        name = body["name"].strip()
        if not name:
            raise HTTPException(422, "Bitte der Ansicht einen Namen geben.")
        payload = {"context": context, "anchor": body.get("anchor"), "name": name, "config": body["config"]}
    elif kind == "view-state":
        context = contexts.check_context(unit.actor_id, identifier)
        payload = {"context": context, "anchor": body.get("anchor"), "state": body["state"]}
    elif kind in ("recents", "favorites"):
        entity_kind, entity_id = identifier.split(":", 1)
        entity = contexts.resolve_context(unit.store, entity_kind, entity_id, unit.actor_id, lock=True)
        context, payload = entity["kind"], {"kind": entity["kind"], "entity_id": entity_id}
    else:
        item = _work_item(unit.store, identifier, unit.actor_id)
        if not item.get("can_defer", True):
            raise HTTPException(403, "Dieser Vorgang lässt sich nicht persönlich zurückstellen.")
        try:
            due_on = date.fromisoformat(body["due_on"]).isoformat()
        except (ValueError, TypeError):
            raise HTTPException(422, "Ungültiges Wiedervorlagedatum.") from None
        reason = body["reason"].strip()
        if not reason:
            raise HTTPException(422, "Bitte einen Grund für die Wiedervorlage angeben.")
        context, payload = item["entity_kind"], {"work_item_key": identifier, "due_on": due_on, "reason": reason}
    _authorize(unit, kind, payload, write=True)
    return context, payload


def mutate(store, actor_id: str, kind: str, identifier: str, body: dict, *, delete: bool = False,
             touch: bool = False, rebase: bool = False, source_guard: tuple | None = None) -> dict:
    if kind not in MODELS:
        raise HTTPException(404, "Arbeitsstand nicht gefunden.")
    contexts.validate_json(body)
    if len(identifier) > 240 or not identifier:
        raise HTTPException(422, "Ungültige Kennung des Arbeitsstands.")
    operation = "delete" if delete else "touch" if touch else "rebase" if rebase else "put"
    command_parts = [kind, identifier, operation, body]
    if source_guard is not None:
        command_parts.append(source_guard)
    digest = hashlib.sha256(json.dumps(command_parts, sort_keys=True, ensure_ascii=False,
                                       separators=(",", ":")).encode()).hexdigest()
    for attempt in range(2):
        try:
            with archive.work(store, actor_id, write_areas=("/workspace",)) as unit:
                if source_guard:
                    source_kind, source_id, expected_source = source_guard
                    source = contexts.resolve_context(unit.store, source_kind, source_id, actor_id, lock=True)
                    if not contexts.same_revision(expected_source, source["revision"]):
                        raise HTTPException(409, "Quelle wurde geändert. Bitte Vorschlag erneut prüfen.")
                with contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
                    prior = _get(unit, kind, identifier, lock=True)
                    command = _command(unit, body["idempotency_key"])
                    if command:
                        if command.request_hash != digest:
                            raise HTTPException(409, {"code": "idempotency_conflict", "message": "Der Wiederholungsschlüssel gehört zu einer anderen Änderung."})
                        # Recheck permission before returning even a saved response.
                        response = deepcopy(command.response["result"])
                        saved_payload = command.response["authorization"]
                        _authorize(unit, kind, saved_payload)
                        if not response.get("deleted"):
                            if kind == "drafts":
                                response["source_state"] = _source_state(unit, saved_payload)
                            elif kind in ("favorites", "recents"):
                                entity = contexts.resolve_context(unit.store, saved_payload["kind"], saved_payload["entity_id"], actor_id)
                                response.update(title=entity["title"], href=entity["href"])
                            elif kind == "view-state":
                                _validate_view(unit, response["state"], state=True, read=True)
                        return response
                    if prior is not None and not prior.deleted:
                        _authorize(unit, kind, prior.payload, write=kind != "view-state")
                    if rebase:
                        if kind != "drafts" or prior is None or prior.deleted or not (prior.payload.get("source") or prior.payload.get("anchor")):
                            raise HTTPException(404, "Bearbeitungsentwurf nicht gefunden.")
                        source = prior.payload.get("source") or prior.payload["anchor"]
                        live = contexts.resolve_context(unit.store, source["kind"], source["id"], actor_id,
                                                        lock=True, include_dependencies=True)
                        if not contexts.same_revision(body["source_revision"], live["revision"]):
                            raise HTTPException(409, {"code": "source_conflict", "current_revision": live["revision"]})
                        provided = {(stamp["table"], stamp["id"]): stamp["revision"] for stamp in body["dependency_etags"]}
                        actual = {(stamp["table"], stamp["id"]): stamp["revision"] for stamp in live["dependencies"]}
                        if len(provided) != len(body["dependency_etags"]) or provided.keys() != actual.keys() or any(
                                not contexts.same_revision(provided[key], value) for key, value in actual.items()):
                            raise HTTPException(409, {"code": "source_conflict", "message": "Ein verknüpfter Datensatz wurde geändert. Bitte erneut vergleichen."})
                        context, payload = prior.context, deepcopy(prior.payload)
                        if payload.get("source"):
                            payload["source"]["revision"] = body["source_revision"]
                            payload["_source_dependencies"] = live["dependencies"]
                        else:
                            payload["_anchor_revision"] = body["source_revision"]
                            payload["_anchor_dependencies"] = live["dependencies"]
                        payload["values"] = contexts.recovery_values(body["values"])
                        contexts.validate_values(unit.store, context, payload["values"], actor_id, payload.get("field_keys"))
                    else:
                        context, payload = _prepare(unit, kind, identifier, body, prior, delete=delete)
                    expected = body.get("base_revision", 0)
                    valid = touch or (expected == 0 and (prior is None or prior.deleted)) or (
                        prior is not None and not prior.deleted and expected == prior.revision)
                    if not valid:
                        current = _public(unit, kind, prior) if prior else None
                        raise HTTPException(409, {"code": "workspace_conflict", "current_revision": prior.revision if prior else 0,
                                                  "current": current})
                    row = _put(unit, kind, identifier, context, payload, prior, deleted=delete)
                    response = _public(unit, kind, row)
                    _remember(unit, body["idempotency_key"], digest, response, payload)
                    return response
        except IntegrityError:
            if attempt:
                raise HTTPException(409, {"code": "workspace_conflict", "message": "Eine gleichzeitige Änderung wurde gespeichert. Bitte neu laden."}) from None
    raise AssertionError("unreachable")


def _cursor(raw: str | None, owner: str, kind: str, context: str | None) -> tuple[datetime, str] | None:
    if raw is None:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        if data[:3] != [owner, kind, context]:
            raise ValueError
        return datetime.fromisoformat(data[3]), data[4]
    except (ValueError, TypeError, IndexError):
        raise HTTPException(422, "Ungültiger Seitencursor.") from None


def _next_cursor(owner: str, kind: str, context: str | None, stamp: datetime, identifier: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([owner, kind, context, stamp.isoformat(), identifier]).encode()).decode().rstrip("=")


def list_records(store, actor_id: str, kind: str, *, context: str | None = None, cursor: str | None = None,
                 limit: int = 50, due_before: date | None = None, form_key: str | None = None) -> dict:
    if kind not in MODELS or not 1 <= limit <= 200:
        raise HTTPException(422, "Ungültige Liste persönlicher Arbeitsstände.")
    if context:
        context = contexts.check_context(actor_id, context, edit=kind == "drafts")
    after = _cursor(cursor, actor_id, kind, context)
    with archive.work(store, actor_id) as unit:
        with contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
            order = "updated_at" if kind == "recents" else "created_at"
            # Fetch one bounded raw page. Hidden rows consume cursor positions,
            # never a global cap; clients may continue even an empty page.
            if unit.db is None:
                rows = [row for row in _memory(unit.store, kind).values() if row.owner_user_id == actor_id
                        and not row.deleted and (context is None or row.context == context)
                        and (after is None or (getattr(row, order), row.id) < after)]
                rows = sorted(rows, key=lambda row: (getattr(row, order), row.id), reverse=True)[:limit + 1]
            else:
                model = MODELS[kind]
                column = getattr(model, order)
                statement = select(model).where(model.owner_user_id == actor_id, model.deleted.is_(False))
                if context is not None:
                    statement = statement.where(model.context == context)
                if after is not None:
                    statement = statement.where(or_(column < after[0], and_(column == after[0], model.id < after[1])))
                rows = list(unit.db.scalars(statement.order_by(column.desc(), model.id.desc()).limit(limit + 1)))
            items = []
            for row in rows[:limit]:
                if due_before is not None and row.payload.get("due_on", "9999-12-31") > due_before.isoformat():
                    continue
                if form_key is not None and row.payload.get("form_key", "") != form_key:
                    continue
                try:
                    _authorize(unit, kind, row.payload)
                    items.append(_public(unit, kind, row))
                except HTTPException as exc:
                    if exc.status_code not in (403, 404):
                        raise
            following = _next_cursor(actor_id, kind, context, getattr(rows[limit - 1], order), rows[limit - 1].id) \
                if len(rows) > limit else None
            return {"items": items, "next_cursor": following}


def deferrals_for(store, keys: list[str], actor_id: str) -> dict[str, dict]:
    """Private decoration for a page of work items already authorized by its resolver."""
    wanted = set(keys)
    if not wanted:
        return {}
    user = contexts.actor(actor_id, store)
    unit = SimpleNamespace(store=store, db=getattr(store, "db", None), actor_id=actor_id, user=user)
    if unit.db is None:
        rows = [row for row in _memory(store, "deferrals").values()
                if row.owner_user_id == actor_id and row.id in wanted and not row.deleted]
    else:
        model = WorkspaceDeferralORM
        rows = list(unit.db.scalars(select(model).where(model.owner_user_id == actor_id,
                                model.id.in_(wanted), model.deleted.is_(False))))
    return {row.id: _public(unit, "deferrals", row) for row in rows}


def deferral_for(store, key: str, actor_id: str, *, check_item: bool = True) -> dict | None:
    if check_item:
        _work_item(store, key, actor_id)
    return deferrals_for(store, [key], actor_id).get(key)
