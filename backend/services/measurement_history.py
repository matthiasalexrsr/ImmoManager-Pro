"""Owned transactions for confirmed history and bounded evidence queries."""

import hashlib
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from copy import deepcopy
from datetime import date, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import exists, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from .. import auth
from ..db.document_version_models import DocumentVersionORM
from ..db.measurement_history_models import (
    MEASUREMENT_TABLES,
    MeasurementCommandORM,
    MeasurementEvidenceORM,
    MeasurementFactORM,
    MeasurementLedgerORM,
)
from ..db.measurement_history_schema import validate_measurement_schema
from ..db.orm_models import ContractORM, TenantORM
from ..permissions import may_write_resource
from .contract_occupancy import begin_writer, lock_location
from .measurement_history_types import MeasurementCommand
from .measurement_history_validation import (
    digest,
    fact_hash,
    payload,
    validate_effective,
    validate_fact,
)
from .portfolio_scope import current_scope, refresh_scope, scope_context, scope_from_user
from .request_authority import require_fresh_request_authority

_inserted: ContextVar[list | None] = ContextVar("measurement_inserted", default=None)


def conflict(message="Die Quellen wurden geändert. Aktuellen Stand laden und erneut bestätigen."):
    return HTTPException(409, message)


def lock_measurement_property(store, property_id: str) -> None:
    """Shared by billing and source writers, before any contract/parent lock."""
    db = getattr(store, "db", None)
    if db is None:
        return  # The existing Memory financial lock spans the caller operation.
    begin_writer(db)
    if db.get_bind().dialect.name == "postgresql":
        identifier = int.from_bytes(hashlib.sha256(("measurement:" + property_id).encode()).digest()[:8], "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:identifier)"), {"identifier": identifier})


def _identity(actor_id, write):
    record = auth.get_user_by_id(actor_id)
    if record is None or not record["is_active"]:
        raise HTTPException(401, "Anmeldung nicht mehr gültig.")
    if write and not may_write_resource(record["role"], "billing"):
        raise HTTPException(403, "Keine Berechtigung zur historischen Abrechnungsgrundlage.")
    captured = current_scope()
    if captured is not None and captured.user_id != actor_id:
        raise HTTPException(403, "Ungültige Benutzerbindung.")
    require_fresh_request_authority(actor_id)
    return refresh_scope(captured) if captured is not None else scope_from_user(record)


@contextmanager
def work(store, unit_id, actor_id, *, write=False):
    from .tenant_privacy import _memory_privacy_lock
    sql = hasattr(store, "db")
    with nullcontext() if sql else _memory_privacy_lock():
        captured = _identity(actor_id, write)
        with scope_context(captured):
            db = None
            active = store
            before = None
            inserted: list[tuple[str, str]] = []
            marker = _inserted.set(inserted)
            if sql:
                from ..repositories.sql_store import SQLAlchemyStore
                bind = store.db.get_bind()
                db = Session(getattr(bind, "engine", bind), autoflush=False, expire_on_commit=False)
                active = SQLAlchemyStore(db)
            try:
                if db is not None:
                    if not validate_measurement_schema(db.connection()):
                        raise HTTPException(503, "Historische Quellen sind noch nicht migriert. Datenbankmigration ausführen.")
                    if write:
                        begin_writer(db)
                        if isinstance(auth._user_store, auth.SQLUserStore):
                            auth._user_store._lock_management(db)
                unit = active.get_unit(unit_id)
                prop = active.get_property(unit.property_id)
                active.get_portfolio(prop.portfolio_id)
                if write:
                    lock_measurement_property(active, prop.id)
                    lock_location(active, prop.id, unit.id)
                    unit = active.get_unit(unit_id)
                    if unit.property_id != prop.id:
                        raise conflict("Die Einheit wurde einer anderen Immobilie zugeordnet.")
                if not sql:
                    # Only this unit's new rows are changed; no copied full historical store.
                    before = {"ledger": deepcopy(active.__dict__.get(MEASUREMENT_TABLES[0], {}).get(unit_id))}
                    if write:
                        for name in MEASUREMENT_TABLES:
                            active.__dict__.setdefault(name, {})
                yield active, unit, prop
                _identity(actor_id, write)
                refresh_scope(captured)
                if db is not None and write:
                    # SQL-domain/Memory-auth deployments hold the account mutex at publication.
                    account_lock = getattr(auth._user_store, "_lock", None)
                    with account_lock if account_lock is not None else nullcontext():
                        _identity(actor_id, write)
                        refresh_scope(captured)
                        db.commit()
            except BaseException:
                if db is not None:
                    db.rollback()
                elif before is not None and write:
                    for name, identifier in reversed(inserted):
                        active.__dict__[name].pop(identifier, None)
                    if before["ledger"] is not None:
                        active.__dict__[MEASUREMENT_TABLES[0]][unit_id] = before["ledger"]
                raise
            finally:
                if db is not None:
                    db.close()
                _inserted.reset(marker)


def _rows(store, model):
    return store.__dict__.get(model.__tablename__, {}).values()


def _add(store, row):
    if hasattr(store, "db"):
        store.db.add(row)
        store.db.flush()
    else:
        store.__dict__[row.__tablename__][row.id] = row
        inserted = _inserted.get()
        if inserted is not None:
            inserted.append((row.__tablename__, row.id))


def _current(store, unit_id, *, start=None, end=None):
    if hasattr(store, "db"):
        later = aliased(MeasurementFactORM)
        query = select(MeasurementFactORM).where(MeasurementFactORM.ledger_id == unit_id,
            ~exists(select(later.id).where(later.predecessor_id == MeasurementFactORM.id)))
        if start is not None:
            query = query.where(MeasurementFactORM.valid_until >= start, MeasurementFactORM.valid_from <= end)
        return list(store.db.scalars(query.order_by(MeasurementFactORM.revision, MeasurementFactORM.position)))
    rows = list(_rows(store, MeasurementFactORM))
    obsolete = {row.predecessor_id for row in rows if row.ledger_id == unit_id}
    return sorted((row for row in rows if row.ledger_id == unit_id and row.id not in obsolete
                   and (start is None or row.valid_until >= start and row.valid_from <= end)),
                  key=lambda row: (row.revision, row.position))


def _links(store, facts):
    ids = {row.id for row in facts}
    if not ids:
        return []
    if hasattr(store, "db"):
        ordered = sorted(ids)
        return [row for offset in range(0, len(ordered), 500)
            for row in store.db.scalars(select(MeasurementEvidenceORM).where(MeasurementEvidenceORM.fact_id.in_(ordered[offset:offset + 500])))]
    return [row for row in _rows(store, MeasurementEvidenceORM) if row.fact_id in ids]


def verified_rows(store, facts):
    links = _links(store, facts)
    by_fact: dict[str, list[dict]] = {}
    for link in links:
        by_fact.setdefault(link.fact_id, []).append(payload(link))
    result = []
    for fact in facts:
        row = payload(fact)
        own = by_fact.get(fact.id, [])
        validate_fact(row, own)
        result.append({**row, "evidence": own})
    return result


def _reference(store, unit, prop, data):
    result = dict(meter_id=None, allocation_key_id=None, contract_id=None, tenant_id=None)
    if data.kind == "assignment":
        meter = store.get_meter(data.meter_id)
        if meter.unit_id != unit.id:
            raise HTTPException(404, "Zähler gehört nicht zur ausgewählten Einheit.")
        result["meter_id"] = meter.id
    elif data.kind == "selection":
        key = store.get_allocation_key(data.allocation_key_id)
        if key.property_id != prop.id or key.key_type != data.basis:
            raise HTTPException(400, "Umlageschlüssel und bestätigte Grundlage passen nicht zusammen.")
        result["allocation_key_id"] = key.id
    elif data.kind == "occupancy" and data.contract_id:
        if hasattr(store, "db"):
            store.db.scalar(select(ContractORM.id).where(ContractORM.id == data.contract_id).with_for_update())
        contract = store.get_contract(data.contract_id)
        if contract.unit_id != unit.id or contract.property_id != prop.id:
            raise HTTPException(404, "Vertrag gehört nicht zur ausgewählten Einheit.")
        if (contract.status not in {"active", "terminated", "expired"} or data.valid_from < contract.start_date
                or contract.end_date is not None and data.valid_until > contract.end_date + timedelta(days=1)):
            raise HTTPException(400, "Belegter Zeitraum liegt außerhalb des tatsächlichen Mietvertrags.")
        if hasattr(store, "db"):
            store.db.scalar(select(TenantORM.id).where(TenantORM.id == contract.tenant_id).with_for_update(read=True))
        store.get_tenant(contract.tenant_id)
        result.update(contract_id=contract.id, tenant_id=contract.tenant_id)
    return result


def _document(store, version_id, unit, prop):
    if hasattr(store, "db"):
        row = store.db.get(DocumentVersionORM, version_id)
    else:
        row = store.__dict__.get("document_versions", {}).get(version_id)
    if (row is None or row.portfolio_id != prop.portfolio_id or row.property_id != prop.id
            or row.unit_id not in (None, unit.id)):
        raise HTTPException(404, "Belegoriginal gehört nicht zum zugänglichen Quellenobjekt.")
    return row


def confirm(store, unit_id: str, command: MeasurementCommand, actor_id: str):
    try:
        with work(store, unit_id, actor_id, write=True) as (active, unit, prop):
            request = command.model_dump(mode="json")
            request_hash = digest(request)
            if hasattr(active, "db"):
                prior = active.db.scalar(select(MeasurementCommandORM).where(MeasurementCommandORM.actor_id == actor_id,
                    MeasurementCommandORM.idempotency_key == command.idempotency_key))
                ledger = active.db.get(MeasurementLedgerORM, unit.id)
            else:
                prior = next((row for row in _rows(active, MeasurementCommandORM) if row.actor_id == actor_id and row.idempotency_key == command.idempotency_key), None)
                ledger = active.__dict__[MEASUREMENT_TABLES[0]].get(unit.id)
            if prior is not None:
                if prior.ledger_id != unit.id or prior.request_hash != request_hash:
                    raise conflict("Dieser Wiederholungsschlüssel gehört bereits zu einem anderen Befehl.")
                return dict(prior.result)
            if command.expected_revision != (ledger.revision if ledger else 0):
                raise conflict()
            if ledger is None:
                ledger = MeasurementLedgerORM(id=unit.id, property_id=prop.id, portfolio_id=prop.portfolio_id, revision=0)
                _add(active, ledger)
            current = {row.source_key: row for row in _current(active, unit.id)}
            revision = ledger.revision + 1
            command_id = str(uuid4())
            facts, links = [], []
            for position, change in enumerate(command.changes):
                previous = current.get(change.source_key)
                if change.predecessor_id != (previous.id if previous else None):
                    raise conflict("Die angegebene Vorgängerfassung ist nicht mehr aktuell.")
                if previous and previous.kind != change.data.kind:
                    raise HTTPException(400, "Eine Quellenkorrektur darf den fachlichen Typ nicht austauschen.")
                if change.withdrawn and (previous is None or previous.data != change.data.model_dump(mode="json")):
                    raise HTTPException(400, "Rücknahme muss die vorherige Quelle unverändert benennen.")
                data = change.data
                first = data.boundary_date if data.kind == "reading" else data.valid_from
                last = first if data.kind == "reading" else data.valid_until
                fact = MeasurementFactORM(id=str(uuid4()), ledger_id=unit.id, command_id=command_id,
                    portfolio_id=prop.portfolio_id, property_id=prop.id, source_key=change.source_key,
                    predecessor_id=change.predecessor_id, revision=revision, position=position, kind=data.kind,
                    valid_from=first, valid_until=last, withdrawn=change.withdrawn, reason=change.reason,
                    data=data.model_dump(mode="json"), **_reference(active, unit, prop, data))
                own = []
                for identifier in change.evidence_version_ids:
                    original = _document(active, identifier, unit, prop)
                    own.append(MeasurementEvidenceORM(id=str(uuid4()), fact_id=fact.id,
                        portfolio_id=prop.portfolio_id, version_id=original.id, sha256=original.sha256))
                fact.content_hash = fact_hash(payload(fact), [payload(link) for link in own])
                facts.append(fact)
                links.extend(own)
                current[change.source_key] = fact
            validate_effective([payload(row) for row in current.values()])
            result = {"revision": revision, "fact_ids": [fact.id for fact in facts]}
            _add(active, MeasurementCommandORM(id=command_id, ledger_id=unit.id, portfolio_id=prop.portfolio_id,
                actor_id=actor_id, idempotency_key=command.idempotency_key, revision=revision,
                request_hash=request_hash, request=request, result=result, created_at=datetime.now()))
            for row in (*facts, *links):
                _add(active, row)
            ledger.revision = revision
            return result
    except IntegrityError as error:
        raise conflict("Quellenkonflikt oder veränderte Elternbelege. Aktuellen Stand laden.") from error


def sources(store, unit_id, actor_id, start: date, end: date):
    if end < start:
        raise HTTPException(422, "Ende liegt vor dem Beginn.")
    with work(store, unit_id, actor_id) as (active, unit, _prop):
        ledger = active.db.get(MeasurementLedgerORM, unit.id) if hasattr(active, "db") else active.__dict__.get(MEASUREMENT_TABLES[0], {}).get(unit.id)
        return {"revision": ledger.revision if ledger else 0,
            "facts": verified_rows(active, _current(active, unit.id, start=start, end=end))}


def journal(store, unit_id, actor_id, *, after=0, page_size=50):
    with work(store, unit_id, actor_id) as (active, unit, _prop):
        if hasattr(active, "db"):
            rows = list(active.db.scalars(select(MeasurementCommandORM).where(MeasurementCommandORM.ledger_id == unit.id,
                MeasurementCommandORM.revision > after).order_by(MeasurementCommandORM.revision).limit(page_size + 1)))
        else:
            from heapq import nsmallest
            rows = nsmallest(page_size + 1, (row for row in _rows(active, MeasurementCommandORM)
                if row.ledger_id == unit.id and row.revision > after), key=lambda row: row.revision)
        return {"items": [payload(row) for row in rows[:page_size]],
            "next_after": rows[page_size - 1].revision if len(rows) > page_size else None}


def period_sources(store, period):
    """Period-bounded query; supersession is resolved before date filtering."""
    end = period.end_date + timedelta(days=1)
    if hasattr(store, "db"):
        if not validate_measurement_schema(store.db.connection()):
            return []
        later = aliased(MeasurementFactORM)
        query = select(MeasurementFactORM).where(MeasurementFactORM.property_id == period.property_id,
            MeasurementFactORM.valid_from <= end, MeasurementFactORM.valid_until >= period.start_date,
            ~exists(select(later.id).where(later.predecessor_id == MeasurementFactORM.id)))
        rows = list(store.db.scalars(query))
    else:
        all_rows = list(_rows(store, MeasurementFactORM))
        obsolete = {row.predecessor_id for row in all_rows if row.property_id == period.property_id}
        rows = [row for row in all_rows if row.property_id == period.property_id and row.id not in obsolete
            and row.valid_from <= end and row.valid_until >= period.start_date]
    # An approved span may use original endpoint readings outside this period.
    required = {row.data[key] for row in rows if row.kind == "proration" and not row.withdrawn
                for key in ("start_reading_id", "end_reading_id")}
    required -= {row.id for row in rows}
    if required:
        if hasattr(store, "db"):
            later = aliased(MeasurementFactORM)
            extra = list(store.db.scalars(select(MeasurementFactORM).where(MeasurementFactORM.id.in_(required),
                MeasurementFactORM.property_id == period.property_id,
                ~exists(select(later.id).where(later.predecessor_id == MeasurementFactORM.id)))))
        else:
            extra = [row for row in _rows(store, MeasurementFactORM) if row.id in required and row.property_id == period.property_id and row.id not in obsolete]
        rows.extend(extra)
    return verified_rows(store, sorted(rows, key=lambda row: row.id))


def period_source_hash(store, period):
    return digest([{key: row[key] for key in ("id", "content_hash")} for row in period_sources(store, period)])


def historical_key_ids(store, property_id, key_ids):
    """Once explicitly selected, withdrawal/date correction cannot revive guessing."""
    if not key_ids:
        return set()
    if hasattr(store, "db"):
        if not validate_measurement_schema(store.db.connection()):
            return set()
        return set(store.db.scalars(select(MeasurementFactORM.allocation_key_id).where(
            MeasurementFactORM.property_id == property_id, MeasurementFactORM.kind == "selection",
            MeasurementFactORM.allocation_key_id.in_(key_ids)).distinct()))
    return {row.allocation_key_id for row in _rows(store, MeasurementFactORM)
        if row.property_id == property_id and row.kind == "selection" and row.allocation_key_id in key_ids}


def property_units(store, property_id):
    if not hasattr(store, "db"):
        return [unit for unit in store.list_units() if unit.property_id == property_id]
    from ..db.orm_models import UnitORM
    from ..models import Unit
    return [Unit.model_validate(payload(row)) for row in store.db.scalars(select(UnitORM).where(UnitORM.property_id == property_id))]


def legacy_meter_sources(store, period):
    if not hasattr(store, "db"):
        ids = {unit.id for unit in property_units(store, period.property_id)}
        meters = [row for row in store.list_meters() if row.unit_id in ids]
        selected = {meter.id for meter in meters}
        return meters, [row for row in store.list_standalone_meter_readings() if row.meter_id in selected and period.start_date <= row.reading_date <= period.end_date]
    from ..db.orm_models import MeterORM, StandaloneMeterReadingORM, UnitORM
    from ..models import Meter, StandaloneMeterReading
    selected_meters = select(MeterORM).join(UnitORM, UnitORM.id == MeterORM.unit_id).where(UnitORM.property_id == period.property_id)
    readings = select(StandaloneMeterReadingORM).join(MeterORM, MeterORM.id == StandaloneMeterReadingORM.meter_id).join(
        UnitORM, UnitORM.id == MeterORM.unit_id).where(UnitORM.property_id == period.property_id,
        StandaloneMeterReadingORM.reading_date >= period.start_date, StandaloneMeterReadingORM.reading_date <= period.end_date)
    return ([Meter.model_validate(payload(row)) for row in store.db.scalars(selected_meters)],
        [StandaloneMeterReading.model_validate(payload(row)) for row in store.db.scalars(readings)])
