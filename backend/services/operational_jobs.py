"""Independent, fair, restart-persistent packets; legacy ticks stay atomic.

Phase 1 covers overdue money items and approved correspondence dates only.
No email, cash posting, global scheduler hook, or implicit caller-session commit.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from heapq import nsmallest
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, inspect, or_, select, text, update
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from .. import auth
from ..db.contract_correspondence_models import CorrespondenceDraftORM
from ..db.operational_job_models import JOB_MODELS, OperationalJobLaneORM, OperationalJobORM, OperationalWorkItemORM
from ..db.operational_models import OperationalDispatchORM, OperationalLockORM, OperationalOccurrenceORM
from ..db.orm_models import CalendarEventORM, ReceivableORM, RentChargeORM
from ..models import CalendarEvent, CalendarEventCreate, Notification, NotificationCreate
from ..repositories.sql_store import SQLAlchemyStore
from ..storage import NotFoundError
from . import contract_correspondence as correspondence
from .concurrency import next_updated_at
from .contract_lifecycle import Work, digest
from .contract_occupancy import begin_writer
from .correspondence_calendar import STALE_MARKER, account_lock
from .operational_job_types import JobCommand, JobContinue, JobCreate, PacketPolicy
from .operational_schedule import _key, _memory_lock, _seed_lock, _state_lock, _Transaction
from .payments import payment_total
from .portfolio_scope import current_scope, refresh_scope, scope_context, scope_from_user

POLICY = PacketPolicy()
_request_token: ContextVar[str | None] = ContextVar("operational_job_request_token", default=None)
SOURCE_MODELS: dict[str, Any] = {"overdue_rent_charge": RentChargeORM, "overdue_receivable": ReceivableORM,
                 "correspondence": CorrespondenceDraftORM}
COLLECTIONS = {"overdue_rent_charge": "rent_charges", "overdue_receivable": "receivables",
               "correspondence": "contract_correspondence_drafts"}


class ClaimLost(RuntimeError):
    pass


class AuthorizationUnavailable(RuntimeError):
    pass


@contextmanager
def request_token(token: str | None):
    """Ephemeral request context only: never stored in a job, receipt or claim."""
    marker = _request_token.set(token)
    try:
        yield
    finally:
        _request_token.reset(marker)


def _fresh(captured):
    refresh_scope(captured)
    token = _request_token.get()
    if captured is None or token is None:
        return
    try:
        # Revalidate expiry and persistent/session revocation without decode_token's
        # last-used writer, which would contend with our SQLite transaction.
        claims = auth.decode_signed_token(token)
        if claims.type != "access" or claims.sub != captured.user_id or auth.is_token_revoked(token):
            raise HTTPException(401, "Sitzung abgelaufen oder widerrufen. Bitte erneut anmelden.")
    except HTTPException as error:
        if error.status_code == 503:
            raise AuthorizationUnavailable("authorization_unavailable") from None
        raise


@dataclass(frozen=True)
class Claim:
    job_id: str
    lane_id: str
    token: str
    fence: int
    actor_id: str


def _clock(db=None):
    if db is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if db.get_bind().dialect.name == "postgresql":
        value = db.scalar(select(func.clock_timestamp()))
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    value = db.scalar(select(func.strftime("%Y-%m-%d %H:%M:%f", "now")))
    return datetime.fromisoformat(value)


def _scope_hash(captured):
    return digest([captured.user_id, captured.role, captured.unrestricted, captured.portfolio_ids])


def _operator(actor_id=None):
    current = current_scope()
    identifier = actor_id or (current.user_id if current else None)
    if not identifier or current and current.user_id != identifier:
        raise HTTPException(403, "Ein ausdrücklicher zuständiger Benutzer ist erforderlich.")
    user = auth.get_user_by_id(identifier)
    if not user or not user["is_active"]:
        raise HTTPException(403, "Der zuständige Benutzer ist nicht mehr aktiv.")
    captured = scope_from_user(user)
    if captured.role not in {"eigentuemer", "verwalter"} or not captured.unrestricted:
        raise HTTPException(403, "Operative Arbeitslisten benötigen installationsweite Verwaltungsrechte.")
    _fresh(current if current is not None else captured)
    return captured


class Unit(_Transaction):
    """SQL caller transaction or per-written-row Memory undo, never full copies."""
    def __init__(self, store, db, captured):
        super().__init__(store, db)
        self.captured = captured
        self.undo: dict[tuple[str, str], tuple[bool, Any]] = {}

    def touch(self, collection, identifier):
        if self.db is None and (collection, identifier) not in self.undo:
            rows = self.store.__dict__.setdefault(collection, {})
            self.undo[collection, identifier] = (identifier in rows, deepcopy(rows.get(identifier)))

    def touch_row(self, row):
        self.touch(row.__tablename__, row.id)

    def add(self, row):
        if self.db is not None:
            self.db.add(row)
            self.db.flush()
        else:
            self.touch_row(row)
            self.store.__dict__[row.__tablename__][row.id] = row

    def row(self, model, identifier):
        return self.db.get(model, identifier) if self.db is not None else self.store.__dict__.get(model.__tablename__, {}).get(identifier)

    def rollback(self):
        for (collection, identifier), (present, previous) in reversed(tuple(self.undo.items())):
            rows = self.memory[collection[1:]] if collection.startswith("@") else self.store.__dict__[collection]
            if present:
                rows[identifier] = previous
            else:
                rows.pop(identifier, None)

    def journal_touch(self, collection, identifier):
        if self.db is None and ("@" + collection, identifier) not in self.undo:
            rows = self.memory[collection]
            self.undo[("@" + collection, identifier)] = (identifier in rows, deepcopy(rows.get(identifier)))

    def create(self, kind, payload):
        if self.db is not None:
            return super().create(kind, payload)
        model, collection = {"calendar": (CalendarEvent, "calendar_events"), "notification": (Notification, "notifications")}[kind]
        value = model(id=str(uuid4()), **payload.model_dump())
        self.touch(collection, value.id)
        getattr(self.store, collection)[value.id] = value
        return value

    def notify(self, key, payload, role=None):
        if self.db is None:
            self.journal_touch("dispatches", key)
            previous = self.memory["dispatches"].get(key)
            if previous:
                self.touch("notifications", previous.notification_id)
        return super().notify(key, payload, role)

    def record(self, schedule_id, day, kind, target_id):
        self.journal_touch("occurrences", _key(schedule_id, day))
        return super().record(schedule_id, day, kind, target_id)


@contextmanager
def atomic(store, captured):
    """Same auth -> operational -> domain ordering as legacy, bounded Memory undo."""
    if hasattr(store, "db"):
        bind = store.db.get_bind()
        with scope_context(captured), Session(bind=getattr(bind, "engine", bind), expire_on_commit=False) as db:
            with db.begin():
                begin_writer(db)
                if db.get_bind().dialect.name == "postgresql":
                    # Apply before the first contended auth/domain row lock.
                    db.execute(text("SET LOCAL lock_timeout = '5s'"))
                    db.execute(text("SET LOCAL statement_timeout = '10s'"))
                if captured is not None and isinstance(auth._user_store, auth.SQLUserStore):
                    auth._user_store._lock_management(db)
                _fresh(captured)
                _seed_lock(db.connection())
                # The existing generation is only the native lock carrier here;
                # repeated job packets/polls must not exhaust a legacy counter.
                db.execute(update(OperationalLockORM).where(OperationalLockORM.id == 1)
                           .values(generation=OperationalLockORM.generation))
                unit = Unit(SQLAlchemyStore(db), db, captured)
                yield unit
                _fresh(captured)
        store.db.expire_all()
    else:
        with scope_context(captured), account_lock(), _state_lock, _memory_lock:
            unit = Unit(store, None, captured)
            try:
                _fresh(captured)
                yield unit
                _fresh(captured)
            except Exception:
                unit.rollback()
                raise


def _schema(store):
    if hasattr(store, "db"):
        tables = set(inspect(store.db.get_bind()).get_table_names())
        if not {model.__tablename__ for model in JOB_MODELS}.issubset(tables):
            raise HTTPException(503, "Die vollständige Arbeitslistenmigration ist erforderlich.")


def _job(unit, identifier):
    row = unit.row(OperationalJobORM, identifier)
    if row is None:
        raise HTTPException(404, "Arbeitslauf nicht gefunden.")
    if unit.captured is not None and (row.actor_id != unit.captured.user_id or row.scope_hash != _scope_hash(unit.captured)):
        raise HTTPException(403, "Der Arbeitslauf gehört zu einem anderen Berechtigungsstand.")
    return row


def _lanes(unit, job_id):
    if unit.db is not None:
        return list(unit.db.scalars(select(OperationalJobLaneORM).where(OperationalJobLaneORM.job_id == job_id).order_by(OperationalJobLaneORM.family)))
    return sorted((row for row in unit.store.__dict__.get(OperationalJobLaneORM.__tablename__, {}).values()
                   if row.job_id == job_id), key=lambda row: row.family)


def _view(unit, job):
    fields = ("id", "family", "state", "scanned", "created", "updated", "skipped", "exhausted", "last_error")
    lanes = []
    for row in _lanes(unit, job.id):
        view = {key: getattr(row, key) for key in fields}
        available = max((stamp for stamp in (row.next_attempt_at, row.lease_expires_at) if stamp is not None), default=None) if row.state == "ready" else None
        view["available_at"] = available.isoformat() + "Z" if available else None
        lanes.append(view)
    return {"id": job.id, "state": job.state, "revision": job.revision, "parameters": deepcopy(job.parameters),
            "lanes": lanes, "has_more": job.state in {"queued", "running"}}


def _bounds(parameters):
    point = date.fromisoformat(parameters["as_of"])
    return point, date.fromordinal(max(1, point.toordinal() - parameters["lookback_days"])), date.fromordinal(min(date.max.toordinal(), point.toordinal() + parameters["days_ahead"]))


def _source_query(family, parameters):
    model = SOURCE_MODELS[family]
    point, _, upper = _bounds(parameters)
    query = select(model.id)
    if family == "correspondence":
        return query.where(model.state == "approved", model.deadline_date <= upper)
    query = query.where(model.status.not_in(("paid", "cancelled", "void")))
    if family == "overdue_receivable":
        return query.where(model.due_date < point, model.amount_due > model.amount_paid)
    amount = sum(func.coalesce(getattr(model, key), 0) for key in ("cold_rent", "service_charge", "heating_charge", "other_charges"))
    month = point.strftime("%Y-%m")
    return query.where(model.month <= month if point.day > 3 else model.month < month, amount > func.coalesce(model.amount_paid, 0))


def _source_memory(unit, family, parameters):
    point, _, upper = _bounds(parameters)
    for row in unit.store.__dict__.get(COLLECTIONS[family], {}).values():
        if family == "correspondence":
            eligible = row.state == "approved" and row.deadline_date <= upper
        else:
            due = row.due_date if family == "overdue_receivable" else date.fromisoformat(row.month + "-03")
            kind = family.removeprefix("overdue_")
            eligible = row.status not in {"paid", "cancelled", "void"} and due < point and payment_total(kind, row) > Decimal(str(row.amount_paid or 0))
        if eligible:
            yield row.id


def _upper(unit, family, parameters):
    if unit.db is not None:
        return unit.db.scalar(_source_query(family, parameters).order_by(SOURCE_MODELS[family].id.desc()).limit(1))
    return max(_source_memory(unit, family, parameters), default=None)


def create_job(store, payload: JobCreate, actor_id=None):
    captured = _operator(actor_id)
    _schema(store)
    parameters = payload.model_dump(mode="json", exclude={"idempotency_key"}) | {"semantics_version": 1}
    request_hash = digest(parameters)
    # Index the digest, so legitimate long caller references never hit the
    # PostgreSQL B-tree tuple-size limit. Command receipts retain their request.
    create_key = digest(payload.idempotency_key)
    with atomic(store, captured) as unit:
        if unit.db is not None:
            previous = unit.db.scalar(select(OperationalJobORM).where(OperationalJobORM.actor_id == captured.user_id,
                OperationalJobORM.create_key == create_key).limit(1))
        else:
            previous = next((row for row in unit.store.__dict__.get(OperationalJobORM.__tablename__, {}).values()
                if row.actor_id == captured.user_id and row.create_key == create_key), None)
        if previous:
            if previous.request_hash != request_hash or previous.scope_hash != _scope_hash(captured):
                raise HTTPException(409, "Die Vorgangsreferenz wurde mit anderen Eingaben verwendet.")
            return _view(unit, previous)
        now = _clock(unit.db)
        job = OperationalJobORM(id=str(uuid4()), actor_id=captured.user_id, create_key=create_key,
            request_hash=request_hash, scope_hash=_scope_hash(captured), parameters=parameters,
            revision=1, state="queued", turn=0, created_at=now, updated_at=now)
        unit.add(job)
        for family in parameters["families"]:
            upper = _upper(unit, family, parameters)
            unit.add(OperationalJobLaneORM(id=str(uuid4()), job_id=job.id, family=family, state="ready",
                cursor=None, upper=upper, exhausted=upper is None, served=0, fence=0,
                lease_token=None, lease_owner=None, lease_expires_at=None, next_attempt_at=None,
                last_error=None, scanned=0, created=0, updated=0, skipped=0))
        return _view(unit, job)


def read_job(store, identifier, actor_id=None):
    captured = _operator(actor_id)
    _schema(store)
    with atomic(store, captured) as unit:
        return _view(unit, _job(unit, identifier))


def claim_lane(store, identifier, worker_id, *, actor_id=None, policy=POLICY):
    captured = _operator(actor_id)
    _schema(store)
    with atomic(store, captured) as unit:
        job = _job(unit, identifier)
        if job.state in {"cancelled", "completed"}:
            return None
        now = _clock(unit.db)
        if unit.db is not None:
            lane = unit.db.scalar(select(OperationalJobLaneORM).where(OperationalJobLaneORM.job_id == job.id,
                OperationalJobLaneORM.state == "ready",
                or_(OperationalJobLaneORM.lease_expires_at.is_(None), OperationalJobLaneORM.lease_expires_at <= now),
                or_(OperationalJobLaneORM.next_attempt_at.is_(None), OperationalJobLaneORM.next_attempt_at <= now))
                .order_by(OperationalJobLaneORM.served, OperationalJobLaneORM.family).limit(1).with_for_update())
        else:
            lane = next(iter(sorted((row for row in _lanes(unit, job.id) if row.state == "ready"
                and (row.lease_expires_at is None or row.lease_expires_at <= now)
                and (row.next_attempt_at is None or row.next_attempt_at <= now)), key=lambda row: (row.served, row.family))), None)
        if lane is None:
            return None
        unit.touch_row(job)
        unit.touch_row(lane)
        job.turn += 1
        job.revision += 1
        job.state, job.updated_at = "running", now
        lane.served = job.turn
        lane.fence += 1
        lane.lease_token, lane.lease_owner = str(uuid4()), worker_id
        lane.lease_expires_at = now + timedelta(seconds=policy.lease_seconds)
        return Claim(job.id, lane.id, lane.lease_token, lane.fence, captured.user_id)


def _checked_claim(unit, claim):
    job = _job(unit, claim.job_id)
    lane = unit.row(OperationalJobLaneORM, claim.lane_id)
    if (lane is None or lane.job_id != job.id or job.state == "cancelled" or lane.state != "ready"
            or lane.lease_token != claim.token or lane.fence != claim.fence
            or lane.lease_expires_at is None or lane.lease_expires_at <= _clock(unit.db)):
        raise ClaimLost("The packet claim expired or was replaced")
    return job, lane


def _source(unit, family, identifier, *, lock=False):
    if unit.db is not None and lock:
        model = SOURCE_MODELS[family]
        value = unit.db.scalar(select(model).where(model.id == identifier).with_for_update().execution_options(populate_existing=True))
        if value is None:
            raise NotFoundError("Quelle nicht gefunden")
    if family == "correspondence":
        return unit.row(CorrespondenceDraftORM, identifier)
    return getattr(unit.store, "get_" + family.removeprefix("overdue_"))(identifier)


def _revision(source):
    if getattr(source, "review_hash", None):
        return source.review_hash
    return digest(source.model_dump(mode="json"))


def _discover(unit, job, lane, width, deadline):
    if lane.exhausted:
        return
    if unit.db is not None:
        model = SOURCE_MODELS[lane.family]
        query = _source_query(lane.family, job.parameters).where(model.id <= lane.upper)
        if lane.cursor is not None:
            query = query.where(model.id > lane.cursor)
        rows = list(unit.db.scalars(query.order_by(model.id).limit(width + 1)))
    else:
        rows = nsmallest(width + 1, (identifier for identifier in _source_memory(unit, lane.family, job.parameters)
            if identifier <= lane.upper and (lane.cursor is None or identifier > lane.cursor)))
    unit.touch_row(lane)
    consumed = 0
    for identifier in rows[:width]:
        # A slow first bounded query must still make progress; the final
        # database-time lease fence remains the hard publication boundary.
        if consumed and monotonic() >= deadline:
            break
        try:
            source = _source(unit, lane.family, identifier)
        except NotFoundError:
            source = None
        if source is not None and _needed(unit, job, lane, source):
            unit.add(OperationalWorkItemORM(id=str(uuid4()), job_id=job.id, lane_id=lane.id, kind="source",
                action_key=lane.family + ":" + identifier, source_id=identifier, planned_revision=_revision(source),
                state="ready", revision=1, attempts=0, next_attempt_at=None, error_code=None, result={}, created_at=_clock(unit.db)))
        else:
            lane.skipped += 1
        lane.cursor, lane.scanned = identifier, lane.scanned + 1
        consumed += 1
    lane.exhausted = consumed == len(rows) or consumed == width and len(rows) <= width


def _items(unit, lane_id, state, limit, *, ready_at=None):
    if unit.db is not None:
        query = select(OperationalWorkItemORM).where(OperationalWorkItemORM.lane_id == lane_id, OperationalWorkItemORM.state == state)
        if ready_at is not None:
            query = query.where(or_(OperationalWorkItemORM.next_attempt_at.is_(None), OperationalWorkItemORM.next_attempt_at <= ready_at))
        return list(unit.db.scalars(query.order_by(OperationalWorkItemORM.id).limit(limit)))
    return nsmallest(limit, (row for row in unit.store.__dict__.get(OperationalWorkItemORM.__tablename__, {}).values()
        if row.lane_id == lane_id and row.state == state and (ready_at is None or row.next_attempt_at is None or row.next_attempt_at <= ready_at)), key=lambda row: row.id)


def _overdue(unit, job, lane, item):
    kind = lane.family.removeprefix("overdue_")
    try:
        source = _source(unit, lane.family, item.source_id, lock=True)
    except NotFoundError:
        return "skipped", {}
    point, _, _ = _bounds(job.parameters)
    due = source.due_date if kind == "receivable" else date.fromisoformat(source.month + "-03")
    remaining = (payment_total(kind, source) - Decimal(str(source.amount_paid or 0))).quantize(Decimal("0.01"))
    if source.status in {"paid", "cancelled", "void"} or remaining <= 0 or due >= point:
        return "skipped", {}
    contract = unit.store.get_contract(source.contract_id)
    tenant = unit.store.get_tenant(contract.tenant_id)
    key = _key("overdue", kind, source.id, due)
    previous = unit.db.get(OperationalDispatchORM, key) if unit.db is not None else unit.memory["dispatches"].get(key)
    previous_item = None
    if previous:
        try:
            previous_item = unit.store.get_notification(previous.notification_id).model_dump(mode="json")
        except NotFoundError:
            pass
    value = unit.notify(key, NotificationCreate(notification_type="overdue_payment",
        title=f"Überfällige Zahlung: {tenant.full_name}", content=f"Offener Restbetrag: {remaining:.2f} EUR. Fällig am {due}.",
        severity="warning", entity_type=kind, entity_id=source.id))
    outcome, target_id = ("created", value.id) if value else ("skipped", previous.notification_id if previous else None)
    if previous_item is not None and unit.store.get_notification(previous.notification_id).model_dump(mode="json") != previous_item:
        outcome = "updated"
    return outcome, {"executed_revision": _revision(source), "target_id": target_id, "effect_key": key}


def _needed(unit, job, lane, source):
    """Avoid materializing a new done-work record for every unchanged old source."""
    point, lower, upper = _bounds(job.parameters)
    if lane.family == "correspondence":
        schedule = "contract-correspondence:" + source.id + ":" + source.review_hash
        key = _key(schedule, source.deadline_date)
        previous = unit.db.get(OperationalOccurrenceORM, key) if unit.db is not None else unit.memory["occurrences"].get(key)
        if not previous:
            return lower <= source.deadline_date <= upper
        try:
            event = unit.store.get_calendar_event(previous.target_id)
        except NotFoundError:
            return False
        if STALE_MARKER in (event.description or ""):
            return False
        work = Work(unit.store, unit.db, unit.captured)
        contract, property = correspondence.parents(work, source.contract_id)
        checked = correspondence.load(work, contract, property, source.id, unit.captured.user_id)
        return correspondence.source_status(work, contract, property, checked) != "current"
    kind = lane.family.removeprefix("overdue_")
    due = source.due_date if kind == "receivable" else date.fromisoformat(source.month + "-03")
    remaining = (payment_total(kind, source) - Decimal(str(source.amount_paid or 0))).quantize(Decimal("0.01"))
    if source.status in {"paid", "cancelled", "void"} or remaining <= 0 or due >= point:
        return False
    previous = unit.db.get(OperationalDispatchORM, _key("overdue", kind, source.id, due)) if unit.db is not None else unit.memory["dispatches"].get(_key("overdue", kind, source.id, due))
    if not previous:
        return True
    try:
        notice = unit.store.get_notification(previous.notification_id)
    except NotFoundError:
        return False
    contract = unit.store.get_contract(source.contract_id)
    tenant = unit.store.get_tenant(contract.tenant_id)
    return (notice.title != f"Überfällige Zahlung: {tenant.full_name}"
            or notice.content != f"Offener Restbetrag: {remaining:.2f} EUR. Fällig am {due}."
            or notice.severity != "warning" or previous.archived_by_tick or previous.target_role is not None)


def _correspondence(unit, job, lane, item):
    # Immutable approved draft first identified without a reverse draft->parent lock.
    source = _source(unit, lane.family, item.source_id)
    if source is None or source.state != "approved":
        return "skipped", {}
    work = Work(unit.store, unit.db, unit.captured)
    contract, property = correspondence.parents(work, source.contract_id, lock=True)
    source = correspondence.load(work, contract, property, source.id, unit.captured.user_id)
    schedule = "contract-correspondence:" + source.id + ":" + source.review_hash
    if unit.db is not None:
        previous = list(unit.db.scalars(select(OperationalOccurrenceORM).where(OperationalOccurrenceORM.schedule_id == schedule).limit(2)))
    else:
        previous = nsmallest(2, (row for row in unit.memory["occurrences"].values() if row.schedule_id == schedule), key=lambda row: row.key)
    if len(previous) > 1:
        raise ValueError("correspondence_occurrence_invalid")
    status = correspondence.source_status(work, contract, property, source)
    if previous:
        try:
            event = unit.store.get_calendar_event(previous[0].target_id)
        except NotFoundError:
            return "skipped", {}  # Deliberate deletion remains a tombstone.
        if status != "current" and STALE_MARKER not in (event.description or ""):
            if unit.db is not None:
                target = unit.db.get(CalendarEventORM, event.id)
                target.description, target.updated_at = (event.description or "") + STALE_MARKER, next_updated_at(event.updated_at)
            else:
                unit.touch("calendar_events", event.id)
                unit.store.calendar_events[event.id] = event.model_copy(update={"description": (event.description or "") + STALE_MARKER,
                    "updated_at": next_updated_at(event.updated_at)})
            return "updated", {"target_id": event.id, "review_hash": source.review_hash, "effect_key": previous[0].key}
        return "skipped", {"target_id": event.id, "effect_key": previous[0].key}
    _, lower, upper = _bounds(job.parameters)
    if status != "current" or not lower <= source.deadline_date <= upper:
        return "skipped", {}
    event = unit.create("calendar", CalendarEventCreate(title="Bestätigter Verwaltungstermin", event_type="deadline",
        event_date=source.deadline_date, property_id=source.property_id, unit_id=source.unit_id,
        description=f"Bewusst bestätigter Verwaltungstermin, keine berechnete Rechtsfrist.\nGrundlage: {source.data['deadline_basis']}\nQuelle: /contracts/{source.contract_id}/correspondence/drafts/{source.id}\nFreigabestand: {source.review_hash}"))
    unit.record(schedule, source.deadline_date, "calendar", event.id)
    return "created", {"target_id": event.id, "review_hash": source.review_hash, "effect_key": _key(schedule, source.deadline_date)}


def _status(unit, job):
    unit.touch_row(job)
    lanes = _lanes(unit, job.id)
    job.state = "running" if any(row.state == "ready" for row in lanes) else "attention" if any(row.state == "attention" for row in lanes) else "completed"
    job.revision += 1
    job.updated_at = _clock(unit.db)


def _finish_claim(unit, claim, lane, *, release=True):
    _fresh(unit.captured)
    if unit.db is not None:
        # Stored timestamps are UTC without a zone. A PostgreSQL session may use
        # a different zone, and transaction-start now() cannot fence a late packet.
        now = func.timezone("UTC", func.clock_timestamp()) if unit.db.get_bind().dialect.name == "postgresql" else func.strftime("%Y-%m-%d %H:%M:%f", "now")
        changes = {"lease_token": None, "lease_owner": None, "lease_expires_at": None} if release else {"fence": claim.fence}
        result = unit.db.execute(update(OperationalJobLaneORM).where(OperationalJobLaneORM.id == claim.lane_id,
            OperationalJobLaneORM.lease_token == claim.token, OperationalJobLaneORM.fence == claim.fence,
            OperationalJobLaneORM.lease_expires_at > now).values(**changes)
            .execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise ClaimLost("The finishing fence rejected this packet")
        unit.db.expire(lane)
    else:
        if lane.lease_token != claim.token or lane.fence != claim.fence or lane.lease_expires_at <= _clock():
            raise ClaimLost("The finishing fence rejected this packet")
        if release:
            lane.lease_token = lane.lease_owner = lane.lease_expires_at = None


def prepare_claim(store, claim: Claim, payload: JobContinue, *, policy=POLICY):
    """Cursor and planned items commit together, before any business publication."""
    captured = _operator(claim.actor_id)
    with atomic(store, captured) as unit:
        job, lane = _checked_claim(unit, claim)
        if not _items(unit, lane.id, "ready", 1):
            _discover(unit, job, lane, min(payload.max_items, policy.page_size), monotonic() + policy.packet_seconds)
        _finish_claim(unit, claim, lane, release=False)


def run_claim(store, claim: Claim, payload: JobContinue, *, policy=POLICY):
    deadline = monotonic() + policy.packet_seconds
    current_item = None
    try:
        prepare_claim(store, claim, payload, policy=policy)
        captured = _operator(claim.actor_id)
        deadline = monotonic() + policy.packet_seconds
        with atomic(store, captured) as unit:
            job, lane = _checked_claim(unit, claim)
            width = min(payload.max_items, policy.page_size)
            unit.touch_row(lane)
            processed = 0
            for item in _items(unit, lane.id, "ready", width, ready_at=_clock(unit.db)):
                if processed and monotonic() >= deadline:
                    break
                current_item = item.id
                unit.touch_row(item)
                outcome, result = (_correspondence(unit, job, lane, item) if lane.family == "correspondence" else _overdue(unit, job, lane, item))
                setattr(lane, outcome, getattr(lane, outcome) + 1)
                item.state, item.result, item.error_code = "done", result, None
                item.revision, item.attempts = item.revision + 1, item.attempts + 1
                processed += 1
            if lane.exhausted and not _items(unit, lane.id, "ready", 1):
                lane.state = "attention" if _items(unit, lane.id, "attention", 1) else "completed"
            lane.last_error, lane.next_attempt_at = None, None
            _finish_claim(unit, claim, lane)
            _status(unit, job)
            return _view(unit, job)
    except ClaimLost:
        raise
    except Exception as error:
        _failure(store, claim, current_item, error)
        if isinstance(error, HTTPException) and error.status_code in {401, 403}:
            raise
        return read_job(store, claim.job_id, claim.actor_id)


def _failure(store, claim, item_id, error):
    """After packet rollback, only metadata under the still-current fence changes."""
    transient = isinstance(error, (AuthorizationUnavailable, OperationalError)) or isinstance(error, DBAPIError) and error.connection_invalidated
    code = ("actor_changed" if isinstance(error, HTTPException) and error.status_code in {401, 403}
            else "transient_authorization" if isinstance(error, AuthorizationUnavailable)
            else "transient_database" if transient else "source_invalid")
    with atomic(store, None) as unit:
        try:
            job, lane = _checked_claim(unit, claim)
        except ClaimLost:
            return
        unit.touch_row(lane)
        lane.last_error = code
        item = unit.row(OperationalWorkItemORM, item_id) if item_id else None
        if code == "actor_changed" or item is None and code == "source_invalid":
            lane.state = "attention"
        if item is not None:
            unit.touch_row(item)
            item.attempts += 1
            item.revision += 1
            item.error_code = code
            if code == "source_invalid":
                item.state = "attention"
            if transient:
                item.next_attempt_at = _clock(unit.db) + timedelta(seconds=min(300, 2 ** min(item.attempts, 8)))
                lane.next_attempt_at = item.next_attempt_at
        elif transient:
            lane.next_attempt_at = _clock(unit.db) + timedelta(seconds=2)
        _finish_claim(unit, claim, lane)
        _status(unit, job)
        if code == "actor_changed":
            job.state = "attention"


def continue_job(store, identifier, payload: JobContinue, actor_id=None, *, worker_id=None, policy=POLICY):
    claim = claim_lane(store, identifier, worker_id or str(uuid4()), actor_id=actor_id, policy=policy)
    return run_claim(store, claim, payload, policy=policy) if claim else read_job(store, identifier, actor_id)


def _command(unit, job, payload, operation, source_id=None):
    key = "command:" + digest(payload.idempotency_key)
    signature = digest({"operation": operation, "source_id": source_id, "request": payload.model_dump(mode="json")})
    if unit.db is not None:
        previous = unit.db.scalar(select(OperationalWorkItemORM).where(OperationalWorkItemORM.job_id == job.id,
            OperationalWorkItemORM.action_key == key).limit(1))
    else:
        previous = next((row for row in unit.store.__dict__.get(OperationalWorkItemORM.__tablename__, {}).values()
            if row.job_id == job.id and row.action_key == key), None)
    if previous:
        if (previous.kind != "command" or previous.state != "done"
                or digest(previous.result.get("request")) != previous.result.get("request_hash")):
            raise HTTPException(503, "Der gespeicherte Befehlsbeleg ist ungültig. Bestand prüfen.")
        if previous.result["request_hash"] != signature:
            raise HTTPException(409, "Dieser Befehl wurde mit anderen Eingaben verwendet.")
        return deepcopy(previous.result["receipt"]), signature
    if job.revision != payload.expected_revision:
        raise HTTPException(412, "Der Arbeitslauf wurde geändert. Aktuellen Stand prüfen.")
    return None, signature


def _receipt(unit, job, payload, signature, result, operation, source_id=None):
    unit.add(OperationalWorkItemORM(id=str(uuid4()), job_id=job.id, lane_id=None, kind="command",
        action_key="command:" + digest(payload.idempotency_key), source_id=None, planned_revision=None,
        state="done", revision=1, attempts=1, next_attempt_at=None, error_code=None,
        result={"request_hash": signature, "request": {"operation": operation, "source_id": source_id,
            "request": payload.model_dump(mode="json")}, "receipt": deepcopy(result)}, created_at=_clock(unit.db)))


def cancel_job(store, identifier, payload: JobCommand, actor_id=None):
    captured = _operator(actor_id)
    _schema(store)
    with atomic(store, captured) as unit:
        job = _job(unit, identifier)
        previous, signature = _command(unit, job, payload, "cancel")
        if previous:
            return previous
        unit.touch_row(job)
        for lane in _lanes(unit, job.id):
            unit.touch_row(lane)
            lane.state = "cancelled"
            lane.fence += 1
            lane.lease_token = lane.lease_owner = lane.lease_expires_at = None
        job.state, job.revision, job.updated_at = "cancelled", job.revision + 1, _clock(unit.db)
        result = _view(unit, job)
        _receipt(unit, job, payload, signature, result, "cancel")
        return result


def retry_item(store, identifier, item_id, payload: JobCommand, actor_id=None):
    captured = _operator(actor_id)
    _schema(store)
    with atomic(store, captured) as unit:
        job = _job(unit, identifier)
        previous, signature = _command(unit, job, payload, "retry", item_id)
        if previous:
            return previous
        item = unit.row(OperationalWorkItemORM, item_id)
        if item is None or item.job_id != job.id or item.kind != "source":
            raise HTTPException(404, "Arbeitslisteneintrag nicht gefunden.")
        if item.state != "attention" or job.state == "cancelled":
            raise HTTPException(409, "Dieser Eintrag benötigt keine Wiederholung oder ist abgebrochen.")
        lane = unit.row(OperationalJobLaneORM, item.lane_id)
        unit.touch_row(item)
        unit.touch_row(lane)
        item.state, item.error_code, item.next_attempt_at = "ready", None, None
        item.revision += 1
        lane.state, lane.last_error, lane.next_attempt_at = "ready", None, None
        lane.fence += 1
        lane.lease_token = lane.lease_owner = lane.lease_expires_at = None
        _status(unit, job)
        result = _view(unit, job)
        _receipt(unit, job, payload, signature, result, "retry", item_id)
        return result


def retry_lane(store, identifier, lane_id, payload: JobCommand, actor_id=None):
    """Explicit recovery of preparation/actor failures which have no item yet."""
    captured = _operator(actor_id)
    _schema(store)
    with atomic(store, captured) as unit:
        job = _job(unit, identifier)
        previous, signature = _command(unit, job, payload, "retry_lane", lane_id)
        if previous:
            return previous
        lane = unit.row(OperationalJobLaneORM, lane_id)
        if lane is None or lane.job_id != job.id:
            raise HTTPException(404, "Arbeitsliste nicht gefunden.")
        if lane.state != "attention" or job.state == "cancelled":
            raise HTTPException(409, "Diese Arbeitsliste benötigt keine Wiederholung.")
        unit.touch_row(lane)
        lane.state, lane.last_error, lane.next_attempt_at = "ready", None, None
        lane.fence += 1
        lane.lease_token = lane.lease_owner = lane.lease_expires_at = None
        _status(unit, job)
        result = _view(unit, job)
        _receipt(unit, job, payload, signature, result, "retry_lane", lane_id)
        return result


def item_page(store, identifier, *, after=None, page_size=64, actor_id=None):
    if type(page_size) is not int or page_size <= 0:
        raise HTTPException(422, "Die Seitengröße muss positiv sein.")
    captured = _operator(actor_id)
    _schema(store)
    with atomic(store, captured) as unit:
        _job(unit, identifier)
        if unit.db is not None:
            query = select(OperationalWorkItemORM).where(OperationalWorkItemORM.job_id == identifier, OperationalWorkItemORM.kind == "source")
            if after is not None:
                query = query.where(OperationalWorkItemORM.id > after)
            rows = list(unit.db.scalars(query.order_by(OperationalWorkItemORM.id).limit(page_size + 1)))
        else:
            rows = nsmallest(page_size + 1, (row for row in unit.store.__dict__.get(OperationalWorkItemORM.__tablename__, {}).values()
                if row.job_id == identifier and row.kind == "source" and (after is None or row.id > after)), key=lambda row: row.id)
        fields = ("id", "lane_id", "source_id", "state", "revision", "attempts", "error_code", "result")
        return {"items": [{key: deepcopy(getattr(row, key)) for key in fields} for row in rows[:page_size]],
                "next_cursor": rows[page_size - 1].id if len(rows) > page_size else None}
