"""Bounded local management-date projections in the caller's tick transaction.

This module never opens Lifecycle.Work, sends messages, or infers legal dates.
The immutable approved letter remains the source; calendar copies are labelled.
"""

import json
from contextlib import contextmanager, nullcontext
from datetime import date
from heapq import nsmallest
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from .. import auth
from ..config import settings
from ..db.contract_correspondence_models import CorrespondenceDraftORM
from ..db.operational_models import OperationalScheduleORM
from ..db.orm_models import CalendarEventORM, ContractORM
from ..models import CalendarEventCreate
from ..permissions import may_write_resource
from ..storage import NotFoundError
from . import contract_correspondence as correspondence
from .concurrency import next_updated_at
from .contract_lifecycle import Work, digest
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scope_from_user, scoped_clause

STALE_MARKER = "\nQuellenstand geändert: Das Schreiben muss erneut geprüft werden. Der ursprüngliche Verwaltungstermin bleibt als damaliger Kalenderbeleg erhalten."
CURSOR_KIND = "contract_correspondence_cursor"


@contextmanager
def account_lock():
    # Account -> operational state -> domain. Do not enter privacy's compound
    # account+domain lock before state: another old calendar writer needs state.
    lock = getattr(auth._user_store, "_lock", None)
    with lock if lock is not None else nullcontext():
        yield


def actor_scope(actor_id=None):
    captured = current_scope()
    identifier = actor_id.strip() if isinstance(actor_id, str) else None
    identifier = identifier or (captured.user_id if captured is not None else None)
    if identifier is None:
        return None  # Never inspect private journals without an explicit actor.
    user = auth.get_user_by_id(identifier)
    if not user or not user["is_active"]:
        raise HTTPException(401, "Der konfigurierte Kalenderbenutzer ist nicht mehr aktiv.")
    if not may_write_resource(user["role"], "calendar"):
        raise HTTPException(403, "Keine Berechtigung zur lokalen Kalenderprojektion.")
    if captured is not None and captured.user_id != identifier:
        raise HTTPException(403, "Der Kalenderbenutzer gehört nicht zu dieser Anfrage.")
    return refresh_scope(captured) if captured is not None else scope_from_user(user)


def _page(unit, upper, after, limit):
    if unit.db is not None:
        query = select(CorrespondenceDraftORM).join(ContractORM, ContractORM.id == CorrespondenceDraftORM.contract_id).where(
            CorrespondenceDraftORM.state == "approved", CorrespondenceDraftORM.deadline_date <= upper)
        for model in (CorrespondenceDraftORM, ContractORM):
            clause = scoped_clause(model, scope=unit.captured)
            if clause is not None:
                query = query.where(clause)
        if after is not None:
            query = query.where(or_(CorrespondenceDraftORM.deadline_date > after[0], and_(
                CorrespondenceDraftORM.deadline_date == after[0], CorrespondenceDraftORM.id > after[1])))
        return list(unit.db.scalars(query.order_by(CorrespondenceDraftORM.deadline_date, CorrespondenceDraftORM.id).limit(limit + 1)))
    contracts = unit.store.__dict__.get("contracts", {})
    return nsmallest(limit + 1, (row for row in unit.store.__dict__.get("contract_correspondence_drafts", {}).values()
        if row.state == "approved" and row.deadline_date <= upper and (after is None or (row.deadline_date, row.id) > after)
        and row.contract_id in contracts and memory_visible(unit.store, "contracts", contracts[row.contract_id], scope=unit.captured)),
        key=lambda row: (row.deadline_date, row.id))


def _position(schedule, scope_hash):
    try:
        value = json.loads(schedule.recurrence_rule)
        point = value["after"]
        if value["v"] == 1 and value["scope"] == scope_hash and point is not None:
            return date.fromisoformat(point[0]), point[1]
    except (ValueError, TypeError, KeyError, IndexError):
        pass
    return None


def _stale(tx, occurrence):
    try:
        event = tx.store.get_calendar_event(occurrence.target_id)
    except NotFoundError:
        return False  # A deliberate deletion/move remains a tombstone.
    if STALE_MARKER in (event.description or ""):
        return False
    changes = {"description": (event.description or "") + STALE_MARKER,
        "updated_at": next_updated_at(event.updated_at)}
    if tx.db is not None:
        current = tx.db.get(CalendarEventORM, event.id)
        for field, value in changes.items():
            setattr(current, field, value)
    else:
        tx.store.calendar_events[event.id] = event.model_copy(update=changes)
    return True


def project(tx, request, budget, captured):
    result = {"enabled": captured is not None, "scanned": 0, "created": 0, "stale_marked": 0, "has_more": False}
    if captured is None:
        return [], result | {"reason": "explicit_actor_required"}
    refresh_scope(captured)
    remaining = max(0, budget.limit - budget.used)
    if not remaining:
        return [], result | {"has_more": True}
    maximum = getattr(settings, "contract_correspondence_page_max_size", 100)
    page_size = min(25, maximum, remaining)
    upper = date.fromordinal(min(date.max.toordinal(), request.as_of.toordinal() + request.days_ahead))
    lower = date.fromordinal(max(1, request.as_of.toordinal() - request.lookback_days))
    cursor_id = f"{CURSOR_KIND}:{captured.user_id}"
    previous_cursor = tx.db.get(OperationalScheduleORM, cursor_id) if tx.db is not None else tx.memory["schedules"].get(cursor_id)
    cursor = tx.schedule(CURSOR_KIND, captured.user_id, request.as_of,
        previous_cursor.recurrence_rule if previous_cursor is not None else "{}")
    scope_hash = digest([captured.user_id, captured.role, captured.unrestricted, captured.portfolio_ids])
    point, created = _position(cursor, scope_hash), []
    unit = Work(tx.store, tx.db, captured)  # Caller owns commit/rollback; no new Session.
    # A bounded scan resumes on the next tick even when all previous rows were
    # already projected. There is no total count, stock cap or reset at midnight.
    scan_limit = min(request.max_items, max(0, (max(10000, budget.limit * 20) - budget.scanned) // 2))
    stopped = False
    while result["scanned"] < scan_limit and monotonic() < budget.deadline:
        rows = _page(unit, upper, point, min(page_size, scan_limit - result["scanned"]))
        if not rows:
            point = None  # Next tick starts a new freshness sweep.
            break
        width = min(page_size, scan_limit - result["scanned"])
        for item in rows[:width]:
            if budget.used >= budget.limit or monotonic() >= budget.deadline:
                stopped = True
                break
            budget.scan()
            contract, property = correspondence.parents(unit, item.contract_id, lock=True)
            checked = correspondence.load(unit, contract, property, item.id, captured.user_id)
            status = correspondence.source_status(unit, contract, property, checked)
            source = "contract-correspondence:" + checked.id + ":" + checked.review_hash
            previous = tx.occurrences(source)
            if status != "current":
                if previous and _stale(tx, previous[0]):
                    budget.take()
                    result["stale_marked"] += 1
            elif not previous and lower <= checked.deadline_date <= upper:
                refresh_scope(captured)
                budget.take()
                event = tx.create("calendar", CalendarEventCreate(
                    title="Bestätigter Verwaltungstermin", event_type="deadline", event_date=checked.deadline_date,
                    property_id=checked.property_id, unit_id=checked.unit_id,
                    description=f"Bewusst bestätigter Verwaltungstermin, keine berechnete Rechtsfrist.\nGrundlage: {checked.data['deadline_basis']}\nQuelle: /contracts/{checked.contract_id}/correspondence/drafts/{checked.id}\nFreigabestand: {checked.review_hash}"))
                tx.record(source, checked.deadline_date, "calendar", event.id)
                created.append(event)
                result["created"] += 1
            point = (checked.deadline_date, checked.id)
            result["scanned"] += 1
        if stopped:
            result["has_more"] = True
            break
        if len(rows) <= width:
            point = None
            break
        result["has_more"] = True
    if point is not None and (result["scanned"] >= scan_limit or monotonic() >= budget.deadline):
        result["has_more"] = True
    elif point is None:
        result["has_more"] = False
    cursor.recurrence_rule = json.dumps({"v": 1, "scope": scope_hash,
        "after": [point[0].isoformat(), point[1]] if point else None}, sort_keys=True)
    refresh_scope(captured)
    return created, result
