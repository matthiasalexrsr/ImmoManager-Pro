"""Atomic P1/P2 tenancy workflow core.

No startup/recovery/privacy registration lives here; Root integrates those
boundaries. This service owns versioned templates, frozen change snapshots,
step execution, task projection and evidence links without financial writes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from heapq import nlargest
from time import time
from typing import Any, Iterable, NoReturn
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from .. import auth
from ..config import settings
from ..db.orm_models import HandoverProtocolORM, MeterReadingORM, TenantORM
from ..db.tenancy_workflow_models import (
    TENANCY_WORKFLOW_MODELS,
    TenancyChangeORM,
    WorkflowCommandORM,
    WorkflowEvidenceLinkORM,
    WorkflowStepInstanceORM,
    WorkflowTemplateORM,
    WorkflowTemplateStepORM,
    WorkflowTemplateVersionORM,
)
from ..models import TaskCreate
from ..permissions import may_write_resource
from ..storage import NotFoundError, ValidationError
from .concurrency import etag
from .contract_occupancy import begin_writer, lock_location
from .payments import _memory_lock
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scope_context, scope_from_user
from .tenancy_workflow_types import (
    AddEvidence,
    ChangeSelection,
    CompleteTenancyChange,
    CreateStepTask,
    CreateTemplate,
    CreateTemplateVersion,
    PatchTenancyChange,
    PreviewTenancyChange,
    PublishTemplateVersion,
    ReanchorPreview,
    ReanchorTenancyChange,
    RemoveEvidence,
    StartTenancyChange,
    TemplateStepInput,
    UpdateStep,
    UpdateTemplateVersion,
)

MANAGER_ROLES = frozenset({"eigentuemer", "verwalter"})
CURSOR_LIFETIME = 3600
_TASK_WRITE_STEP: ContextVar[str | None] = ContextVar("tenancy_workflow_task_write", default=None)


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def conflict(message: str = "Der Vorgang wurde zwischenzeitlich geändert. Aktuellen Stand laden.") -> HTTPException:
    return HTTPException(409, message)


def workflow_etag(kind: str, identifier: str, revision: str) -> str:
    return f'"immo-workflow-v1:{kind}:{identifier}:{revision}"'


def _revision(row: Any, expected: str) -> None:
    if row.revision != expected:
        raise conflict()


def _scope_binding(scope: Any) -> dict[str, Any]:
    return {
        "user_id": scope.user_id,
        "role": scope.role,
        "unrestricted": scope.unrestricted,
        "portfolio_ids": list(scope.portfolio_ids),
    }


def _cursor_signature(payload: bytes) -> bytes:
    return hmac.new(
        settings.jwt_secret_key.encode(),
        b"immo-tenancy-workflow-cursor-v1\0" + payload,
        hashlib.sha256,
    ).digest()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    if not value or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in value):
        raise ValueError("invalid base64")
    result = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if _b64(result) != value:
        raise ValueError("noncanonical base64")
    return result


def encode_cursor(binding: dict[str, Any], position: list[Any]) -> str:
    issued = int(time())
    payload = canonical(
        {"v": 1, "binding": binding, "position": position, "issued": issued, "expires": issued + CURSOR_LIFETIME}
    )
    return _b64(payload) + "." + _b64(_cursor_signature(payload))


def decode_cursor(cursor: str | None, binding: dict[str, Any]) -> list[Any] | None:
    if cursor is None:
        return None
    try:
        left, right = cursor.split(".", 1)
        payload, signature = _unb64(left), _unb64(right)
        if not hmac.compare_digest(signature, _cursor_signature(payload)):
            raise ValueError("signature")
        value = json.loads(payload)
        if set(value) != {"v", "binding", "position", "issued", "expires"} or value["v"] != 1:
            raise ValueError("shape")
        current = int(time())
        if value["issued"] > current + 60 or current >= value["expires"]:
            raise ValueError("expired")
        if not hmac.compare_digest(digest(value["binding"]), digest(binding)):
            raise ValueError("binding")
        if not isinstance(value["position"], list):
            raise ValueError("position")
        return value["position"]
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError):
        raise HTTPException(422, "Ungültige oder abgelaufene Workflow-Seite. Erste Seite neu laden.") from None


def _identity(actor_id: str) -> tuple[dict[str, Any], Any]:
    user = auth.get_user_by_id(actor_id)
    if not user or not user["is_active"]:
        raise HTTPException(401, "Anmeldung nicht mehr gültig.")
    captured = current_scope()
    if captured is not None and captured.user_id != actor_id:
        raise HTTPException(403, "Ungültige Benutzerbindung.")
    scope = refresh_scope(captured) if captured is not None else scope_from_user(user)
    return user, scope


def _can_manage(user: dict[str, Any]) -> bool:
    return user["role"] in MANAGER_ROLES


def _require_manager(user: dict[str, Any]) -> None:
    if not _can_manage(user):
        raise HTTPException(403, "Nur Eigentümer oder Verwaltung dürfen Mieterwechsel konfigurieren.")


class Work:
    def __init__(self, store: Any, db: Session | None, scope: Any, user: dict[str, Any]):
        self.store, self.db, self.scope, self.user = store, db, scope, user
        self.undo: dict[tuple[str, str], tuple[bool, Any]] = {}

    def touch(self, collection: str, identifier: str, *, inserted: bool = False) -> None:
        if self.db is None and (collection, identifier) not in self.undo:
            rows = self.store.__dict__.setdefault(collection, {})
            self.undo[collection, identifier] = (
                identifier in rows and not inserted,
                deepcopy(rows.get(identifier)) if not inserted else None,
            )

    def add(self, row: Any) -> None:
        if self.db is not None:
            self.db.add(row)
            self.db.flush()
        else:
            self.touch(row.__tablename__, row.id, inserted=True)
            self.store.__dict__.setdefault(row.__tablename__, {})[row.id] = row

    def rollback(self) -> None:
        for (collection, identifier), (present, value) in reversed(list(self.undo.items())):
            rows = self.store.__dict__.setdefault(collection, {})
            if present:
                rows[identifier] = value
            else:
                rows.pop(identifier, None)


@contextmanager
def work(store: Any, actor_id: str, *, write: bool = False):
    sql = hasattr(store, "db")
    if not sql:
        from .tenant_privacy import _memory_privacy_lock
    with nullcontext() if sql else _memory_privacy_lock():
        user, captured = _identity(actor_id)
        with scope_context(captured), (nullcontext() if sql else _memory_lock):
            if sql:
                from ..repositories.sql_store import SQLAlchemyStore

                bind = store.db.get_bind()
                db = Session(getattr(bind, "engine", bind), autoflush=False, expire_on_commit=False)
                active = SQLAlchemyStore(db)
            else:
                db, active = None, store
                for model in TENANCY_WORKFLOW_MODELS:
                    active.__dict__.setdefault(model.__tablename__, {})
            unit = Work(active, db, captured, user)
            try:
                if db is not None and write:
                    begin_writer(db)
                    if isinstance(auth._user_store, auth.SQLUserStore):
                        auth._user_store._lock_management(db)
                        refresh_scope(captured)
                yield unit
                refresh_scope(captured)
                latest = auth.get_user_by_id(actor_id)
                if not latest or not latest["is_active"] or latest["role"] != user["role"]:
                    raise HTTPException(403, "Berechtigung wurde während des Vorgangs geändert.")
                if db is not None and write:
                    db.commit()
            except BaseException:
                if db is not None:
                    db.rollback()
                else:
                    unit.rollback()
                raise
            finally:
                if db is not None:
                    db.close()


def _row(unit: Work, model: Any, identifier: str, *, lock: bool = False):
    if unit.db is not None:
        query = select(model).where(model.id == identifier)
        if lock:
            query = query.with_for_update()
        return unit.db.scalar(query)
    return unit.store.__dict__.get(model.__tablename__, {}).get(identifier)


def _rows(unit: Work, model: Any) -> Iterable[Any]:
    if unit.db is not None:
        return unit.db.scalars(select(model))
    return unit.store.__dict__.get(model.__tablename__, {}).values()


def _property_unit(unit: Work, property_id: str, unit_id: str | None, *, lock: bool = False):
    if unit_id is not None:
        if lock:
            prop, location = lock_location(unit.store, property_id, unit_id)
        else:
            prop, location = unit.store.get_property(property_id), unit.store.get_unit(unit_id)
        if location.property_id != property_id:
            raise ValidationError("Einheit gehört nicht zur Immobilie.")
    else:
        prop, location = unit.store.get_property(property_id), None
        if lock and unit.db is not None:
            from ..db.orm_models import PropertyORM

            if unit.db.scalar(select(PropertyORM.id).where(PropertyORM.id == property_id).with_for_update()) is None:
                raise NotFoundError("Immobilie nicht gefunden")
            prop = unit.store.get_property(property_id)
    unit.store.get_portfolio(prop.portfolio_id)
    return prop, location


def _user_has_portfolio(user: dict[str, Any], portfolio_id: str) -> bool:
    return user["role"] == "eigentuemer" or user.get("portfolio_access") == "all" or portfolio_id in set(
        user.get("portfolio_ids") or []
    )


def _validate_assignment(portfolio_id: str, step: TemplateStepInput) -> None:
    if step.assignee_role:
        if not may_write_resource(step.assignee_role, "tasks"):
            raise ValidationError("Die verantwortliche Rolle darf operative Aufgaben nicht bearbeiten.")
    if step.assignee_user_id:
        assigned = auth.get_user_by_id(step.assignee_user_id)
        if (
            not assigned
            or not assigned["is_active"]
            or not may_write_resource(assigned["role"], "tasks")
            or not _user_has_portfolio(assigned, portfolio_id)
        ):
            raise ValidationError("Der verantwortliche Benutzer ist nicht aktiv und für dieses Portfolio berechtigt.")


def _validate_steps(portfolio_id: str, steps: list[TemplateStepInput]) -> None:
    if not steps:
        raise ValidationError("Eine Workflowvorlage benötigt mindestens einen Schritt.")
    keys = [step.stable_key for step in steps]
    positions = [step.position for step in steps]
    if len(keys) != len(set(keys)) or len(positions) != len(set(positions)):
        raise ValidationError("Schrittschlüssel und Positionen müssen innerhalb einer Fassung eindeutig sein.")
    known = set(keys)
    graph = {step.stable_key: tuple(step.depends_on_step_keys) for step in steps}
    for step in steps:
        _validate_assignment(portfolio_id, step)
        if step.stable_key in step.depends_on_step_keys or any(dep not in known for dep in step.depends_on_step_keys):
            raise ValidationError("Jede Abhängigkeit muss auf einen anderen Schritt derselben Fassung zeigen.")
    # Iterative Kahn validation; no recursion depth and no silent disabled predecessor.
    indegree = {key: 0 for key in known}
    outgoing: dict[str, list[str]] = {key: [] for key in known}
    for key, dependencies in graph.items():
        indegree[key] = len(dependencies)
        for dependency in dependencies:
            outgoing[dependency].append(key)
    ready = [key for key, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        current = ready.pop()
        visited += 1
        for follower in outgoing[current]:
            indegree[follower] -= 1
            if indegree[follower] == 0:
                ready.append(follower)
    if visited != len(known):
        raise ValidationError("Workflow-Abhängigkeiten enthalten einen Zyklus.")


def _template_steps(unit: Work, version_id: str) -> list[Any]:
    if unit.db is not None:
        return list(
            unit.db.scalars(
                select(WorkflowTemplateStepORM)
                .where(WorkflowTemplateStepORM.version_id == version_id)
                .order_by(WorkflowTemplateStepORM.position, WorkflowTemplateStepORM.id)
            )
        )
    return sorted(
        (
            row
            for row in unit.store.__dict__[WorkflowTemplateStepORM.__tablename__].values()
            if row.version_id == version_id
        ),
        key=lambda row: (row.position, row.id),
    )


def _step_input(row: Any) -> TemplateStepInput:
    return TemplateStepInput(
        stable_key=row.stable_key,
        position=row.position,
        title=row.title,
        description=row.description,
        default_requirement=row.default_requirement,
        anchor=row.anchor,
        offset_days=row.offset_days,
        assignee_user_id=row.assignee_user_id,
        assignee_role=row.assignee_role,
        depends_on_step_keys=list(row.depends_on_step_keys),
        evidence_requirement=row.evidence_requirement,
    )


def _template_actions(user: dict[str, Any], row: Any) -> dict[str, bool]:
    manager = _can_manage(user)
    return {
        "edit_template": bool(manager and row.state == "draft"),
        "publish_template": bool(manager and row.state == "draft"),
        "edit_change": False,
        "reanchor": False,
        "complete_step": False,
        "link_task": False,
        "link_document": False,
        "complete_change": False,
    }


def _version_public(unit: Work, row: Any) -> dict[str, Any]:
    steps = [
        {
            "id": step.id,
            "stable_key": step.stable_key,
            "position": step.position,
            "title": step.title,
            "description": step.description,
            "default_requirement": step.default_requirement,
            "anchor": step.anchor,
            "offset_days": step.offset_days,
            "assignee_user_id": step.assignee_user_id,
            "assignee_role": step.assignee_role,
            "depends_on_step_keys": list(step.depends_on_step_keys),
            "evidence_requirement": step.evidence_requirement,
        }
        for step in _template_steps(unit, row.id)
    ]
    return {
        "id": row.id,
        "template_id": row.template_id,
        "portfolio_id": row.portfolio_id,
        "property_id": row.property_id,
        "unit_id": row.unit_id,
        "direction": row.direction,
        "version": row.version,
        "state": row.state,
        "based_on_version_id": row.based_on_version_id,
        "revision": row.revision,
        "etag": workflow_etag("template-version", row.id, row.revision),
        "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "published_at": row.published_at.replace(tzinfo=timezone.utc).isoformat() if row.published_at else None,
        "steps": steps,
        "actions": _template_actions(unit.user, row),
    }


def _request_hash(operation: str, payload: Any) -> str:
    value = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    return digest({"operation": operation, "payload": value})


def _command(unit: Work, actor_id: str, key: str, operation: str, request_hash: str):
    if unit.db is not None:
        saved = unit.db.scalar(
            select(WorkflowCommandORM)
            .where(WorkflowCommandORM.actor_id == actor_id, WorkflowCommandORM.idempotency_key == key)
            .limit(1)
        )
    else:
        saved = next(
            (
                row
                for row in unit.store.__dict__[WorkflowCommandORM.__tablename__].values()
                if row.actor_id == actor_id and row.idempotency_key == key
            ),
            None,
        )
    if saved is None:
        return None
    if saved.operation != operation or saved.request_sha256 != request_hash:
        raise conflict("Die Wiederholungsreferenz wurde bereits mit anderen Eingaben verwendet.")
    return deepcopy(saved.response)


def _save_command(
    unit: Work,
    actor_id: str,
    key: str,
    operation: str,
    subject_type: str,
    subject_id: str,
    portfolio_id: str,
    request_hash: str,
    response: dict[str, Any],
) -> dict[str, Any]:
    unit.add(
        WorkflowCommandORM(
            id=str(uuid4()),
            portfolio_id=portfolio_id,
            actor_id=actor_id,
            idempotency_key=key,
            operation=operation,
            subject_type=subject_type,
            subject_id=subject_id,
            request_sha256=request_hash,
            response=deepcopy(response),
            created_at=now(),
        )
    )
    return response


def _insert_template_steps(unit: Work, version_id: str, steps: list[TemplateStepInput]) -> None:
    for step in sorted(steps, key=lambda value: (value.position, value.stable_key)):
        unit.add(
            WorkflowTemplateStepORM(
                id=str(uuid4()),
                version_id=version_id,
                stable_key=step.stable_key,
                position=step.position,
                title=step.title,
                description=step.description,
                default_requirement=step.default_requirement,
                anchor=step.anchor,
                offset_days=step.offset_days,
                assignee_user_id=step.assignee_user_id,
                assignee_role=step.assignee_role,
                depends_on_step_keys=list(step.depends_on_step_keys),
                evidence_requirement=step.evidence_requirement,
            )
        )


def _delete_draft_steps(unit: Work, version_id: str) -> None:
    rows = _template_steps(unit, version_id)
    if unit.db is not None:
        for row in rows:
            unit.db.delete(row)
        unit.db.flush()
    else:
        collection = unit.store.__dict__[WorkflowTemplateStepORM.__tablename__]
        for row in rows:
            unit.touch(WorkflowTemplateStepORM.__tablename__, row.id)
            collection.pop(row.id, None)


def _load_template(unit: Work, template_id: str, *, lock: bool = False):
    row = _row(unit, WorkflowTemplateORM, template_id)
    if row is None:
        raise HTTPException(404, "Workflowvorlage nicht gefunden.")
    binding = (row.portfolio_id, row.property_id, row.unit_id, row.direction)
    _property_unit(unit, row.property_id, row.unit_id, lock=lock)
    if lock:
        row = _row(unit, WorkflowTemplateORM, template_id, lock=True)
        if row is None or binding != (row.portfolio_id, row.property_id, row.unit_id, row.direction):
            raise conflict("Die Vorlagenzuordnung wurde parallel geändert.")
    return row


def _load_version(unit: Work, version_id: str, *, lock: bool = False):
    row = _row(unit, WorkflowTemplateVersionORM, version_id)
    if row is None:
        raise HTTPException(404, "Vorlagenfassung nicht gefunden.")
    binding = (
        row.template_id,
        row.portfolio_id,
        row.property_id,
        row.unit_id,
        row.direction,
        row.version,
    )
    _property_unit(unit, row.property_id, row.unit_id, lock=lock)
    if lock:
        if _row(unit, WorkflowTemplateORM, row.template_id, lock=True) is None:
            raise HTTPException(404, "Workflowvorlage nicht gefunden.")
        row = _row(unit, WorkflowTemplateVersionORM, version_id, lock=True)
        if row is None or binding != (
            row.template_id,
            row.portfolio_id,
            row.property_id,
            row.unit_id,
            row.direction,
            row.version,
        ):
            raise conflict("Die Vorlagenfassung wurde parallel verschoben oder ersetzt.")
    return row


def create_template(store: Any, payload: CreateTemplate, actor_id: str) -> dict[str, Any]:
    with work(store, actor_id, write=True) as unit:
        _require_manager(unit.user)
        prop, _ = _property_unit(unit, payload.property_id, payload.unit_id, lock=True)
        request_hash = _request_hash("create_template", payload)
        replay = _command(unit, actor_id, payload.idempotency_key, "create_template", request_hash)
        if replay is not None:
            return replay
        _validate_steps(prop.portfolio_id, payload.steps)
        if unit.db is not None:
            duplicate = unit.db.scalar(
                select(WorkflowTemplateORM.id).where(
                    WorkflowTemplateORM.property_id == payload.property_id,
                    WorkflowTemplateORM.unit_id.is_(None)
                    if payload.unit_id is None
                    else WorkflowTemplateORM.unit_id == payload.unit_id,
                    WorkflowTemplateORM.direction == payload.direction,
                ).limit(1)
            )
        else:
            duplicate = next(
                (
                    row.id
                    for row in unit.store.__dict__[WorkflowTemplateORM.__tablename__].values()
                    if row.property_id == payload.property_id
                    and row.unit_id == payload.unit_id
                    and row.direction == payload.direction
                ),
                None,
            )
        if duplicate is not None:
            raise conflict("Für Immobilie/Einheit und Richtung besteht bereits eine Workflowvorlage.")
        stamp = now()
        template = WorkflowTemplateORM(
            id=str(uuid4()),
            portfolio_id=prop.portfolio_id,
            property_id=payload.property_id,
            unit_id=payload.unit_id,
            direction=payload.direction,
            created_by=actor_id,
            created_at=stamp,
        )
        version = WorkflowTemplateVersionORM(
            id=str(uuid4()),
            template_id=template.id,
            portfolio_id=prop.portfolio_id,
            property_id=payload.property_id,
            unit_id=payload.unit_id,
            direction=payload.direction,
            version=1,
            state="draft",
            based_on_version_id=None,
            revision=str(uuid4()),
            created_by=actor_id,
            created_at=stamp,
            published_at=None,
        )
        unit.add(template)
        unit.add(version)
        _insert_template_steps(unit, version.id, payload.steps)
        response = _version_public(unit, version)
        return _save_command(
            unit,
            actor_id,
            payload.idempotency_key,
            "create_template",
            "template",
            template.id,
            prop.portfolio_id,
            request_hash,
            response,
        )


def get_template_version(store: Any, version_id: str, actor_id: str) -> dict[str, Any]:
    with work(store, actor_id) as unit:
        _require_manager(unit.user)
        return _version_public(unit, _load_version(unit, version_id))


def get_template(store: Any, template_id: str, actor_id: str) -> dict[str, Any]:
    with work(store, actor_id) as unit:
        _require_manager(unit.user)
        template = _load_template(unit, template_id)
        if unit.db is not None:
            row = unit.db.scalar(
                select(WorkflowTemplateVersionORM)
                .where(WorkflowTemplateVersionORM.template_id == template.id)
                .order_by(WorkflowTemplateVersionORM.version.desc(), WorkflowTemplateVersionORM.id.desc())
                .limit(1)
            )
        else:
            row = max(
                (
                    value
                    for value in unit.store.__dict__[WorkflowTemplateVersionORM.__tablename__].values()
                    if value.template_id == template.id
                ),
                key=lambda value: (value.version, value.id),
                default=None,
            )
        if row is None:
            raise HTTPException(503, "Workflowvorlage besitzt keine Fassung.")
        return _version_public(unit, row)


def _check_page_limit(limit: int) -> None:
    maximum = settings.tenancy_workflow_page_max_size
    if type(limit) is not int or not 1 <= limit <= maximum:
        raise HTTPException(422, f"Seitengröße muss zwischen 1 und {maximum} liegen.")


def _page_binding(unit: Work, kind: str, filters: dict[str, Any], limit: int) -> dict[str, Any]:
    return {
        "kind": kind,
        "filters": filters,
        "limit": limit,
        "scope": _scope_binding(unit.scope),
    }


def list_templates(
    store: Any,
    actor_id: str,
    *,
    property_id: str | None = None,
    unit_id: str | None = None,
    direction: str | None = None,
    after: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    _check_page_limit(limit)
    with work(store, actor_id) as unit:
        _require_manager(unit.user)
        effective_property_id = property_id
        if unit_id is not None:
            location = unit.store.get_unit(unit_id)
            if property_id is not None and location.property_id != property_id:
                raise ValidationError("Einheit gehört nicht zur gefilterten Immobilie.")
            effective_property_id = location.property_id
        filters = {
            "property_id": effective_property_id,
            "unit_id": unit_id,
            "direction": direction,
        }
        binding = _page_binding(unit, "workflow_templates", filters, limit)
        point = decode_cursor(after, binding)
        point_time: datetime | None
        point_id: str | None
        if point is not None:
            try:
                if len(point) != 2 or not all(isinstance(item, str) for item in point):
                    raise ValueError
                point_time = datetime.fromisoformat(point[0])
                if point_time.tzinfo is not None or not point[1]:
                    raise ValueError
                point_id = point[1]
            except (TypeError, ValueError):
                raise HTTPException(422, "Ungültige Workflow-Seite.") from None
        else:
            point_time = point_id = None
        if unit.db is not None:
            latest = (
                select(
                    WorkflowTemplateVersionORM.template_id,
                    func.max(WorkflowTemplateVersionORM.version).label("latest_version"),
                )
                .group_by(WorkflowTemplateVersionORM.template_id)
                .subquery()
            )
            query = select(WorkflowTemplateVersionORM).join(
                latest,
                and_(
                    latest.c.template_id == WorkflowTemplateVersionORM.template_id,
                    latest.c.latest_version == WorkflowTemplateVersionORM.version,
                ),
            )
            if effective_property_id is not None:
                query = query.where(WorkflowTemplateVersionORM.property_id == effective_property_id)
            if unit_id is not None:
                query = query.where(
                    or_(
                        WorkflowTemplateVersionORM.unit_id.is_(None),
                        WorkflowTemplateVersionORM.unit_id == unit_id,
                    )
                )
            if direction is not None:
                query = query.where(WorkflowTemplateVersionORM.direction == direction)
            if point_time is not None:
                query = query.where(
                    or_(
                        WorkflowTemplateVersionORM.created_at < point_time,
                        and_(
                            WorkflowTemplateVersionORM.created_at == point_time,
                            WorkflowTemplateVersionORM.id < point_id,
                        ),
                    )
                )
            selected = list(
                unit.db.scalars(
                    query.order_by(
                        WorkflowTemplateVersionORM.created_at.desc(),
                        WorkflowTemplateVersionORM.id.desc(),
                    ).limit(limit + 1)
                )
            )
        else:
            latest_by_template: dict[str, Any] = {}
            for row in unit.store.__dict__[WorkflowTemplateVersionORM.__tablename__].values():
                if not memory_visible(
                    unit.store, WorkflowTemplateVersionORM.__tablename__, row, scope=unit.scope
                ):
                    continue
                current = latest_by_template.get(row.template_id)
                if current is None or (row.version, row.id) > (current.version, current.id):
                    latest_by_template[row.template_id] = row
            values = (
                row
                for row in latest_by_template.values()
                if (effective_property_id is None or row.property_id == effective_property_id)
                and (unit_id is None or row.unit_id in {None, unit_id})
                and (direction is None or row.direction == direction)
                and (point_time is None or (row.created_at, row.id) < (point_time, point_id))
            )
            selected = nlargest(limit + 1, values, key=lambda row: (row.created_at, row.id))
        has_more = len(selected) > limit
        items = selected[:limit]
        return {
            "items": [_version_public(unit, row) for row in items],
            "next_cursor": encode_cursor(binding, [items[-1].created_at.isoformat(), items[-1].id])
            if has_more and items
            else None,
            "has_more": has_more,
        }


def list_template_versions(
    store: Any,
    template_id: str,
    actor_id: str,
    *,
    after: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    _check_page_limit(limit)
    with work(store, actor_id) as unit:
        _require_manager(unit.user)
        template = _load_template(unit, template_id)
        binding = _page_binding(unit, "workflow_template_versions", {"template_id": template.id}, limit)
        point = decode_cursor(after, binding)
        if point is None:
            version_point = id_point = None
        elif (
            len(point) != 2
            or type(point[0]) is not int
            or point[0] < 1
            or not isinstance(point[1], str)
            or not point[1]
        ):
            raise HTTPException(422, "Ungültige Vorlagenversionsseite.")
        else:
            version_point, id_point = point[0], point[1]
        if unit.db is not None:
            query = select(WorkflowTemplateVersionORM).where(
                WorkflowTemplateVersionORM.template_id == template.id
            )
            if version_point is not None:
                query = query.where(
                    or_(
                        WorkflowTemplateVersionORM.version < version_point,
                        and_(
                            WorkflowTemplateVersionORM.version == version_point,
                            WorkflowTemplateVersionORM.id < id_point,
                        ),
                    )
                )
            selected = list(
                unit.db.scalars(
                    query.order_by(
                        WorkflowTemplateVersionORM.version.desc(),
                        WorkflowTemplateVersionORM.id.desc(),
                    ).limit(limit + 1)
                )
            )
        else:
            selected = nlargest(
                limit + 1,
                (
                    row
                    for row in unit.store.__dict__[WorkflowTemplateVersionORM.__tablename__].values()
                    if row.template_id == template.id
                    and memory_visible(
                        unit.store, WorkflowTemplateVersionORM.__tablename__, row, scope=unit.scope
                    )
                    and (
                        version_point is None
                        or (row.version, row.id) < (version_point, id_point)
                    )
                ),
                key=lambda row: (row.version, row.id),
            )
        has_more = len(selected) > limit
        items = selected[:limit]
        return {
            "items": [_version_public(unit, row) for row in items],
            "next_cursor": encode_cursor(binding, [items[-1].version, items[-1].id])
            if has_more and items
            else None,
            "has_more": has_more,
        }


def create_template_version(
    store: Any, template_id: str, payload: CreateTemplateVersion, actor_id: str
) -> dict[str, Any]:
    with work(store, actor_id, write=True) as unit:
        _require_manager(unit.user)
        template = _load_template(unit, template_id, lock=True)
        based = _load_version(unit, payload.based_on_version_id, lock=True)
        if based.template_id != template.id:
            raise HTTPException(404, "Ausgangsfassung gehört nicht zu dieser Vorlage.")
        request_hash = _request_hash("create_template_version", payload)
        replay = _command(unit, actor_id, payload.idempotency_key, "create_template_version", request_hash)
        if replay is not None:
            return replay
        _revision(based, payload.expected_revision)
        if based.state not in {"published", "retired"}:
            raise conflict("Neue Fassungen werden aus einer veröffentlichten/ausgemusterten Fassung erzeugt.")
        if unit.db is not None:
            maximum = unit.db.scalar(
                select(func.max(WorkflowTemplateVersionORM.version)).where(
                    WorkflowTemplateVersionORM.template_id == template.id
                )
            )
        else:
            maximum = max(
                (
                    row.version
                    for row in unit.store.__dict__[WorkflowTemplateVersionORM.__tablename__].values()
                    if row.template_id == template.id
                ),
                default=0,
            )
        stamp = now()
        created = WorkflowTemplateVersionORM(
            id=str(uuid4()),
            template_id=template.id,
            portfolio_id=template.portfolio_id,
            property_id=template.property_id,
            unit_id=template.unit_id,
            direction=template.direction,
            version=int(maximum or 0) + 1,
            state="draft",
            based_on_version_id=based.id,
            revision=str(uuid4()),
            created_by=actor_id,
            created_at=stamp,
            published_at=None,
        )
        copied = [_step_input(row) for row in _template_steps(unit, based.id)]
        _validate_steps(template.portfolio_id, copied)
        unit.add(created)
        _insert_template_steps(unit, created.id, copied)
        response = _version_public(unit, created)
        return _save_command(
            unit,
            actor_id,
            payload.idempotency_key,
            "create_template_version",
            "template_version",
            created.id,
            template.portfolio_id,
            request_hash,
            response,
        )


def update_template_version(
    store: Any, version_id: str, payload: UpdateTemplateVersion, actor_id: str
) -> dict[str, Any]:
    with work(store, actor_id, write=True) as unit:
        _require_manager(unit.user)
        row = _load_version(unit, version_id, lock=True)
        request_hash = _request_hash("update_template_version", payload)
        replay = _command(unit, actor_id, payload.idempotency_key, "update_template_version", request_hash)
        if replay is not None:
            return replay
        _revision(row, payload.expected_revision)
        if row.state != "draft":
            raise conflict("Veröffentlichte oder ausgemusterte Fassungen bleiben unverändert.")
        _validate_steps(row.portfolio_id, payload.steps)
        _delete_draft_steps(unit, row.id)
        _insert_template_steps(unit, row.id, payload.steps)
        if unit.db is None:
            unit.touch(WorkflowTemplateVersionORM.__tablename__, row.id)
        row.revision = str(uuid4())
        if unit.db is not None:
            unit.db.flush()
        response = _version_public(unit, row)
        return _save_command(
            unit,
            actor_id,
            payload.idempotency_key,
            "update_template_version",
            "template_version",
            row.id,
            row.portfolio_id,
            request_hash,
            response,
        )


def publish_template_version(
    store: Any, version_id: str, payload: PublishTemplateVersion, actor_id: str
) -> dict[str, Any]:
    with work(store, actor_id, write=True) as unit:
        _require_manager(unit.user)
        row = _load_version(unit, version_id, lock=True)
        request_hash = _request_hash("publish_template_version", payload)
        replay = _command(unit, actor_id, payload.idempotency_key, "publish_template_version", request_hash)
        if replay is not None:
            return replay
        _revision(row, payload.expected_revision)
        if row.state != "draft":
            raise conflict("Nur ein Entwurf kann veröffentlicht werden.")
        steps = [_step_input(value) for value in _template_steps(unit, row.id)]
        _validate_steps(row.portfolio_id, steps)
        if unit.db is not None:
            previous = list(
                unit.db.scalars(
                    select(WorkflowTemplateVersionORM)
                    .where(
                        WorkflowTemplateVersionORM.template_id == row.template_id,
                        WorkflowTemplateVersionORM.state == "published",
                        WorkflowTemplateVersionORM.id != row.id,
                    )
                    .with_for_update()
                )
            )
        else:
            previous = [
                value
                for value in unit.store.__dict__[WorkflowTemplateVersionORM.__tablename__].values()
                if value.template_id == row.template_id and value.state == "published" and value.id != row.id
            ]
        stamp = now()
        for old in previous:
            if unit.db is None:
                unit.touch(WorkflowTemplateVersionORM.__tablename__, old.id)
            old.state = "retired"
            old.revision = str(uuid4())
        if unit.db is None:
            unit.touch(WorkflowTemplateVersionORM.__tablename__, row.id)
        row.state, row.published_at, row.revision = "published", stamp, str(uuid4())
        if unit.db is not None:
            unit.db.flush()
        response = _version_public(unit, row)
        return _save_command(
            unit,
            actor_id,
            payload.idempotency_key,
            "publish_template_version",
            "template_version",
            row.id,
            row.portfolio_id,
            request_hash,
            response,
        )


def _contract_etag(contract: Any) -> str:
    return etag("contracts", contract.id, contract.updated_at)


def _lock_contract(unit: Work, identifier: str):
    contract = unit.store.get_contract(identifier)
    if unit.db is not None:
        from ..db.orm_models import ContractORM

        if unit.db.scalar(select(ContractORM.id).where(ContractORM.id == identifier).with_for_update()) is None:
            raise NotFoundError("Vertrag nicht gefunden")
        contract = unit.store.get_contract(identifier)
    return contract


def _contract_snapshot(contract: Any) -> dict[str, Any]:
    return {
        "id": contract.id,
        "contract_number": contract.contract_number,
        "property_id": contract.property_id,
        "unit_id": contract.unit_id,
        "tenant_id": contract.tenant_id,
        "start_date": contract.start_date.isoformat(),
        "end_date": contract.end_date.isoformat() if contract.end_date else None,
        "status": contract.status,
        "updated_at": contract.updated_at.astimezone(timezone.utc).isoformat()
        if contract.updated_at.tzinfo
        else contract.updated_at.replace(tzinfo=timezone.utc).isoformat(),
        "etag": _contract_etag(contract),
    }


def _template_snapshot(unit: Work, row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "template_id": row.template_id,
        "property_id": row.property_id,
        "unit_id": row.unit_id,
        "direction": row.direction,
        "version": row.version,
        "revision": row.revision,
        "published_at": row.published_at.replace(tzinfo=timezone.utc).isoformat() if row.published_at else None,
        "steps": [step.model_dump(mode="json") for step in (_step_input(value) for value in _template_steps(unit, row.id))],
    }


def _published_for(
    unit: Work,
    version_id: str,
    *,
    property_id: str,
    unit_id: str,
    direction: str,
    lock: bool,
):
    row = _load_version(unit, version_id, lock=lock)
    if (
        row.state != "published"
        or row.property_id != property_id
        or row.direction != direction
        or row.unit_id not in {None, unit_id}
    ):
        raise conflict("Die ausgewählte Vorlagenfassung ist für diese Immobilie/Einheit/Richtung nicht veröffentlicht.")
    steps = [_step_input(value) for value in _template_steps(unit, row.id)]
    _validate_steps(row.portfolio_id, steps)
    return row, steps


def _anchor_value(
    anchor: str,
    previous: Any | None,
    following: Any | None,
    move_out_handover: date | None,
    move_in_handover: date | None,
) -> date:
    if anchor == "previous_contract_end":
        value = previous.end_date if previous is not None else None
    elif anchor == "next_contract_start":
        value = following.start_date if following is not None else None
    elif anchor == "move_out_handover":
        value = move_out_handover
    elif anchor == "move_in_handover":
        value = move_in_handover
    else:
        value = None
    if not isinstance(value, date):
        raise ValidationError(f"Der bewusst gewählte Terminanker '{anchor}' fehlt.")
    return value


def _due(anchor: date, offset: int) -> date:
    try:
        return anchor + timedelta(days=offset)
    except OverflowError:
        raise ValidationError("Der relative Workflowtermin liegt außerhalb der gültigen Kalenderdarstellung.") from None


def _active_conflicts(unit: Work, previous_id: str | None, next_id: str | None) -> list[str]:
    conflicts: list[str] = []
    if unit.db is not None:
        query = select(TenancyChangeORM.id, TenancyChangeORM.previous_contract_id, TenancyChangeORM.next_contract_id).where(
            TenancyChangeORM.state == "active"
        )
        if previous_id or next_id:
            clauses = []
            if previous_id:
                clauses.append(TenancyChangeORM.previous_contract_id == previous_id)
            if next_id:
                clauses.append(TenancyChangeORM.next_contract_id == next_id)
            query = query.where(or_(*clauses))
        else:
            return conflicts
        for identifier, old_id, new_id in unit.db.execute(query):
            if old_id == previous_id and previous_id:
                conflicts.append("previous_contract_active_change")
            if new_id == next_id and next_id:
                conflicts.append("next_contract_active_change")
    else:
        for row in unit.store.__dict__[TenancyChangeORM.__tablename__].values():
            if row.state != "active":
                continue
            if previous_id and row.previous_contract_id == previous_id:
                conflicts.append("previous_contract_active_change")
            if next_id and row.next_contract_id == next_id:
                conflicts.append("next_contract_active_change")
    return sorted(set(conflicts))


def _selection(
    unit: Work,
    payload: ChangeSelection,
    *,
    lock: bool,
) -> tuple[Any, Any | None, Any | None, dict[str, Any], list[dict[str, Any]], dict[str, str], list[str]]:
    prop, location = _property_unit(unit, payload.property_id, payload.unit_id, lock=lock)
    assert location is not None
    previous = _lock_contract(unit, payload.previous_contract_id) if payload.previous_contract_id and lock else (
        unit.store.get_contract(payload.previous_contract_id) if payload.previous_contract_id else None
    )
    following = _lock_contract(unit, payload.next_contract_id) if payload.next_contract_id and lock else (
        unit.store.get_contract(payload.next_contract_id) if payload.next_contract_id else None
    )
    for contract in (previous, following):
        if contract is not None and (contract.property_id, contract.unit_id) != (prop.id, location.id):
            raise ValidationError("Alle ausgewählten Mietverhältnisse müssen zu derselben Immobilie und Einheit gehören.")

    versions: list[tuple[str, Any, list[TemplateStepInput]]] = []
    if payload.mode in {"move_out", "turnover"}:
        move_out_version_id = payload.move_out_template_version_id
        if move_out_version_id is None:
            raise ValidationError("Auszug benötigt eine veröffentlichte Auszugsvorlage.")
        row, steps = _published_for(
            unit,
            move_out_version_id,
            property_id=prop.id,
            unit_id=location.id,
            direction="move_out",
            lock=lock,
        )
        versions.append(("move_out", row, steps))
    if payload.mode in {"move_in", "turnover"}:
        move_in_version_id = payload.move_in_template_version_id
        if move_in_version_id is None:
            raise ValidationError("Einzug benötigt eine veröffentlichte Einzugsvorlage.")
        row, steps = _published_for(
            unit,
            move_in_version_id,
            property_id=prop.id,
            unit_id=location.id,
            direction="move_in",
            lock=lock,
        )
        versions.append(("move_in", row, steps))

    planned: list[dict[str, Any]] = []
    for direction, version, steps in versions:
        for step in sorted(steps, key=lambda item: (item.position, item.stable_key)):
            anchor = _anchor_value(
                step.anchor,
                previous,
                following,
                payload.move_out_handover_date,
                payload.move_in_handover_date,
            )
            planned.append(
                {
                    "direction": direction,
                    "template_version_id": version.id,
                    "template_step_key": step.stable_key,
                    "position": step.position,
                    "title_snapshot": step.title,
                    "description_snapshot": step.description,
                    "requirement": step.default_requirement,
                    "anchor": step.anchor,
                    "anchor_date": anchor.isoformat(),
                    "offset_days": step.offset_days,
                    "due_date": _due(anchor, step.offset_days).isoformat(),
                    "assignee_user_id": step.assignee_user_id,
                    "assignee_role": step.assignee_role,
                    "depends_on_step_keys": list(step.depends_on_step_keys),
                    "evidence_requirement": step.evidence_requirement,
                }
            )

    source_etags: dict[str, str] = {}
    if previous is not None:
        source_etags["previous_contract"] = _contract_etag(previous)
    if following is not None:
        source_etags["next_contract"] = _contract_etag(following)
    snapshot = {
        "schema": "tenancy-change-snapshot-v1",
        "portfolio_id": prop.portfolio_id,
        "property_id": prop.id,
        "unit_id": location.id,
        "mode": payload.mode,
        "move_out_handover_date": payload.move_out_handover_date.isoformat()
        if payload.move_out_handover_date
        else None,
        "move_in_handover_date": payload.move_in_handover_date.isoformat()
        if payload.move_in_handover_date
        else None,
        "previous_contract": _contract_snapshot(previous) if previous is not None else None,
        "next_contract": _contract_snapshot(following) if following is not None else None,
        "templates": [_template_snapshot(unit, row) for _, row, _ in versions],
    }
    conflicts = _active_conflicts(
        unit,
        previous.id if previous is not None else None,
        following.id if following is not None else None,
    )
    return prop, previous, following, snapshot, planned, source_etags, conflicts


def preview_change(store: Any, payload: PreviewTenancyChange, actor_id: str) -> dict[str, Any]:
    with work(store, actor_id) as unit:
        _require_manager(unit.user)
        prop, _, _, snapshot, planned, source_etags, conflicts = _selection(unit, payload, lock=False)
        proposal = {
            "selection": payload.model_dump(mode="json"),
            "snapshot_sha256": digest(snapshot),
            "source_etags": source_etags,
            "steps": planned,
        }
        anchors = {
            "previous_contract_end": snapshot["previous_contract"]["end_date"] if snapshot["previous_contract"] else None,
            "next_contract_start": snapshot["next_contract"]["start_date"] if snapshot["next_contract"] else None,
            "move_out_handover": snapshot["move_out_handover_date"],
            "move_in_handover": snapshot["move_in_handover_date"],
        }
        return {
            "preview_hash": digest(proposal),
            "snapshot_sha256": proposal["snapshot_sha256"],
            "source_etags": source_etags,
            "anchors": anchors,
            "affected_steps": planned,
            "conflicts": conflicts,
            "portfolio_id": prop.portfolio_id,
        }


def _selection_only(payload: StartTenancyChange) -> PreviewTenancyChange:
    fields = set(PreviewTenancyChange.model_fields)
    return PreviewTenancyChange(**payload.model_dump(include=fields))


def start_change(store: Any, payload: StartTenancyChange, actor_id: str) -> dict[str, Any]:
    with work(store, actor_id, write=True) as unit:
        _require_manager(unit.user)
        selection = _selection_only(payload)
        # Fresh authorization/scope is checked before receipt replay, but a later
        # template retirement or source edit must not turn an already committed
        # identical command into a second operation or a false conflict.
        prop, _ = _property_unit(unit, selection.property_id, selection.unit_id, lock=True)
        request_hash = _request_hash("start_tenancy_change", payload)
        replay = _command(unit, actor_id, payload.idempotency_key, "start_tenancy_change", request_hash)
        if replay is not None:
            return replay
        prop, previous, following, snapshot, planned, source_etags, conflicts = _selection(unit, selection, lock=True)
        proposal = {
            "selection": selection.model_dump(mode="json"),
            "snapshot_sha256": digest(snapshot),
            "source_etags": source_etags,
            "steps": planned,
        }
        if payload.preview_hash != digest(proposal):
            raise conflict("Die Startvorschau ist nicht mehr aktuell. Erneut prüfen.")
        if payload.source_etags != source_etags:
            raise conflict("Ein ausgewählter Vertrag wurde seit der Vorschau geändert.")
        if conflicts:
            raise conflict("Für dieselbe Vertragsrolle besteht bereits eine aktive Wechselakte.")
        stamp = now()
        change = TenancyChangeORM(
            id=str(uuid4()),
            portfolio_id=prop.portfolio_id,
            property_id=selection.property_id,
            unit_id=selection.unit_id,
            previous_contract_id=previous.id if previous else None,
            next_contract_id=following.id if following else None,
            mode=selection.mode,
            move_out_handover_date=selection.move_out_handover_date,
            move_in_handover_date=selection.move_in_handover_date,
            move_out_template_version_id=selection.move_out_template_version_id,
            move_in_template_version_id=selection.move_in_template_version_id,
            state="active",
            revision=str(uuid4()),
            created_by=actor_id,
            snapshot=snapshot,
            snapshot_sha256=digest(snapshot),
            created_at=stamp,
            updated_at=stamp,
        )
        unit.add(change)
        step_ids = {
            (item["direction"], item["template_step_key"]): str(uuid4())
            for item in planned
        }
        for item in planned:
            dependencies = [
                step_ids[item["direction"], key] for key in item["depends_on_step_keys"]
            ]
            row = WorkflowStepInstanceORM(
                id=step_ids[item["direction"], item["template_step_key"]],
                tenancy_change_id=change.id,
                portfolio_id=change.portfolio_id,
                template_step_key=item["template_step_key"],
                direction=item["direction"],
                title_snapshot=item["title_snapshot"],
                description_snapshot=item["description_snapshot"],
                requirement=item["requirement"],
                not_applicable_reason=None,
                anchor=item["anchor"],
                offset_days=item["offset_days"],
                original_due_date=date.fromisoformat(item["due_date"]),
                due_date=date.fromisoformat(item["due_date"]),
                state="blocked" if dependencies else "open",
                depends_on_step_ids=dependencies,
                assignee_user_id=item["assignee_user_id"],
                assignee_role=item["assignee_role"],
                task_id=None,
                completed_at=None,
                completed_by=None,
                evidence_requirement=item["evidence_requirement"],
                revision=str(uuid4()),
                created_at=stamp,
                updated_at=stamp,
            )
            unit.add(row)
        response = _change_public(unit, change, require_view=False)
        return _save_command(
            unit,
            actor_id,
            payload.idempotency_key,
            "start_tenancy_change",
            "tenancy_change",
            change.id,
            change.portfolio_id,
            request_hash,
            response,
        )


def _change_steps(unit: Work, change_id: str, *, lock: bool = False) -> list[Any]:
    if unit.db is not None:
        query = select(WorkflowStepInstanceORM).where(
            WorkflowStepInstanceORM.tenancy_change_id == change_id
        )
        if lock:
            query = query.with_for_update()
        return list(
            unit.db.scalars(
                query.order_by(
                    WorkflowStepInstanceORM.direction,
                    WorkflowStepInstanceORM.due_date,
                    WorkflowStepInstanceORM.id,
                )
            )
        )
    return sorted(
        (
            row
            for row in unit.store.__dict__[WorkflowStepInstanceORM.__tablename__].values()
            if row.tenancy_change_id == change_id
        ),
        key=lambda row: (row.direction, row.due_date, row.id),
    )


def _step_evidence(unit: Work, step_id: str) -> list[Any]:
    if unit.db is not None:
        return list(
            unit.db.scalars(
                select(WorkflowEvidenceLinkORM)
                .where(WorkflowEvidenceLinkORM.step_id == step_id)
                .order_by(WorkflowEvidenceLinkORM.created_at, WorkflowEvidenceLinkORM.id)
            )
        )
    return sorted(
        (
            row
            for row in unit.store.__dict__[WorkflowEvidenceLinkORM.__tablename__].values()
            if row.step_id == step_id
        ),
        key=lambda row: (row.created_at, row.id),
    )


def _evidence_public(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "document_id": row.document_id,
        "document_version_id": row.document_version_id,
        "handover_protocol_id": row.handover_protocol_id,
        "meter_reading_id": row.meter_reading_id,
        "snapshot_sha256": row.snapshot_sha256,
        "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
    }


def _responsible(unit: Work, step: Any) -> bool:
    if _can_manage(unit.user):
        return True
    if not may_write_resource(unit.user["role"], "tasks"):
        return False
    if step.assignee_user_id is not None:
        return step.assignee_user_id == unit.user["id"]
    if step.assignee_role is not None:
        return step.assignee_role == unit.user["role"]
    return False


def _step_map(steps: list[Any]) -> dict[str, Any]:
    return {row.id: row for row in steps}


def _unresolved(step: Any, rows: dict[str, Any]) -> list[str]:
    result = []
    for identifier in step.depends_on_step_ids:
        predecessor = rows.get(identifier)
        if predecessor is None or predecessor.state not in {"completed", "not_applicable"}:
            result.append(identifier)
    return result


def _step_actions(unit: Work, change: Any, step: Any, blocked: list[str]) -> dict[str, bool]:
    allowed = change.state == "active" and _responsible(unit, step)
    mutable = allowed and step.state not in {"completed", "not_applicable"}
    return {
        "edit_template": False,
        "publish_template": False,
        "edit_change": False,
        "reanchor": False,
        "complete_step": bool(mutable and not blocked),
        "link_task": bool(mutable and not blocked and step.task_id is None),
        "link_document": bool(mutable),
        "complete_change": False,
    }


def _step_public(unit: Work, change: Any, step: Any, rows: dict[str, Any]) -> dict[str, Any]:
    blocked = _unresolved(step, rows)
    visible_state = (
        "blocked"
        if blocked and step.state not in {"completed", "not_applicable"}
        else ("open" if step.state == "blocked" and not blocked else step.state)
    )
    evidence = _step_evidence(unit, step.id)
    return {
        "id": step.id,
        "tenancy_change_id": step.tenancy_change_id,
        "template_step_key": step.template_step_key,
        "direction": step.direction,
        "title_snapshot": step.title_snapshot,
        "description_snapshot": step.description_snapshot,
        "requirement": step.requirement,
        "not_applicable_reason": step.not_applicable_reason,
        "anchor": step.anchor,
        "offset_days": step.offset_days,
        "original_due_date": step.original_due_date.isoformat(),
        "due_date": step.due_date.isoformat(),
        "state": visible_state,
        "blocked_by_step_ids": blocked,
        "assignee_user_id": step.assignee_user_id,
        "assignee_role": step.assignee_role,
        "task_id": step.task_id,
        "completed_at": step.completed_at.replace(tzinfo=timezone.utc).isoformat() if step.completed_at else None,
        "completed_by": step.completed_by,
        "evidence_links": [_evidence_public(value) for value in evidence],
        "revision": step.revision,
        "etag": workflow_etag("step", step.id, step.revision),
        "actions": _step_actions(unit, change, step, blocked),
    }


def _change_actions(unit: Work, row: Any, steps: list[Any]) -> dict[str, bool]:
    manager = _can_manage(unit.user)
    active = row.state == "active"
    return {
        "edit_template": False,
        "publish_template": False,
        "edit_change": bool(manager and active),
        "reanchor": bool(manager and active),
        "complete_step": False,
        "link_task": False,
        "link_document": False,
        "complete_change": bool(manager and active),
    }


def _can_view_change(unit: Work, row: Any, steps: list[Any]) -> bool:
    if _can_manage(unit.user):
        return True
    return any(_responsible(unit, step) for step in steps)


def _load_change(unit: Work, identifier: str, *, lock: bool = False, require_view: bool = True):
    row = _row(unit, TenancyChangeORM, identifier)
    if row is None:
        raise HTTPException(404, "Mieterwechselakte nicht gefunden.")
    binding = (
        row.portfolio_id,
        row.property_id,
        row.unit_id,
        row.previous_contract_id,
        row.next_contract_id,
    )
    if lock:
        # Common order: property -> unit -> contracts -> change -> steps.
        _property_unit(unit, row.property_id, row.unit_id, lock=True)
        for contract_id in sorted(
            identifier for identifier in {row.previous_contract_id, row.next_contract_id} if identifier
        ):
            _lock_contract(unit, contract_id)
        row = _row(unit, TenancyChangeORM, identifier, lock=True)
        if row is None or binding != (
            row.portfolio_id,
            row.property_id,
            row.unit_id,
            row.previous_contract_id,
            row.next_contract_id,
        ):
            raise conflict("Die Zuordnung der Wechselakte wurde parallel geändert.")
    else:
        _property_unit(unit, row.property_id, row.unit_id)
    steps = _change_steps(unit, row.id, lock=lock)
    if require_view and not _can_view_change(unit, row, steps):
        raise HTTPException(404, "Mieterwechselakte nicht gefunden.")
    return row, steps


def _change_public(unit: Work, row: Any, *, require_view: bool = True) -> dict[str, Any]:
    row, steps = _load_change(unit, row.id, require_view=require_view)
    mapping = _step_map(steps)
    return {
        "id": row.id,
        "portfolio_id": row.portfolio_id,
        "property_id": row.property_id,
        "unit_id": row.unit_id,
        "previous_contract_id": row.previous_contract_id,
        "next_contract_id": row.next_contract_id,
        "mode": row.mode,
        "move_out_handover_date": row.move_out_handover_date.isoformat() if row.move_out_handover_date else None,
        "move_in_handover_date": row.move_in_handover_date.isoformat() if row.move_in_handover_date else None,
        "move_out_template_version_id": row.move_out_template_version_id,
        "move_in_template_version_id": row.move_in_template_version_id,
        "state": row.state,
        "revision": row.revision,
        "etag": workflow_etag("tenancy-change", row.id, row.revision),
        "created_by": row.created_by,
        "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "updated_at": row.updated_at.replace(tzinfo=timezone.utc).isoformat(),
        "snapshot_sha256": row.snapshot_sha256,
        "steps": [_step_public(unit, row, step, mapping) for step in steps],
        "actions": _change_actions(unit, row, steps),
    }


def get_change(store: Any, change_id: str, actor_id: str) -> dict[str, Any]:
    with work(store, actor_id) as unit:
        row, _ = _load_change(unit, change_id)
        return _change_public(unit, row)


def _touch_change(unit: Work, change: Any) -> None:
    if unit.db is None:
        unit.touch(TenancyChangeORM.__tablename__, change.id)
    change.revision = str(uuid4())
    change.updated_at = now()


def _touch_step(unit: Work, step: Any) -> None:
    if unit.db is None:
        unit.touch(WorkflowStepInstanceORM.__tablename__, step.id)
    step.revision = str(uuid4())
    step.updated_at = now()


def _refresh_blocked(unit: Work, change: Any, steps: list[Any]) -> None:
    rows = _step_map(steps)
    for step in steps:
        if step.state in {"completed", "not_applicable"}:
            continue
        blocked = bool(_unresolved(step, rows))
        target = "blocked" if blocked else ("open" if step.state == "blocked" else step.state)
        if target != step.state:
            _touch_step(unit, step)
            step.state = target
    if unit.db is not None:
        unit.db.flush()


def list_changes(
    store: Any,
    actor_id: str,
    *,
    property_id: str | None = None,
    unit_id: str | None = None,
    state: str | None = None,
    after: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    _check_page_limit(limit)
    with work(store, actor_id) as unit:
        filters = {"property_id": property_id, "unit_id": unit_id, "state": state}
        binding = _page_binding(unit, "tenancy_changes", filters, limit)
        point = decode_cursor(after, binding)
        point_time: datetime | None
        point_id: str | None
        if point is not None:
            try:
                if len(point) != 2 or not all(isinstance(value, str) for value in point):
                    raise ValueError
                point_time = datetime.fromisoformat(point[0])
                if point_time.tzinfo is not None or not point[1]:
                    raise ValueError
                point_id = point[1]
            except (TypeError, ValueError):
                raise HTTPException(422, "Ungültige Wechselaktenseite.") from None
        else:
            point_time = point_id = None
        if unit.db is not None:
            query = select(TenancyChangeORM)
            if property_id is not None:
                query = query.where(TenancyChangeORM.property_id == property_id)
            if unit_id is not None:
                query = query.where(TenancyChangeORM.unit_id == unit_id)
            if state is not None:
                query = query.where(TenancyChangeORM.state == state)
            if not _can_manage(unit.user):
                responsibility = select(WorkflowStepInstanceORM.id).where(
                    WorkflowStepInstanceORM.tenancy_change_id == TenancyChangeORM.id,
                    or_(
                        WorkflowStepInstanceORM.assignee_user_id == actor_id,
                        WorkflowStepInstanceORM.assignee_role == unit.user["role"],
                    ),
                )
                query = query.where(responsibility.exists())
            if point_time is not None:
                query = query.where(
                    or_(
                        TenancyChangeORM.updated_at < point_time,
                        and_(TenancyChangeORM.updated_at == point_time, TenancyChangeORM.id < point_id),
                    )
                )
            selected = list(
                unit.db.scalars(
                    query.order_by(TenancyChangeORM.updated_at.desc(), TenancyChangeORM.id.desc()).limit(limit + 1)
                )
            )
        else:
            steps = list(unit.store.__dict__[WorkflowStepInstanceORM.__tablename__].values())
            values = (
                row
                for row in unit.store.__dict__[TenancyChangeORM.__tablename__].values()
                if memory_visible(unit.store, TenancyChangeORM.__tablename__, row, scope=unit.scope)
                and (property_id is None or row.property_id == property_id)
                and (unit_id is None or row.unit_id == unit_id)
                and (state is None or row.state == state)
                and (
                    _can_manage(unit.user)
                    or any(
                        step.tenancy_change_id == row.id
                        and (
                            step.assignee_user_id == actor_id
                            or step.assignee_role == unit.user["role"]
                        )
                        for step in steps
                    )
                )
                and (point_time is None or (row.updated_at, row.id) < (point_time, point_id))
            )
            selected = nlargest(limit + 1, values, key=lambda row: (row.updated_at, row.id))
        has_more = len(selected) > limit
        items = selected[:limit]
        return {
            "items": [_change_public(unit, row) for row in items],
            "next_cursor": encode_cursor(binding, [items[-1].updated_at.isoformat(), items[-1].id])
            if has_more and items
            else None,
            "has_more": has_more,
        }


def _task_values(task: Any, **changes: Any) -> TaskCreate:
    values = task.model_dump(include=set(TaskCreate.model_fields))
    values.update(changes)
    return TaskCreate(**values)


def _write_task(unit: Work, step: Any, **changes: Any):
    if step.task_id is None:
        return None
    token = _TASK_WRITE_STEP.set(step.id)
    try:
        current = unit.store.get_task(step.task_id)
        payload = _task_values(current, **changes)
        if unit.db is not None:
            return unit.store.communication._tasks.update(current.id, payload)
        unit.touch("tasks", current.id)
        return unit.store.update_task(current.id, payload)
    finally:
        _TASK_WRITE_STEP.reset(token)


def patch_change(
    store: Any, change_id: str, payload: PatchTenancyChange, actor_id: str
) -> dict[str, Any]:
    with work(store, actor_id, write=True) as unit:
        _require_manager(unit.user)
        change, steps = _load_change(unit, change_id, lock=True)
        request_hash = _request_hash("patch_tenancy_change", payload)
        replay = _command(unit, actor_id, payload.idempotency_key, "patch_tenancy_change", request_hash)
        if replay is not None:
            return replay
        _revision(change, payload.expected_revision)
        if change.state != "active" or payload.state != "cancelled":
            raise conflict("Nur eine aktive Wechselakte kann ausdrücklich abgebrochen werden.")
        _touch_change(unit, change)
        change.state = "cancelled"
        for step in steps:
            if step.task_id and step.state not in {"completed", "not_applicable"}:
                _write_task(unit, step, status="cancelled")
        if unit.db is not None:
            unit.db.flush()
        response = _change_public(unit, change)
        return _save_command(
            unit,
            actor_id,
            payload.idempotency_key,
            "patch_tenancy_change",
            "tenancy_change",
            change.id,
            change.portfolio_id,
            request_hash,
            response,
        )


def _current_change_etags(unit: Work, change: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    if change.previous_contract_id:
        result["previous_contract"] = _contract_etag(unit.store.get_contract(change.previous_contract_id))
    if change.next_contract_id:
        result["next_contract"] = _contract_etag(unit.store.get_contract(change.next_contract_id))
    return result


def _snapshot_anchor(change: Any, anchor: str, move_out: date | None, move_in: date | None) -> date:
    snapshot = change.snapshot
    if anchor == "previous_contract_end":
        value = (snapshot.get("previous_contract") or {}).get("end_date")
        result = date.fromisoformat(value) if value else None
    elif anchor == "next_contract_start":
        value = (snapshot.get("next_contract") or {}).get("start_date")
        result = date.fromisoformat(value) if value else None
    elif anchor == "move_out_handover":
        result = move_out
    elif anchor == "move_in_handover":
        result = move_in
    else:
        result = None
    if result is None:
        raise ValidationError(f"Der bewusst gewählte Terminanker '{anchor}' fehlt.")
    return result


def reanchor_preview(
    store: Any, change_id: str, payload: ReanchorPreview, actor_id: str
) -> dict[str, Any]:
    with work(store, actor_id) as unit:
        _require_manager(unit.user)
        change, steps = _load_change(unit, change_id)
        _revision(change, payload.expected_revision)
        if change.state != "active":
            raise conflict("Nur eine aktive Wechselakte kann neu terminiert werden.")
        affected = []
        for step in steps:
            if step.state in {"completed", "not_applicable"}:
                continue
            anchor = _snapshot_anchor(
                change,
                step.anchor,
                payload.move_out_handover_date,
                payload.move_in_handover_date,
            )
            target = _due(anchor, step.offset_days)
            if target != step.due_date:
                affected.append(
                    {
                        "step_id": step.id,
                        "original_due_date": step.original_due_date.isoformat(),
                        "current_due_date": step.due_date.isoformat(),
                        "new_due_date": target.isoformat(),
                        "task_id": step.task_id,
                    }
                )
        source_etags = _current_change_etags(unit, change)
        proposal = {
            "change_id": change.id,
            "revision": change.revision,
            "move_out_handover_date": payload.move_out_handover_date.isoformat()
            if payload.move_out_handover_date
            else None,
            "move_in_handover_date": payload.move_in_handover_date.isoformat()
            if payload.move_in_handover_date
            else None,
            "source_etags": source_etags,
            "affected_steps": affected,
        }
        return {
            "preview_hash": digest(proposal),
            "change_revision": change.revision,
            "source_etags": source_etags,
            "affected_steps": affected,
            "completed_steps_unchanged": [
                step.id for step in steps if step.state in {"completed", "not_applicable"}
            ],
        }


def reanchor_change(
    store: Any, change_id: str, payload: ReanchorTenancyChange, actor_id: str
) -> dict[str, Any]:
    with work(store, actor_id, write=True) as unit:
        _require_manager(unit.user)
        change, steps = _load_change(unit, change_id, lock=True)
        request_hash = _request_hash("reanchor_tenancy_change", payload)
        replay = _command(unit, actor_id, payload.idempotency_key, "reanchor_tenancy_change", request_hash)
        if replay is not None:
            return replay
        _revision(change, payload.expected_revision)
        if change.state != "active":
            raise conflict("Nur eine aktive Wechselakte kann neu terminiert werden.")
        affected = []
        targets: dict[str, date] = {}
        for step in steps:
            if step.state in {"completed", "not_applicable"}:
                continue
            anchor = _snapshot_anchor(
                change,
                step.anchor,
                payload.move_out_handover_date,
                payload.move_in_handover_date,
            )
            target = _due(anchor, step.offset_days)
            if target != step.due_date:
                targets[step.id] = target
                affected.append(
                    {
                        "step_id": step.id,
                        "original_due_date": step.original_due_date.isoformat(),
                        "current_due_date": step.due_date.isoformat(),
                        "new_due_date": target.isoformat(),
                        "task_id": step.task_id,
                    }
                )
        source_etags = _current_change_etags(unit, change)
        if source_etags != payload.source_etags:
            raise conflict("Ein ausgewählter Vertrag wurde seit der Terminvorschau geändert.")
        proposal = {
            "change_id": change.id,
            "revision": change.revision,
            "move_out_handover_date": payload.move_out_handover_date.isoformat()
            if payload.move_out_handover_date
            else None,
            "move_in_handover_date": payload.move_in_handover_date.isoformat()
            if payload.move_in_handover_date
            else None,
            "source_etags": source_etags,
            "affected_steps": affected,
        }
        if digest(proposal) != payload.preview_hash:
            raise conflict("Die Terminverschiebung stimmt nicht mehr mit der Vorschau überein.")
        _touch_change(unit, change)
        change.move_out_handover_date = payload.move_out_handover_date
        change.move_in_handover_date = payload.move_in_handover_date
        for step in steps:
            new_due = targets.get(step.id)
            if new_due is None:
                continue
            _touch_step(unit, step)
            step.due_date = new_due
            if step.task_id:
                _write_task(unit, step, due_date=new_due)
        if unit.db is not None:
            unit.db.flush()
        response = _change_public(unit, change)
        return _save_command(
            unit,
            actor_id,
            payload.idempotency_key,
            "reanchor_tenancy_change",
            "tenancy_change",
            change.id,
            change.portfolio_id,
            request_hash,
            response,
        )


def _load_step(unit: Work, change: Any, step_id: str, *, lock: bool = False):
    step = _row(unit, WorkflowStepInstanceORM, step_id, lock=lock)
    if step is None or step.tenancy_change_id != change.id or step.portfolio_id != change.portfolio_id:
        raise HTTPException(404, "Workflowschritt nicht gefunden.")
    return step


def _required_evidence_present(unit: Work, step: Any) -> bool:
    if step.evidence_requirement == "none":
        return True
    kind = {
        "document_original": "document_version",
        "handover_protocol": "handover_protocol",
        "meter_reading": "meter_reading",
    }[step.evidence_requirement]
    return any(link.kind == kind for link in _step_evidence(unit, step.id))


def update_step(
    store: Any, change_id: str, step_id: str, payload: UpdateStep, actor_id: str
) -> dict[str, Any]:
    with work(store, actor_id, write=True) as unit:
        change, steps = _load_change(unit, change_id, lock=True)
        step = _load_step(unit, change, step_id, lock=True)
        if not _responsible(unit, step):
            raise HTTPException(403, "Dieser Schritt ist Ihnen nicht zur Ausführung zugewiesen.")
        request_hash = _request_hash("update_workflow_step", payload)
        replay = _command(unit, actor_id, payload.idempotency_key, "update_workflow_step", request_hash)
        if replay is not None:
            return replay
        _revision(change, payload.expected_change_revision)
        _revision(step, payload.expected_revision)
        if change.state != "active":
            raise conflict("Die Wechselakte ist nicht mehr aktiv.")
        if step.state in {"completed", "not_applicable"}:
            raise conflict("Erledigte oder bewusst ausgenommene Schritte bleiben unverändert.")
        mapping = _step_map(steps)
        blocked = _unresolved(step, mapping)
        if blocked and payload.state in {"in_progress", "completed"}:
            raise conflict("Abhängige Vorgängerschritte sind noch nicht abgeschlossen.")
        if payload.state == "completed" and not _required_evidence_present(unit, step):
            raise conflict("Der für diesen Schritt verlangte Originalbeleg fehlt.")
        _touch_step(unit, step)
        stamp = now()
        step.state = payload.state
        step.not_applicable_reason = (
            (payload.not_applicable_reason or "").strip() if payload.state == "not_applicable" else None
        )
        if payload.state == "completed":
            step.completed_at, step.completed_by = stamp, actor_id
        elif payload.state == "not_applicable":
            step.completed_at, step.completed_by = stamp, actor_id
        else:
            step.completed_at = step.completed_by = None
        if step.task_id:
            status = {
                "open": "open",
                "in_progress": "in_progress",
                "completed": "completed",
                "not_applicable": "cancelled",
            }[payload.state]
            _write_task(unit, step, status=status)
        _touch_change(unit, change)
        _refresh_blocked(unit, change, steps)
        if unit.db is not None:
            unit.db.flush()
        response = _step_public(unit, change, step, _step_map(steps))
        return _save_command(
            unit,
            actor_id,
            payload.idempotency_key,
            "update_workflow_step",
            "workflow_step",
            step.id,
            change.portfolio_id,
            request_hash,
            response,
        )


def _assignee_display(step: Any) -> str | None:
    if step.assignee_user_id:
        user = auth.get_user_by_id(step.assignee_user_id)
        if not user or not user["is_active"]:
            raise conflict("Der verantwortliche Benutzer ist nicht mehr aktiv. Zuweisung prüfen.")
        return user["full_name"]
    if step.assignee_role:
        return step.assignee_role
    return None


def create_step_task(
    store: Any, change_id: str, step_id: str, payload: CreateStepTask, actor_id: str
) -> dict[str, Any]:
    with work(store, actor_id, write=True) as unit:
        change, steps = _load_change(unit, change_id, lock=True)
        step = _load_step(unit, change, step_id, lock=True)
        if not _responsible(unit, step):
            raise HTTPException(403, "Dieser Schritt ist Ihnen nicht zur Ausführung zugewiesen.")
        request_hash = _request_hash("create_workflow_task", payload)
        replay = _command(unit, actor_id, payload.idempotency_key, "create_workflow_task", request_hash)
        if replay is not None:
            return replay
        _revision(change, payload.expected_change_revision)
        _revision(step, payload.expected_revision)
        if change.state != "active" or step.state in {"completed", "not_applicable"}:
            raise conflict("Für diesen Schritt kann keine neue Aufgabe mehr angelegt werden.")
        if _unresolved(step, _step_map(steps)):
            raise conflict("Die Aufgabe wird erst nach Abschluss ihrer Vorgänger erzeugt.")
        if step.task_id is not None:
            raise conflict("Dieser Workflowschritt besitzt bereits eine Aufgabeninstanz.")
        task_data = TaskCreate(
            title=step.title_snapshot,
            description=step.description_snapshot,
            assignee=_assignee_display(step),
            due_date=step.due_date,
            priority="medium",
            status="in_progress" if step.state == "in_progress" else "open",
            property_id=change.property_id,
            unit_id=change.unit_id,
            recurrence_rule=None,
            parent_task_id=None,
        )
        if unit.db is not None:
            task = unit.store.communication._tasks.create(task_data)
        else:
            task = unit.store.create_task(task_data)
            unit.touch("tasks", task.id, inserted=True)
        _touch_step(unit, step)
        step.task_id = task.id
        _touch_change(unit, change)
        if unit.db is not None:
            unit.db.flush()
        response = _step_public(unit, change, step, _step_map(steps))
        return _save_command(
            unit,
            actor_id,
            payload.idempotency_key,
            "create_workflow_task",
            "workflow_step",
            step.id,
            change.portfolio_id,
            request_hash,
            response,
        )


def _direction_contract(change: Any, direction: str) -> tuple[str, str]:
    contract_id = change.previous_contract_id if direction == "move_out" else change.next_contract_id
    snapshot = (
        change.snapshot.get("previous_contract")
        if direction == "move_out"
        else change.snapshot.get("next_contract")
    )
    if not contract_id or not snapshot or snapshot.get("id") != contract_id or not snapshot.get("tenant_id"):
        raise HTTPException(503, "Der eingefrorene Vertragsbezug der Wechselakte ist unvollständig.")
    return contract_id, snapshot["tenant_id"]


def _lock_document_tenant_first(unit: Work, change_id: str, step_id: str, evidence: Any) -> None:
    """Respect document/privacy lock order before location/contract locks."""
    if unit.db is None or evidence.kind != "document_version":
        return
    change = _row(unit, TenancyChangeORM, change_id)
    step = _row(unit, WorkflowStepInstanceORM, step_id)
    if change is None or step is None or step.tenancy_change_id != change.id:
        raise HTTPException(404, "Workflowschritt nicht gefunden.")
    _, tenant_id = _direction_contract(change, step.direction)
    if unit.db.scalar(
        select(TenantORM.id).where(TenantORM.id == tenant_id).with_for_update(read=True)
    ) is None:
        raise HTTPException(404, "Vertragspartei nicht zugänglich.")


def _evidence_snapshot(unit: Work, change: Any, step: Any, evidence: Any) -> tuple[dict[str, Any], str]:
    from . import document_versions

    expected_contract, expected_tenant = _direction_contract(change, step.direction)
    current_contract = unit.store.get_contract(expected_contract)
    if (
        current_contract.tenant_id != expected_tenant
        or current_contract.property_id != change.property_id
        or current_contract.unit_id != change.unit_id
    ):
        raise conflict("Die aktuelle Vertragszuordnung stimmt nicht mehr mit dem eingefrorenen Wechselstand überein.")
    if evidence.kind == "document_version":
        if (
            not evidence.document_id
            or not evidence.document_version_id
            or evidence.handover_protocol_id
            or evidence.meter_reading_id
        ):
            raise ValidationError("Dokumentbeleg benötigt genau Dokument- und Versions-ID.")
        document, binding = document_versions._document(
            unit.store, unit.db, evidence.document_id, lock=unit.db is not None
        )
        version = document_versions._authorized_version(
            unit.store, unit.db, evidence.document_id, evidence.document_version_id, binding
        )
        if (
            binding["portfolio_id"] != change.portfolio_id
            or binding["property_id"] != change.property_id
            or binding["unit_id"] != change.unit_id
            or binding["contract_id"] != expected_contract
            or binding["tenant_id"] != expected_tenant
        ):
            raise ValidationError("Das Dokumentoriginal gehört nicht zum Mietverhältnis dieses Workflowschritts.")
        for _ in document_versions.verified_blocks(unit.store, version):
            pass
        values = {
            "kind": "document_version",
            "document_id": document.id,
            "document_version_id": version.id,
            "sha256": version.sha256,
            "number": version.number,
            "contract_id": expected_contract,
            "tenant_id": expected_tenant,
        }
        return values, digest(values)

    if evidence.kind == "handover_protocol":
        if (
            not evidence.handover_protocol_id
            or evidence.document_id
            or evidence.document_version_id
            or evidence.meter_reading_id
        ):
            raise ValidationError("Übergabebeleg benötigt genau eine Protokoll-ID.")
        if unit.db is not None:
            unit.db.scalar(
                select(HandoverProtocolORM.id)
                .where(HandoverProtocolORM.id == evidence.handover_protocol_id)
                .with_for_update()
            )
        protocol = unit.store.get_handover_protocol(evidence.handover_protocol_id)
        if (
            protocol.status != "finalized"
            or protocol.contract_id != expected_contract
            or protocol.unit_id != change.unit_id
            or protocol.protocol_type != step.direction
        ):
            raise ValidationError("Nur ein finalisiertes Übergabeprotokoll derselben Vertragsrichtung ist zulässig.")
        values = {
            "kind": "handover_protocol",
            "id": protocol.id,
            "contract_id": protocol.contract_id,
            "unit_id": protocol.unit_id,
            "protocol_type": protocol.protocol_type,
            "protocol_date": protocol.protocol_date.isoformat(),
            "status": protocol.status,
            "updated_at": protocol.updated_at.isoformat(),
        }
        return values, digest(values)

    if evidence.kind == "meter_reading":
        if (
            not evidence.meter_reading_id
            or evidence.document_id
            or evidence.document_version_id
            or evidence.handover_protocol_id
        ):
            raise ValidationError("Zählerbeleg benötigt genau eine Ablesungs-ID.")
        if unit.db is not None:
            unit.db.scalar(
                select(MeterReadingORM.id)
                .where(MeterReadingORM.id == evidence.meter_reading_id)
                .with_for_update()
            )
        reading = unit.store.get_meter_reading(evidence.meter_reading_id)
        protocol = unit.store.get_handover_protocol(reading.handover_id)
        if (
            protocol.status != "finalized"
            or protocol.contract_id != expected_contract
            or protocol.unit_id != change.unit_id
            or protocol.protocol_type != step.direction
        ):
            raise ValidationError("Die Zählerablesung benötigt ein finalisiertes Protokoll derselben Vertragsrichtung.")
        values = {
            "kind": "meter_reading",
            "id": reading.id,
            "handover_id": reading.handover_id,
            "meter_type": reading.meter_type,
            "meter_number": reading.meter_number,
            "reading_value": reading.reading_value,
            "unit": reading.unit,
            "created_at": reading.created_at.isoformat(),
            "protocol_snapshot": {
                "id": protocol.id,
                "contract_id": protocol.contract_id,
                "unit_id": protocol.unit_id,
                "protocol_type": protocol.protocol_type,
                "status": protocol.status,
                "updated_at": protocol.updated_at.isoformat(),
            },
        }
        return values, digest(values)
    raise ValidationError("Unbekannte Belegart.")


def _same_evidence(left: Any, evidence: Any) -> bool:
    if evidence.kind == "document_version":
        return left.kind == evidence.kind and left.document_id == evidence.document_id and left.document_version_id == evidence.document_version_id
    if evidence.kind == "handover_protocol":
        return left.kind == evidence.kind and left.handover_protocol_id == evidence.handover_protocol_id
    return left.kind == evidence.kind and left.meter_reading_id == evidence.meter_reading_id


def add_evidence(
    store: Any, change_id: str, step_id: str, payload: AddEvidence, actor_id: str
) -> dict[str, Any]:
    with work(store, actor_id, write=True) as unit:
        _lock_document_tenant_first(unit, change_id, step_id, payload.evidence)
        change, steps = _load_change(unit, change_id, lock=True)
        step = _load_step(unit, change, step_id, lock=True)
        if not _responsible(unit, step):
            raise HTTPException(403, "Dieser Schritt ist Ihnen nicht zur Ausführung zugewiesen.")
        request_hash = _request_hash("add_workflow_evidence", payload)
        replay = _command(unit, actor_id, payload.idempotency_key, "add_workflow_evidence", request_hash)
        if replay is not None:
            return replay
        _revision(change, payload.expected_change_revision)
        _revision(step, payload.expected_revision)
        if change.state != "active" or step.state in {"completed", "not_applicable"}:
            raise conflict("Belege eines abgeschlossenen Schritts bleiben unverändert.")
        if any(_same_evidence(link, payload.evidence) for link in _step_evidence(unit, step.id)):
            raise conflict("Dieser Originalbeleg ist bereits mit dem Schritt verknüpft.")
        _, snapshot_hash = _evidence_snapshot(unit, change, step, payload.evidence)
        link = WorkflowEvidenceLinkORM(
            id=str(uuid4()),
            tenancy_change_id=change.id,
            step_id=step.id,
            portfolio_id=change.portfolio_id,
            kind=payload.evidence.kind,
            document_id=payload.evidence.document_id,
            document_version_id=payload.evidence.document_version_id,
            handover_protocol_id=payload.evidence.handover_protocol_id,
            meter_reading_id=payload.evidence.meter_reading_id,
            snapshot_sha256=snapshot_hash,
            created_by=actor_id,
            created_at=now(),
        )
        unit.add(link)
        _touch_step(unit, step)
        _touch_change(unit, change)
        if unit.db is not None:
            unit.db.flush()
        response = _step_public(unit, change, step, _step_map(steps))
        return _save_command(
            unit,
            actor_id,
            payload.idempotency_key,
            "add_workflow_evidence",
            "workflow_step",
            step.id,
            change.portfolio_id,
            request_hash,
            response,
        )


def remove_evidence(
    store: Any,
    change_id: str,
    step_id: str,
    link_id: str,
    payload: RemoveEvidence,
    actor_id: str,
) -> dict[str, Any]:
    with work(store, actor_id, write=True) as unit:
        change, steps = _load_change(unit, change_id, lock=True)
        step = _load_step(unit, change, step_id, lock=True)
        if not _responsible(unit, step):
            raise HTTPException(403, "Dieser Schritt ist Ihnen nicht zur Ausführung zugewiesen.")
        request_hash = _request_hash("remove_workflow_evidence", {"link_id": link_id, **payload.model_dump(mode="json")})
        replay = _command(unit, actor_id, payload.idempotency_key, "remove_workflow_evidence", request_hash)
        if replay is not None:
            return replay
        _revision(change, payload.expected_change_revision)
        _revision(step, payload.expected_revision)
        if change.state != "active" or step.state in {"completed", "not_applicable"}:
            raise conflict("Belege eines abgeschlossenen Schritts bleiben unverändert.")
        link = _row(unit, WorkflowEvidenceLinkORM, link_id, lock=True)
        if link is None or link.step_id != step.id or link.tenancy_change_id != change.id:
            raise HTTPException(404, "Belegverknüpfung nicht gefunden.")
        if unit.db is not None:
            unit.db.delete(link)
            unit.db.flush()
        else:
            unit.touch(WorkflowEvidenceLinkORM.__tablename__, link.id)
            unit.store.__dict__[WorkflowEvidenceLinkORM.__tablename__].pop(link.id, None)
        _touch_step(unit, step)
        _touch_change(unit, change)
        response = _step_public(unit, change, step, _step_map(steps))
        return _save_command(
            unit,
            actor_id,
            payload.idempotency_key,
            "remove_workflow_evidence",
            "workflow_step",
            step.id,
            change.portfolio_id,
            request_hash,
            response,
        )


def complete_change(
    store: Any, change_id: str, payload: CompleteTenancyChange, actor_id: str
) -> dict[str, Any]:
    with work(store, actor_id, write=True) as unit:
        _require_manager(unit.user)
        change, steps = _load_change(unit, change_id, lock=True)
        request_hash = _request_hash("complete_tenancy_change", payload)
        replay = _command(unit, actor_id, payload.idempotency_key, "complete_tenancy_change", request_hash)
        if replay is not None:
            return replay
        _revision(change, payload.expected_revision)
        if change.state != "active":
            raise conflict("Die Wechselakte ist nicht mehr aktiv.")
        mapping = _step_map(steps)
        blockers = [
            {
                "step_id": step.id,
                "state": _step_public(unit, change, step, mapping)["state"],
                "blocked_by_step_ids": _unresolved(step, mapping),
            }
            for step in steps
            if step.requirement == "required" and step.state not in {"completed", "not_applicable"}
        ]
        if blockers:
            raise HTTPException(
                409,
                {
                    "message": "Pflichtschritte verhindern den Abschluss.",
                    "blocking_steps": blockers,
                },
            )
        _touch_change(unit, change)
        change.state = "completed"
        for step in steps:
            if step.task_id and step.state not in {"completed", "not_applicable"}:
                _write_task(unit, step, status="cancelled")
        if unit.db is not None:
            unit.db.flush()
        response = _change_public(unit, change)
        return _save_command(
            unit,
            actor_id,
            payload.idempotency_key,
            "complete_tenancy_change",
            "tenancy_change",
            change.id,
            change.portfolio_id,
            request_hash,
            response,
        )


def _workflow_tables_present(store: Any) -> bool:
    if not hasattr(store, "db"):
        return WorkflowStepInstanceORM.__tablename__ in store.__dict__
    from sqlalchemy import inspect

    return inspect(store.db.get_bind()).has_table(WorkflowStepInstanceORM.__tablename__)


def _linked_task_step(store: Any, task_id: str):
    if not _workflow_tables_present(store):
        return None
    if hasattr(store, "db"):
        # The task itself is already authorized by BaseRepository. Read only an
        # existence/source row here so a corrupted hidden workflow cannot turn
        # a visible workflow-owned task into an ordinary mutable task.
        return store.db.connection().execute(
            select(
                WorkflowStepInstanceORM.id,
                WorkflowStepInstanceORM.task_id,
            ).where(WorkflowStepInstanceORM.task_id == task_id).limit(1)
        ).first()
    return next(
        (
            row
            for row in store.__dict__.get(WorkflowStepInstanceORM.__tablename__, {}).values()
            if row.task_id == task_id
        ),
        None,
    )


def guard_task_workflow_edit(store: Any, task_id: str, current: Any, changes: dict[str, Any]) -> None:
    linked = _linked_task_step(store, task_id)
    if linked is None:
        return
    linked_id = linked.id if hasattr(linked, "id") else linked[0]
    if _TASK_WRITE_STEP.get() == linked_id:
        return
    protected = {
        "title",
        "description",
        "assignee",
        "due_date",
        "status",
        "property_id",
        "unit_id",
        "recurrence_rule",
        "parent_task_id",
    }
    if any(key in changes and changes[key] != getattr(current, key) for key in protected):
        raise ValidationError(
            "Diese Aufgabe wird von einer Mieterwechselakte gesteuert. Änderung im zugehörigen Workflowschritt ausführen."
        )


def guard_task_workflow_delete(store: Any, task_id: str) -> None:
    if _linked_task_step(store, task_id) is not None:
        raise ValidationError(
            "Diese Aufgabe ist Fachbestandteil einer Mieterwechselakte und darf nicht direkt gelöscht werden."
        )


def _abort_guard(store: Any, message: str) -> NoReturn:
    if hasattr(store, "db"):
        store.db.rollback()
    raise ValidationError(message)


def _lock_handovers(store: Any, protocol_ids: Iterable[str]) -> dict[str, Any]:
    identifiers = sorted(set(protocol_ids))
    if not hasattr(store, "db"):
        return {identifier: store.get_handover_protocol(identifier) for identifier in identifiers}
    begin_writer(store.db)
    result: dict[str, Any] = {}
    for identifier in identifiers:
        row = store.db.scalar(
            select(HandoverProtocolORM)
            .where(HandoverProtocolORM.id == identifier)
            .with_for_update()
        )
        if row is None:
            store.db.rollback()
            raise NotFoundError("Übergabeprotokoll nicht gefunden")
        result[identifier] = row
    return result


def _lock_meter(store: Any, reading_id: str):
    if not hasattr(store, "db"):
        return store.get_meter_reading(reading_id)
    begin_writer(store.db)
    row = store.db.scalar(
        select(MeterReadingORM)
        .where(MeterReadingORM.id == reading_id)
        .with_for_update()
    )
    if row is None:
        store.db.rollback()
        raise NotFoundError("Zählerstand nicht gefunden")
    return row


def _handover_is_final(store: Any, protocol_id: str) -> bool:
    return _lock_handovers(store, (protocol_id,))[protocol_id].status == "finalized"


def guard_handover_edit(store: Any, protocol_id: str, current: Any, changes: dict[str, Any]) -> None:
    current = _lock_handovers(store, (protocol_id,))[protocol_id]
    if current.status == "finalized":
        _abort_guard(
            store,
            "Ein finalisiertes Übergabeprotokoll ist ein abgeschlossener Beleg und bleibt unverändert.",
        )


def guard_handover_delete(store: Any, protocol_id: str) -> None:
    current = _lock_handovers(store, (protocol_id,))[protocol_id]
    if current.status == "finalized":
        _abort_guard(store, "Ein finalisiertes Übergabeprotokoll darf nicht gelöscht werden.")
    if _workflow_tables_present(store):
        if hasattr(store, "db"):
            linked = store.db.connection().scalar(
                select(WorkflowEvidenceLinkORM.id)
                .where(WorkflowEvidenceLinkORM.handover_protocol_id == protocol_id)
                .limit(1)
            )
        else:
            linked = next(
                (
                    row.id
                    for row in store.__dict__.get(WorkflowEvidenceLinkORM.__tablename__, {}).values()
                    if row.handover_protocol_id == protocol_id
                ),
                None,
            )
        if linked is not None:
            _abort_guard(store, "Das Übergabeprotokoll ist als Workflowbeleg verknüpft und muss erhalten bleiben.")


def guard_meter_create(store: Any, handover_id: str) -> None:
    protocol = _lock_handovers(store, (handover_id,))[handover_id]
    if protocol.status == "finalized":
        _abort_guard(
            store,
            "Zu einem finalisierten Übergabeprotokoll dürfen keine Zählerstände nachgetragen werden.",
        )


def guard_meter_edit(store: Any, reading_id: str, current: Any, changes: dict[str, Any]) -> None:
    proposed_handover = changes.get("handover_id", current.handover_id)
    handovers = _lock_handovers(store, (current.handover_id, proposed_handover))
    current = _lock_meter(store, reading_id)
    # Re-read the current parent after waiting for the common parent locks.
    if current.handover_id not in handovers:
        _abort_guard(store, "Die Zählerzuordnung wurde parallel geändert. Bestand neu laden.")
    target = handovers.get(changes.get("handover_id", current.handover_id))
    if target is None:
        _abort_guard(store, "Die Zählerzuordnung wurde parallel geändert. Bestand neu laden.")
    if handovers[current.handover_id].status == "finalized" or target.status == "finalized":
        _abort_guard(
            store,
            "Zählerstände eines finalisierten Übergabeprotokolls bleiben unverändert.",
        )
    if _workflow_tables_present(store):
        if hasattr(store, "db"):
            linked = store.db.connection().scalar(
                select(WorkflowEvidenceLinkORM.id)
                .where(WorkflowEvidenceLinkORM.meter_reading_id == reading_id)
                .limit(1)
            )
        else:
            linked = next(
                (
                    row.id
                    for row in store.__dict__.get(WorkflowEvidenceLinkORM.__tablename__, {}).values()
                    if row.meter_reading_id == reading_id
                ),
                None,
            )
        if linked is not None:
            _abort_guard(store, "Der verknüpfte Zählerbeleg ist eingefroren und bleibt unverändert.")


def guard_meter_delete(store: Any, reading_id: str) -> None:
    current = store.get_meter_reading(reading_id)
    handover = _lock_handovers(store, (current.handover_id,))[current.handover_id]
    current = _lock_meter(store, reading_id)
    if current.handover_id != handover.id:
        _abort_guard(store, "Die Zählerzuordnung wurde parallel geändert. Bestand neu laden.")
    if handover.status == "finalized":
        _abort_guard(
            store,
            "Zählerstände eines finalisierten Übergabeprotokolls dürfen nicht gelöscht werden.",
        )
    if _workflow_tables_present(store):
        if hasattr(store, "db"):
            linked = store.db.connection().scalar(
                select(WorkflowEvidenceLinkORM.id)
                .where(WorkflowEvidenceLinkORM.meter_reading_id == reading_id)
                .limit(1)
            )
        else:
            linked = next(
                (
                    row.id
                    for row in store.__dict__.get(WorkflowEvidenceLinkORM.__tablename__, {}).values()
                    if row.meter_reading_id == reading_id
                ),
                None,
            )
        if linked is not None:
            _abort_guard(store, "Der verknüpfte Zählerbeleg muss erhalten bleiben.")
