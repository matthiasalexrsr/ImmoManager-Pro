"""Bounded source reads; production snapshots use database revision triggers."""
import hashlib
import heapq
import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased

from ..db.booking_order import bytewise_id
from ..db.orm_models import ContractORM, PropertyORM, RentAdjustmentORM, UnitORM
from ..db.rent_batch_models import RentBatchContractORM, RentBatchSelectionORM, RentSourceRevisionORM
from .portfolio_scope import scope_context, scoped_clause


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
        separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()


def cents(value):
    return int(Decimal(str(value or 0)).quantize(Decimal("0.01")) * 100)


def utc_naive(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def fields(contract, unit, property_item):
    return dict(contract_id=contract.id, contract_number=contract.contract_number,
        property_id=contract.property_id, portfolio_id=property_item.portfolio_id,
        unit_id=contract.unit_id, tenant_id=contract.tenant_id, status=contract.status,
        start_date=contract.start_date, end_date=contract.end_date, cold_cents=cents(unit.cold_rent),
        service_cents=cents(unit.service_charge_advance), heating_cents=cents(unit.heating_advance))


def source_statement(job, after=None, *, scope=None):
    revisions = [aliased(RentSourceRevisionORM) for _ in range(4)]
    stmt = select(ContractORM, UnitORM, PropertyORM, *[func.coalesce(r.revision, 0) for r in revisions]).join(
        UnitORM, UnitORM.id == ContractORM.unit_id).join(PropertyORM, PropertyORM.id == ContractORM.property_id)
    for revision, kind, identifier in zip(revisions, ("contract", "unit", "prices", "property"),
            (ContractORM.id, UnitORM.id, ContractORM.id, PropertyORM.id), strict=True):
        stmt = stmt.outerjoin(revision, and_(revision.entity_type == kind, revision.entity_id == identifier))
    cutoff = datetime.fromisoformat(job.preparation.get("source_cutoff", job.created_at.isoformat()))
    stmt = stmt.where(ContractORM.created_at <= cutoff)
    clause = scoped_clause(ContractORM, scope=scope)
    if clause is not None:
        stmt = stmt.where(clause)
    if job.parameters.get("contract_ids"):
        stmt = stmt.join(RentBatchSelectionORM, and_(RentBatchSelectionORM.batch_id == job.id,
            RentBatchSelectionORM.contract_id == ContractORM.id))
    else:
        stmt = stmt.where(ContractORM.status == "active")
    if after is not None:
        stmt = stmt.where(bytewise_id(ContractORM.id) > after)
    return stmt.order_by(bytewise_id(ContractORM.id))


def source_rows(store, db, job, after, limit, *, scope=None):
    if hasattr(store, "db"):
        rows = db.execute(source_statement(job, after, scope=scope).limit(limit))
        for contract, unit, prop, *versions in rows:
            value = fields(contract, unit, prop)
            yield {**value, **dict(zip(("contract_revision", "unit_revision", "price_revision", "property_revision"), versions, strict=True)),
                "basis_hash": digest(value)}
        return
    with scope_context(scope):
        selected = set(job.parameters.get("contract_ids") or ())
        # Memory reference scans its collection but materializes only one bounded page.
        rows = heapq.nsmallest(limit, (c for c in store.contracts.values()
            if (not selected and c.status == "active" or c.id in selected)
            and utc_naive(c.created_at) <= job.created_at and (after is None or c.id > after)), key=lambda c: c.id)
        for contract in rows:
            unit, prop = store.get_unit(contract.unit_id), store.get_property(contract.property_id)
            value = fields(contract, unit, prop)
            versions = memory_versions(store, contract.id, contract.unit_id, contract.property_id)
            yield {**value, **versions, "basis_hash": digest(value)}


def memory_versions(store, contract_id, unit_id, property_id):
    contract, unit, prop = store.contracts.get(contract_id), store.units.get(unit_id), store.properties.get(property_id)
    prices = 0
    for row in store.rent_adjustments.values():
        if row.contract_id == contract_id:
            prices ^= int(digest((row.id, row.contract_id, row.status, row.effective_date, row.previous_rent, row.new_rent)), 16)
    def number(value):
        return int(digest(value)[:15], 16)
    return {"contract_revision": number(None if contract is None else tuple(getattr(contract, k)
                for k in ("id", "contract_number", "property_id", "unit_id", "tenant_id", "status", "start_date", "end_date"))),
        "unit_revision": number(None if unit is None else (unit.id, unit.property_id, unit.cold_rent, unit.service_charge_advance, unit.heating_advance)),
        "price_revision": prices & ((1 << 60) - 1),
        "property_revision": number(None if prop is None else (prop.id, prop.portfolio_id))}


def changed_source(store, db, job, *, after_seal=False, contract_ids=None):
    frozen = RentBatchContractORM
    if not hasattr(store, "db"):
        memory_stmt = select(frozen).where(frozen.batch_id == job.id)
        if contract_ids is not None:
            memory_stmt = memory_stmt.where(frozen.contract_id.in_(contract_ids))
        for row in db.scalars(memory_stmt.execution_options(yield_per=100)):
            versions = memory_versions(store, row.contract_id, row.unit_id, row.property_id)
            keys = ("contract_revision", "property_revision") if after_seal else tuple(versions)
            if any(getattr(row, key) != versions[key] for key in keys):
                return True
        return False
    revisions = [aliased(RentSourceRevisionORM) for _ in range(4)]
    stmt = select(frozen.contract_id).where(frozen.batch_id == job.id)
    if contract_ids is not None:
        stmt = stmt.where(frozen.contract_id.in_(contract_ids))
    clauses = []
    for revision, kind, identifier, field in zip(revisions, ("contract", "unit", "prices", "property"),
            (frozen.contract_id, frozen.unit_id, frozen.contract_id, frozen.property_id),
            (frozen.contract_revision, frozen.unit_revision, frozen.price_revision, frozen.property_revision), strict=True):
        if after_seal and kind in {"unit", "prices"}:
            continue  # The confirmed price basis is deliberately immutable.
        stmt = stmt.outerjoin(revision, and_(revision.entity_type == kind, revision.entity_id == identifier))
        clauses.append(func.coalesce(revision.revision, 0) != field)
    return db.execute(stmt.where(or_(*clauses)).limit(1)).first() is not None


def price_rows(store, db, contract_id, after, limit):
    if hasattr(store, "db"):
        stmt = select(RentAdjustmentORM).where(RentAdjustmentORM.contract_id == contract_id,
            RentAdjustmentORM.status == "applied").order_by(bytewise_id(RentAdjustmentORM.id)).limit(limit)
        if after is not None:
            stmt = stmt.where(bytewise_id(RentAdjustmentORM.id) > after)
        rows = db.scalars(stmt)
    else:
        rows = heapq.nsmallest(limit, (p for p in store.rent_adjustments.values()
            if p.contract_id == contract_id and p.status == "applied" and (after is None or p.id > after)), key=lambda p: p.id)
    for row in rows:
        value = dict(adjustment_id=row.id, contract_id=contract_id, effective_date=row.effective_date,
            previous_cents=cents(row.previous_rent), new_cents=cents(row.new_rent))
        yield {**value, "source_hash": digest(value)}
