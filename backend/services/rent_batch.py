"""Durable rental batches: bounded snapshots, explicit confirmation, atomic progress.

SQL is persistent. The explicitly nonpersistent memory backend uses a private
SQLite journal only for its reference workflow; it never claims restart durability.
"""
import base64
import hashlib
import hmac
import json
from contextlib import contextmanager, nullcontext
from dataclasses import asdict
from datetime import datetime, timezone
from typing import cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import (
    Date,
    String,
    Table,
    and_,
    column,
    create_engine,
    delete,
    exists,
    insert,
    or_,
    select,
    update,
    values,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ..config import settings
from ..db.booking_order import bytewise_id
from ..db.orm_models import ContractORM, RentAdjustmentORM, RentChargeORM, UnitORM
from ..db.rent_batch_models import (
    RENT_BATCH_TABLES,
    RentBatchContractORM,
    RentBatchORM,
    RentBatchPriceORM,
    RentBatchResultORM,
    RentBatchSelectionORM,
)
from ..models import RentChargeCreate
from .payments import _memory_lock
from .portfolio_scope import refresh_scope, scope_context, scoped_clause
from .rent_batch_planner import Contract, Cursor, Plan, load_cursor, month_index, plan_tick
from .rent_batch_sources import cents, changed_source, digest, price_rows, source_rows, source_statement


class BatchError(ValueError):
    def __init__(self, code, message, recovery="refresh_batch", status=409):
        super().__init__(message)
        self.code, self.recovery, self.status = code, recovery, status

    @property
    def detail(self):
        return {"clear_code": self.code, "message": str(self), "recovery": self.recovery}


class BatchParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_month: str
    end_month: str
    contract_ids: list[str] | None = None

    @model_validator(mode="after")
    def validate_parameters(self):
        if month_index(self.start_month) > month_index(self.end_month):
            raise ValueError("Der Endmonat darf nicht vor dem Startmonat liegen.")
        if self.contract_ids is not None:
            if not self.contract_ids or len(set(self.contract_ids)) != len(self.contract_ids):
                raise ValueError("Vertragsauswahl muss eindeutig und nicht leer sein.")
            if any(not x or len(x) > 100 or x != x.strip() or any(ord(c) < 32 for c in x) for x in self.contract_ids):
                raise ValueError("Ungültige Vertragskennung.")
            self.contract_ids = sorted(self.contract_ids)
        return self


class BatchCreate(BatchParameters):
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")


class BatchAdvance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cursor: str = Field(min_length=1, max_length=4096)
    budget: int = Field(default=100, ge=1, le=5000, strict=True)


class BatchConfirm(BatchAdvance):
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def batch_max_size():
    result = getattr(settings, "rent_batch_max_size", 500)
    if type(result) is not int or not 25 <= result <= 5000:
        raise RuntimeError("RENT_BATCH_MAX_SIZE must be from 25 through 5000")
    return result


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _source_clock(store, db):
    if not hasattr(store, "db"):
        return _now().isoformat()
    from sqlalchemy import func
    # Existing source columns are timestamp-without-time-zone and use the DB
    # wall clock. Do not compare that to a Python UTC clock on non-UTC PG servers.
    return db.scalar(select(func.current_timestamp())).replace(tzinfo=None).isoformat()


def _pack(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    signature = hmac.new(settings.jwt_secret_key.encode(), b"immo-rent-batch-v1\0" + payload, hashlib.sha256).digest()
    return ".".join(base64.urlsafe_b64encode(v).decode().rstrip("=") for v in (payload, signature))


def _unpack(raw):
    try:
        a, b = raw.split(".")
        payload, signature = (base64.b64decode(x + "=" * (-len(x) % 4), altchars=b"-_", validate=True) for x in (a, b))
        value = json.loads(payload)
        if not isinstance(value, dict) or _pack(value) != raw or not hmac.compare_digest(signature,
                hmac.new(settings.jwt_secret_key.encode(), b"immo-rent-batch-v1\0" + payload, hashlib.sha256).digest()):
            raise ValueError
        return value
    except (ValueError, TypeError, KeyError) as exc:
        raise BatchError("RENT_CURSOR_INVALID", "Fortschrittstoken ungültig. Gespeicherten Stand neu laden.", status=400) from exc


def _binding(job):
    return dict(v=1, purpose="advance", id=job.id, revision=job.revision, state=job.state, phase=job.phase, plan_hash=job.plan_hash)


def summary(job, persistent):
    return dict(id=job.id, state=job.state, phase=job.phase, revision=job.revision,
        cursor=_pack(_binding(job)), parameters=job.parameters, plan_hash=job.plan_hash,
        snapshot_hash=job.snapshot_hash, contract_count=job.contract_count, price_count=job.price_count,
        examined_count=job.examined_count, created_count=job.created_count, existing_count=job.existing_count,
        created_at=job.created_at.isoformat(), sealed_at=job.sealed_at.isoformat() if job.sealed_at else None,
        confirmed_at=job.confirmed_at.isoformat() if job.confirmed_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None, persistent=persistent,
        policy="full_month", last_error=job.last_error, maximum_step_size=batch_max_size())


@contextmanager
def journal(store):
    sql = hasattr(store, "db")
    with nullcontext() if sql else _memory_lock:
        if not sql and not hasattr(store, "_rent_batch_engine"):
            store._rent_batch_engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
            with store._rent_batch_engine.begin() as connection:
                for table in RENT_BATCH_TABLES:
                    cast(Table, table).create(connection, checkfirst=True)
        db = store.db if sql else Session(store._rent_batch_engine)
        if not sql:
            db.info["rent_batch_memory_store"] = store
        # Batch metadata is creator-bound here. Source reads apply the captured
        # scope explicitly; generic resource hooks must not hide journal rows.
        with scope_context(None):
            try:
                yield db
            except Exception:
                db.rollback()
                raise
            finally:
                if not sql:
                    db.close()


def _guard(scope):
    return refresh_scope(scope)


def _load(db, batch_id, actor_id, scope):
    _guard(scope)
    job = db.get(RentBatchORM, batch_id, populate_existing=True)
    if not job or job.creator_id != actor_id:
        raise BatchError("RENT_BATCH_NOT_FOUND", "Gespeicherter Lauf nicht gefunden.", status=404)
    stored = job.scope_snapshot
    if stored != (asdict(scope) if scope is not None else None):
        # JSON stores tuples as lists; normalize before comparison.
        if digest(stored) != digest(asdict(scope) if scope is not None else None):
            raise BatchError("RENT_SCOPE_CHANGED", "Bestandsberechtigungen haben sich geändert. Neuen Lauf vorbereiten.", "create_new_batch", 403)
    if scope is not None and not scope.unrestricted:
        for model in (RentBatchSelectionORM, RentBatchContractORM):
            visible = select(ContractORM.id).where(ContractORM.id == model.contract_id,
                scoped_clause(ContractORM, scope=scope))
            memory_store = db.info.get("rent_batch_memory_store")
            if memory_store is None:
                missing = db.execute(select(model.contract_id).where(model.batch_id == job.id, ~exists(visible)).limit(1)).first()
                if missing:
                    raise BatchError("RENT_SCOPE_CHANGED", "Ein ausgewählter Bestand ist nicht mehr zugänglich. Neue Auswahl prüfen.", "create_new_batch", 403)
            else:
                identifiers = db.scalars(select(model.contract_id).where(model.batch_id == job.id).execution_options(yield_per=100))
                for identifier in identifiers:
                    with scope_context(scope):
                        if identifier not in memory_store.contracts:
                            raise BatchError("RENT_SCOPE_CHANGED", "Ein ausgewählter Bestand ist nicht mehr zugänglich.", "create_new_batch", 403)
    return job


def _claim(db, job, raw):
    if _unpack(raw) != _binding(job):
        raise BatchError("RENT_CURSOR_STALE", "Der Lauf wurde bereits weitergeführt. Gespeicherten Stand neu laden.")
    result = db.execute(update(RentBatchORM).where(RentBatchORM.id == job.id,
        RentBatchORM.revision == job.revision).values(revision=RentBatchORM.revision + 1), execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        raise BatchError("RENT_CURSOR_STALE", "Ein anderer Prozess hat diesen Schritt bereits bearbeitet.")
    db.refresh(job)


def create_batch(store, payload, *, actor_id="internal", scope=None):
    _guard(scope)
    params = BatchParameters(**payload.model_dump(exclude={"idempotency_key"})).model_dump(mode="json")
    with journal(store) as db:
        known = db.scalar(select(RentBatchORM).where(RentBatchORM.creator_id == actor_id,
            RentBatchORM.idempotency_key == payload.idempotency_key))
        if known:
            if known.parameters != params:
                raise BatchError("RENT_IDEMPOTENCY_CONFLICT", "Dieselbe Wiederholungskennung gehört zu einer anderen Auswahl.", "create_new_batch")
            return summary(_load(db, known.id, actor_id, scope), hasattr(store, "db"))
        job = RentBatchORM(id=str(uuid4()), creator_id=actor_id, idempotency_key=payload.idempotency_key,
            parameters=params, scope_snapshot=asdict(scope) if scope is not None else None,
            preparation={"after": None, "price_contract": None, "price_after": None, "digest": digest("rent-snapshot-v1"),
                "source_cutoff": _source_clock(store, db)}, created_at=_now())
        db.add(job)
        try:
            db.flush()
            selected = params["contract_ids"] or []
            for offset in range(0, len(selected), 250):
                db.execute(insert(RentBatchSelectionORM), [{"batch_id": job.id, "contract_id": x} for x in selected[offset:offset + 250]])
            if selected:
                if hasattr(store, "db"):
                    visible = select(ContractORM.id).where(ContractORM.id == RentBatchSelectionORM.contract_id)
                    clause = scoped_clause(ContractORM, scope=scope)
                    if clause is not None:
                        visible = visible.where(clause)
                    missing = db.scalar(select(RentBatchSelectionORM.contract_id).where(RentBatchSelectionORM.batch_id == job.id,
                        ~exists(visible)).limit(1))
                else:
                    with scope_context(scope):
                        missing = next((x for x in selected if x not in store.contracts), None)
                if missing:
                    raise BatchError("RENT_CONTRACT_NOT_FOUND", "Ein ausgewählter Vertrag ist nicht mehr zugänglich.", "change_selection", 400)
            db.commit()
        except IntegrityError:
            db.rollback()
            known = db.scalar(select(RentBatchORM).where(RentBatchORM.creator_id == actor_id,
                RentBatchORM.idempotency_key == payload.idempotency_key))
            if known and known.parameters == params:
                return summary(_load(db, known.id, actor_id, scope), hasattr(store, "db"))
            raise BatchError("RENT_IDEMPOTENCY_CONFLICT", "Wiederholungskennung wurde gleichzeitig anders verwendet.", "create_new_batch") from None
        return summary(job, hasattr(store, "db"))


def get_batch(store, batch_id, *, actor_id="internal", scope=None):
    with journal(store) as db:
        return summary(_load(db, batch_id, actor_id, scope), hasattr(store, "db"))


def list_batches(store, *, actor_id="internal", scope=None, cursor=None, page_size=25):
    _guard(scope)
    if not 1 <= page_size <= batch_max_size():
        raise BatchError("RENT_BUDGET_TOO_LARGE", "Kleinere Liste wählen.", "reduce_budget", 400)
    binding = dict(v=1, purpose="list", actor_id=actor_id, scope=digest(asdict(scope) if scope else None), page_size=page_size)
    with journal(store) as db:
        stmt = select(RentBatchORM).where(RentBatchORM.creator_id == actor_id).order_by(
            RentBatchORM.created_at.desc(), bytewise_id(RentBatchORM.id).desc()).limit(page_size + 1)
        if cursor:
            value = _unpack(cursor)
            if set(value) != {*binding, "after", "id"} or any(value.get(k) != v for k, v in binding.items()):
                raise BatchError("RENT_LIST_CURSOR_INVALID", "Listenauswahl geändert. Erste Seite laden.", "restart_list", 400)
            after = datetime.fromisoformat(value["after"])
            stmt = stmt.where(or_(RentBatchORM.created_at < after,
                and_(RentBatchORM.created_at == after, bytewise_id(RentBatchORM.id) < value["id"])))
        rows = list(db.scalars(stmt))
        visible = rows[:page_size]
        # No old parameters, price/contract counts or source data are disclosed
        # when the actor's portfolio access no longer matches that frozen plan.
        items = [dict(id=r.id, created_at=r.created_at.isoformat(), state=r.state,
            available=digest(r.scope_snapshot) == binding["scope"]) for r in visible]
        next_cursor = _pack({**binding, "after": visible[-1].created_at.isoformat(), "id": visible[-1].id}) if len(rows) > page_size else None
        return {"items": items, "next_cursor": next_cursor, "has_more": next_cursor is not None}


def _plan(job):
    return Plan(job.parameters["start_month"], job.parameters["end_month"], job.parameters["end_month"], job.snapshot_hash)


def _planner_source(db, job, limit):
    def source(snapshot_hash, after, inclusive):
        if snapshot_hash != job.snapshot_hash:
            raise BatchError("RENT_PLAN_CHANGED", "Preisstand stimmt nicht mit dem Plan überein.")
        stmt = select(RentBatchContractORM).where(RentBatchContractORM.batch_id == job.id).order_by(
            bytewise_id(RentBatchContractORM.contract_id)).limit(limit)
        if after is not None:
            identifier = bytewise_id(RentBatchContractORM.contract_id)
            stmt = stmt.where(identifier >= after if inclusive else identifier > after)
        for row in db.scalars(stmt):
            yield Contract(row.contract_id, row.start_date, row.end_date, row.status, row.property_id,
                row.unit_id, digest((row.basis_hash, row.price_digest)))
    return source


def _prepare(store, db, job, budget, scope):
    progress = dict(job.preparation)
    if job.phase == "contracts":
        rows = list(source_rows(store, db, job, progress["after"], budget + 1, scope=scope))
        for row in rows[:budget]:
            db.add(RentBatchContractORM(batch_id=job.id, price_digest=digest("rent-prices-v1"), **row))
        job.contract_count += len(rows[:budget])
        if rows[:budget]:
            progress["after"] = rows[:budget][-1]["contract_id"]
        if len(rows) <= budget:
            job.phase = "prices"
            progress["after"] = None
    elif job.phase == "prices":
        if hasattr(store, "db"):
            _prepare_sql_prices(db, job, progress, budget)
            job.preparation = progress
            return
        row = db.scalar(select(RentBatchContractORM).where(RentBatchContractORM.batch_id == job.id,
            RentBatchContractORM.prices_complete.is_(False)).order_by(bytewise_id(RentBatchContractORM.contract_id)).limit(1))
        if row is None:
            job.phase = "seal"
            progress["after"] = None
        else:
            if progress["price_contract"] != row.contract_id:
                progress["price_contract"], progress["price_after"] = row.contract_id, None
            prices = list(price_rows(store, db, row.contract_id, progress["price_after"], budget + 1))
            for price in prices[:budget]:
                db.add(RentBatchPriceORM(batch_id=job.id, **price))
                row.price_digest = digest((row.price_digest, price["source_hash"]))
            job.price_count += len(prices[:budget])
            if prices[:budget]:
                progress["price_after"] = prices[:budget][-1]["adjustment_id"]
            if len(prices) <= budget:
                row.prices_complete = True
    else:
        stmt = select(RentBatchContractORM).where(RentBatchContractORM.batch_id == job.id).order_by(
            bytewise_id(RentBatchContractORM.contract_id)).limit(budget + 1)
        if progress["after"] is not None:
            stmt = stmt.where(bytewise_id(RentBatchContractORM.contract_id) > progress["after"])
        rows = list(db.scalars(stmt))
        for row in rows[:budget]:
            progress["digest"] = digest((progress["digest"], row.contract_id, row.basis_hash, row.price_digest))
        if rows[:budget]:
            progress["after"] = rows[:budget][-1].contract_id
        if len(rows) <= budget:
            if changed_source(store, db, job):
                raise BatchError("RENT_SOURCE_CHANGED", "Verträge oder Preise wurden während der Vorbereitung geändert. Vorbereitung neu starten.", "restart_preparation")
            if hasattr(store, "db"):
                missing = source_statement(job, scope=scope).outerjoin(RentBatchContractORM,
                    and_(RentBatchContractORM.batch_id == job.id, RentBatchContractORM.contract_id == ContractORM.id)).where(
                    RentBatchContractORM.contract_id.is_(None)).limit(1)
                if db.execute(missing).first():
                    raise BatchError("RENT_SOURCE_CHANGED", "Die Vertragsauswahl wurde geändert. Vorbereitung neu starten.", "restart_preparation")
            else:
                # Bounded pages, constant memory. SQL production uses a single EXISTS.
                after = None
                while rows := list(source_rows(store, db, job, after, budget, scope=scope)):
                    if any(db.get(RentBatchContractORM, (job.id, row["contract_id"])) is None for row in rows):
                        raise BatchError("RENT_SOURCE_CHANGED", "Die Vertragsauswahl wurde geändert.", "restart_preparation")
                    after = rows[-1]["contract_id"]
            job.snapshot_hash = progress["digest"]
            job.plan_hash = _plan(job).fingerprint
            job.planner_cursor = Cursor(job.plan_hash).dump()
            job.state, job.sealed_at = "ready", _now()
    job.preparation = progress


def _prepare_sql_prices(db, job, progress, budget):
    """One bounded LEFT JOIN; empty price histories consume one contract probe."""
    frozen, price = RentBatchContractORM, RentAdjustmentORM
    stmt = select(frozen, price).outerjoin(price, and_(price.contract_id == frozen.contract_id, price.status == "applied")).where(
        frozen.batch_id == job.id, frozen.prices_complete.is_(False)).order_by(
        bytewise_id(frozen.contract_id), bytewise_id(price.id)).limit(budget + 1)
    if progress["price_contract"] is not None and progress["price_after"] is not None:
        stmt = stmt.where(or_(bytewise_id(frozen.contract_id) > progress["price_contract"],
            and_(frozen.contract_id == progress["price_contract"], bytewise_id(price.id) > progress["price_after"])))
    rows = list(db.execute(stmt))
    previous = progress["price_contract"]
    if previous is not None and (not rows or rows[0][0].contract_id != previous):
        row = db.get(frozen, (job.id, previous))
        row.prices_complete = True
    for index, (row, adjustment) in enumerate(rows[:budget]):
        if adjustment is not None:
            value = dict(adjustment_id=adjustment.id, contract_id=row.contract_id, effective_date=adjustment.effective_date,
                previous_cents=cents(adjustment.previous_rent), new_cents=cents(adjustment.new_rent))
            value["source_hash"] = digest(value)
            db.add(RentBatchPriceORM(batch_id=job.id, **value))
            row.price_digest = digest((row.price_digest, value["source_hash"]))
            job.price_count += 1
        following = rows[index + 1] if index + 1 < len(rows) else None
        complete = following is None or following[0].contract_id != row.contract_id
        row.prices_complete = complete
        progress["price_contract"] = None if complete else row.contract_id
        progress["price_after"] = None if complete or adjustment is None else adjustment.id
    if len(rows) <= budget:
        job.phase = "seal"
        progress["after"] = None


def _priced_targets(db, job, targets):
    if not targets:
        return []
    table = values(column("contract_id", String), column("month", String), column("month_start", Date)).data(
        [(t.contract_id, t.month, datetime.strptime(t.month + "-01", "%Y-%m-%d").date()) for t in targets]).cte("rent_targets")
    price = RentBatchPriceORM
    applied = select(price.new_cents).where(price.batch_id == job.id, price.contract_id == table.c.contract_id,
        price.effective_date <= table.c.month_start).order_by(price.effective_date.desc()).limit(1).correlate(table).scalar_subquery()
    baseline = select(price.previous_cents).where(price.batch_id == job.id, price.contract_id == table.c.contract_id).order_by(
        price.effective_date).limit(1).correlate(table).scalar_subquery()
    from sqlalchemy import func
    frozen = RentBatchContractORM
    stmt = select(table.c.contract_id, table.c.month, func.coalesce(applied, baseline, frozen.cold_cents).label("cold_cents"),
        frozen.service_cents, frozen.heating_cents, frozen.contract_number, frozen.unit_id, frozen.property_id).join(frozen,
        and_(frozen.batch_id == job.id, frozen.contract_id == table.c.contract_id))
    return [dict(row._mapping) for row in db.execute(stmt)]


def _generate(store, db, job, budget, scope):
    plan = _plan(job)
    batch = plan_tick(plan, load_cursor(plan, job.planner_cursor), _planner_source(db, job, budget), lambda *_: False, batch_size=budget)
    identifiers = sorted({target.contract_id for target in batch.targets})
    if identifiers and hasattr(store, "db"):
        # Per-contract DML locks, one bounded statement. A term/unit switch
        # cannot race this batch's validation+charge insert on PostgreSQL.
        lock = update(ContractORM).where(ContractORM.id.in_(identifiers)).values(updated_at=ContractORM.updated_at).returning(ContractORM.id)
        clause = scoped_clause(ContractORM, scope=scope)
        if clause is not None:
            lock = lock.where(clause)
        if set(db.scalars(lock)) != set(identifiers):
            raise BatchError("RENT_SOURCE_CHANGED", "Ein Vertrag wurde entfernt oder ist nicht mehr zugänglich.", "create_new_batch")
    if identifiers and changed_source(store, db, job, after_seal=True, contract_ids=identifiers):
        raise BatchError("RENT_SOURCE_CHANGED", "Vertragsdaten wurden seit Freigabe geändert. Neuen Lauf prüfen; vorhandene Forderungen bleiben erhalten.", "create_new_batch")
    priced = { (row["contract_id"], row["month"]): row for row in _priced_targets(db, job, batch.targets) }
    added_memory = []
    try:
        sql_receipts = {}
        if hasattr(store, "db") and priced:
            expected_units = {(row["unit_id"], row["property_id"]) for row in priced.values()}
            unit_lock = update(UnitORM).where(UnitORM.id.in_(sorted({x[0] for x in expected_units}))).values(
                updated_at=UnitORM.updated_at).returning(UnitORM.id, UnitORM.property_id)
            if set(db.execute(unit_lock)) != expected_units:
                raise BatchError("RENT_SOURCE_CHANGED", "Eine Einheit wurde entfernt oder einer anderen Immobilie zugeordnet.", "create_new_batch")
            from sqlalchemy import tuple_
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            factory = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
            payloads = [dict(id=str(uuid4()), contract_id=r["contract_id"], month=r["month"], cold_rent=r["cold_cents"] / 100,
                service_charge=r["service_cents"] / 100, heating_charge=r["heating_cents"] / 100,
                other_charges=0, amount_paid=0, status="open") for r in priced.values()]
            created_receipts = {}
            # Bound SQL parameter counts independently of the configurable work
            # budget, including SQLite builds with a 32766-variable limit.
            for offset in range(0, len(payloads), 1000):
                rows = db.execute(factory(RentChargeORM).values(payloads[offset:offset + 1000]).on_conflict_do_nothing(
                    index_elements=["contract_id", "month"]).returning(RentChargeORM.contract_id, RentChargeORM.month, RentChargeORM.id))
                created_receipts.update({(r[0], r[1]): r[2] for r in rows})
            existing = {(r[0], r[1]): r[2] for r in db.execute(select(RentChargeORM.contract_id, RentChargeORM.month, RentChargeORM.id).where(
                tuple_(RentChargeORM.contract_id, RentChargeORM.month).in_(list(priced))))}
            sql_receipts = {key: (identifier, key in created_receipts) for key, identifier in existing.items()}
        for target in batch.targets:
            row = priced[target.key]
            charge_id, created = str(uuid4()), False
            data = dict(contract_id=target.contract_id, month=target.month, cold_rent=row["cold_cents"] / 100,
                service_charge=row["service_cents"] / 100, heating_charge=row["heating_cents"] / 100,
                other_charges=0, amount_paid=0, status="open")
            if hasattr(store, "db"):
                charge_id, created = sql_receipts[target.key]
            else:
                known = next((r for r in store.rent_charges.values() if (r.contract_id, r.month) == target.key), None)
                if known:
                    charge_id = known.id
                else:
                    created_charge = store.create_rent_charge(RentChargeCreate(**data))
                    charge_id, created = created_charge.id, True
                    added_memory.append(charge_id)
            db.add(RentBatchResultORM(batch_id=job.id, contract_id=target.contract_id, month=target.month,
                charge_id=charge_id, was_created=created, basis_revision=target.basis_revision))
            job.created_count += int(created)
            job.existing_count += int(not created)
        job.examined_count += batch.examined
        job.planner_cursor = batch.next_cursor.dump()
        if batch.next_cursor.done:
            job.state, job.completed_at = "done", _now()
        db.flush()
        return added_memory
    except Exception:
        for charge_id in added_memory:
            store.rent_charges.pop(charge_id, None)
        raise


def advance_batch(store, batch_id, payload, *, actor_id="internal", scope=None):
    if payload.budget > batch_max_size():
        raise BatchError("RENT_BUDGET_TOO_LARGE", "Kleinere technische Schrittgröße wählen; der gesamte Lauf bleibt unbegrenzt.", "reduce_budget", 400)
    with journal(store) as db:
        job = _load(db, batch_id, actor_id, scope)
        if job.state not in {"preparing", "running"}:
            raise BatchError("RENT_BATCH_NOT_RUNNING", "Lauf zuerst fortsetzen oder den geprüften Preisstand freigeben.")
        _claim(db, job, payload.cursor)
        added = []
        try:
            if job.state == "preparing":
                _prepare(store, db, job, payload.budget, scope)
            else:
                added = _generate(store, db, job, payload.budget, scope)
            _guard(scope)
            db.commit()
        except Exception:
            for identifier in added:
                store.rent_charges.pop(identifier, None)
            raise
        return summary(job, hasattr(store, "db"))


def control_batch(store, batch_id, payload, action, *, actor_id="internal", scope=None):
    with journal(store) as db:
        job = _load(db, batch_id, actor_id, scope)
        _claim(db, job, payload.cursor)
        if action == "confirm":
            if job.state != "ready" or payload.plan_hash != job.plan_hash:
                raise BatchError("RENT_PLAN_CHANGED", "Gespeicherten Preisstand erneut prüfen.")
            job.state, job.confirmed_at = "running", _now()
        elif action == "pause":
            if job.state not in {"preparing", "running"}:
                raise BatchError("RENT_BATCH_NOT_RUNNING", "Dieser Lauf läuft nicht.")
            job.preparation = {**job.preparation, "resume_state": job.state}
            job.state = "paused"
        elif action == "resume":
            if job.state != "paused":
                raise BatchError("RENT_BATCH_NOT_PAUSED", "Dieser Lauf ist nicht pausiert.")
            job.state = job.preparation["resume_state"]
        elif action == "restart":
            if job.created_count or job.existing_count:
                raise BatchError("RENT_BATCH_ALREADY_COMMITTED", "Ein teilweise gebuchter Lauf behält seinen Preisstand. Neuen Lauf prüfen.", "create_new_batch")
            for model in (RentBatchResultORM, RentBatchPriceORM, RentBatchContractORM):
                db.execute(delete(model).where(model.batch_id == job.id))
            job.state, job.phase = "preparing", "contracts"
            job.created_at, job.sealed_at, job.confirmed_at, job.completed_at = _now(), None, None, None
            job.plan_hash, job.snapshot_hash, job.planner_cursor = None, None, None
            job.contract_count, job.price_count, job.examined_count = 0, 0, 0
            job.preparation = {"after": None, "price_contract": None, "price_after": None, "digest": digest("rent-snapshot-v1"),
                "source_cutoff": _source_clock(store, db)}
        else:
            raise ValueError("Unknown rental batch action")
        _guard(scope)
        db.commit()
        return summary(job, hasattr(store, "db"))


def preview_batch(store, batch_id, *, cursor=None, page_size=100, actor_id="internal", scope=None):
    if not 1 <= page_size <= batch_max_size():
        raise BatchError("RENT_BUDGET_TOO_LARGE", "Kleinere Vorschauseite wählen.", "reduce_budget", 400)
    with journal(store) as db:
        job = _load(db, batch_id, actor_id, scope)
        if not job.plan_hash:
            raise BatchError("RENT_BATCH_NOT_READY", "Vorbereitung zuerst abschließen.")
        plan = _plan(job)
        position = Cursor(plan.fingerprint)
        if cursor:
            value = _unpack(cursor)
            if set(value) != {"v", "purpose", "id", "plan_hash", "cursor", "page_size"} or value != {
                    "v": 1, "purpose": "preview", "id": job.id, "plan_hash": job.plan_hash,
                    "cursor": value.get("cursor"), "page_size": page_size}:
                raise BatchError("RENT_PREVIEW_CURSOR_INVALID", "Vorschauauswahl geändert. Erste Seite neu laden.", "restart_preview", 400)
            position = load_cursor(plan, value["cursor"])
        batch = plan_tick(plan, position, _planner_source(db, job, page_size), lambda *_: False, batch_size=page_size)
        items = _priced_targets(db, job, batch.targets)
        # One bounded lookup identifies existing targets without changing history.
        if hasattr(store, "db") and items:
            from sqlalchemy import tuple_
            existing = {
                    (r[0], r[1]): r[2] for r in db.execute(select(RentChargeORM.contract_id, RentChargeORM.month, RentChargeORM.id).where(
                        tuple_(RentChargeORM.contract_id, RentChargeORM.month).in_([(x["contract_id"], x["month"]) for x in items])))}
        else:
            keys = {(x["contract_id"], x["month"]) for x in items}
            existing = {(r.contract_id, r.month): r.id for r in store.rent_charges.values() if (r.contract_id, r.month) in keys} if not hasattr(store, "db") else {}
        for item in items:
            item["total_amount"] = (item["cold_cents"] + item["service_cents"] + item["heating_cents"]) / 100
            item["existing_charge_id"] = existing.get((item["contract_id"], item["month"]))
        next_cursor = None if batch.next_cursor.done else _pack(dict(v=1, purpose="preview", id=job.id,
            plan_hash=job.plan_hash, cursor=batch.next_cursor.dump(), page_size=page_size))
        return {"items": items, "next_cursor": next_cursor, "has_more": next_cursor is not None,
            "plan_hash": job.plan_hash, "sealed_at": job.sealed_at.isoformat(), "policy": "full_month"}
