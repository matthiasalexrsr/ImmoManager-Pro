"""One booking mutation and all derived contract allocations, committed together."""

from collections.abc import MutableMapping, MutableSet
from contextlib import contextmanager, nullcontext
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, scoped_session

from .. import auth
from ..db.orm_models import (
    AccountORM,
    BookingORM,
    CategoryORM,
    ContractORM,
    PaymentAllocationORM,
    PropertyORM,
    TenantORM,
    UnitORM,
)
from ..storage import NotFoundError, ValidationError
from .billing_writes import _ACTIVE
from .document_versions import begin_writer, check_account, memory_archive
from .portfolio_scope import current_scope, scope_from_user

_OWNED = "booking_write_unit"
_BINDING = ("account_id", "category_id", "property_id", "unit_id", "tenant_id", "reverses_booking_id")


class _Rows(MutableMapping):
    """Journal replacements, not copies of historical booking models."""

    def __init__(self, rows):
        self.rows, self.before = rows, {}

    def __getitem__(self, key):
        return self.rows[key]

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)

    def _remember(self, key):
        if key not in self.before:
            self.before[key] = (key in self.rows, self.rows.get(key))

    def __setitem__(self, key, value):
        self._remember(key)
        self.rows[key] = value

    def __delitem__(self, key):
        self._remember(key)
        del self.rows[key]

    def rollback(self):
        for key, (present, value) in self.before.items():
            if present:
                self.rows[key] = value
            else:
                self.rows.pop(key, None)


class _Grants(MutableSet):
    def __init__(self, rows):
        self.rows, self.before = rows, {}

    def __contains__(self, key):
        return key in self.rows

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)

    def add(self, key):
        self.before.setdefault(key, key in self.rows)
        self.rows.add(key)

    def discard(self, key):
        self.before.setdefault(key, key in self.rows)
        self.rows.discard(key)

    def update(self, values):
        for key in values:
            self.add(key)

    def rollback(self):
        for key, present in self.before.items():
            (self.rows.add if present else self.rows.discard)(key)


def _check_actor(scope, user):
    if scope is not None:
        check_account(user, write_areas=("/bookings",))
        if scope_from_user(user) != scope:
            raise HTTPException(403, "Berechtigungen wurden geändert. Bitte die Anfrage erneut starten.")


@contextmanager
def _actor(scope, db=None):
    # No captured actor means an existing direct service/test caller, not an HTTP
    # authorization bypass: HTTP requests always establish their portfolio scope.
    lock = auth.locked_account(scope.user_id, db) if scope is not None else nullcontext(None)
    with lock as user:
        _check_actor(scope, user)
        yield


def _recheck_actor(scope, db):
    if scope is not None:
        db.expire_all()
        with auth.locked_account(scope.user_id, db) as current:
            _check_actor(scope, current)


def _lock_booking(db, store, booking_id, reversal_of, changes):
    # Every change of a reversal and every new partial reversal locks the original
    # first. A second writer must re-read the remaining amount after that lock.
    existing = store.get_booking(booking_id) if booking_id is not None else None
    if existing is not None:
        reversal_of = existing.reverses_booking_id or reversal_of
    try:
        source = store.get_booking(reversal_of) if reversal_of else None
    except NotFoundError:
        source = None  # preserve the repository's invalid reversal-link error
    before = {row.id: tuple(getattr(row, key) for key in _BINDING) for row in (existing, source) if row}
    if db.get_bind().dialect.name == "postgresql":
        _lock_parents(db, store, existing, source, changes)
    for key in dict.fromkeys(key for key in (reversal_of, booking_id) if key):
        db.scalar(select(BookingORM.id).where(BookingORM.id == key).with_for_update())
    db.expire_all()
    for key, binding in before.items():
        if tuple(getattr(store.get_booking(key), field) for field in _BINDING) != binding:
            raise HTTPException(409, "Die Buchungszuordnung wurde geändert. Bitte neu laden.")


def _lock_parents(db, store, existing, source, changes):
    """Hold just the operation's reference parents against portfolio moves.

    SHARE, rather than KEY SHARE, also blocks non-key portfolio/binding updates.
    Match the parent order used by rent/deposit units, then lock the booking.
    """
    references = [row.model_dump() for row in (existing, source) if row is not None]
    prospective = {**(existing.model_dump() if existing else {}), **(changes or {})}
    references.append(prospective)
    tenants = {row["tenant_id"] for row in references if row.get("tenant_id")}
    # Lock tenants before discovering candidates. FOR UPDATE also excludes FK
    # KEY SHARE taken by a newly inserted contract, unlike a parent SHARE lock.
    # Auto-allocation cannot subsequently discover an unlocked phantom contract.
    for key in sorted(tenants):
        if db.scalar(select(TenantORM.id).where(TenantORM.id == key).with_for_update()) is None:
            raise ValidationError("Der Buchungsmieter ist nicht mehr verfügbar")
    contracts = list(db.scalars(select(ContractORM).where(ContractORM.tenant_id.in_(sorted(tenants))))) if tenants else []
    initial: dict[tuple[type, str], tuple[Any, ...]] = {
        (ContractORM, row.id): (row.tenant_id, row.property_id, row.unit_id) for row in contracts}
    unit_ids = {row["unit_id"] for row in references if row.get("unit_id")} | {row.unit_id for row in contracts}
    units = [store.get_unit(key) for key in sorted(unit_ids)]
    initial.update({(UnitORM, row.id): (row.property_id,) for row in units})
    property_ids = ({row["property_id"] for row in references if row.get("property_id")}
                    | {row.property_id for row in contracts} | {row.property_id for row in units})
    groups = (
        (PropertyORM, property_ids, ("portfolio_id",)),
        (UnitORM, unit_ids, ("property_id",)),
        (ContractORM, {row.id for row in contracts}, ("tenant_id", "property_id", "unit_id")),
        (AccountORM, {row["account_id"] for row in references if row.get("account_id")}, ("portfolio_id",)),
        (CategoryORM, {row["category_id"] for row in references if row.get("category_id")}, ()),
    )
    # Read all bindings before acquiring any parent locks, then verify after each
    # lock wait. A moved reference must not silently change the unit's lock set.
    expected = {}
    for model, keys, fields in groups:
        for key in sorted(keys):
            row = db.scalar(select(model).where(model.id == key))
            if row is None:
                raise ValidationError("Die Buchungsreferenz ist nicht mehr verfügbar")
            expected[(model, key)] = initial.get((model, key), tuple(getattr(row, field) for field in fields))
    for model, keys, fields in groups:
        for key in sorted(keys):
            row = db.scalar(select(model).where(model.id == key).with_for_update(read=True)
                            .execution_options(populate_existing=True))
            if row is None:
                raise ValidationError("Die Buchungsreferenz ist nicht mehr verfügbar")
            if tuple(getattr(row, field) for field in fields) != expected[(model, key)]:
                raise HTTPException(409, "Eine Buchungsreferenz wurde verschoben. Bitte neu laden.")


@contextmanager
def booking_write(store, *, booking_id=None, reversal_of=None, changes=None):
    """Yield a store whose legacy writes flush; publish only the complete operation.

    Parent scope and account checks remain active inside the transaction. An owned
    SQL session avoids committing or rolling back unrelated caller work. Memory
    uses the same writer lock as rent receipts and revision-checked edits.
    """
    scope = current_scope()
    if not hasattr(store, "db"):
        with _actor(scope), memory_archive(store).lock:
            raw = object.__getattribute__(store, "__dict__")
            journals = {name: _Rows(raw[name]) for name in ("bookings", "payment_allocations")}
            had_grants = "_resource_grants" in raw
            grants = _Grants(raw.get("_resource_grants", set()))
            raw.update(journals)
            raw["_resource_grants"] = grants
            try:
                yield store
                # Recheck while the memory writer and account locks are still held.
                if scope is not None:
                    _check_actor(scope, auth.get_user_by_id(scope.user_id))
            except BaseException:
                for journal in journals.values():
                    journal.rollback()
                grants.rollback()
                raise
            finally:
                raw.update({name: journal.rows for name, journal in journals.items()})
                if had_grants or grants.rows:
                    raw["_resource_grants"] = grants.rows
                else:
                    raw.pop("_resource_grants", None)
        return

    from ..repositories.sql_store import SQLAlchemyStore

    caller = store.db() if isinstance(store.db, scoped_session) else store.db
    if caller.info.get(_OWNED):
        # Only our own unit participates. A caught nested failure rolls back to
        # this savepoint; successful children still depend on the outer commit.
        with caller.begin_nested():
            _lock_booking(caller, store, booking_id, reversal_of, changes)
            yield store
        return
    bind = caller.get_bind()
    if bind.dialect.name == "sqlite" and caller.in_transaction():
        driver = caller.connection().connection.driver_connection
        if driver is not None and driver.in_transaction:
            # A file database would deadlock on the caller's writer; a shared
            # in-memory connection could commit/rollback the caller's work.
            raise RuntimeError("Die Buchung benötigt eine eigene Transaktion; zuerst die laufende SQLite-Transaktion beenden.")
    db = Session(bind=getattr(bind, "engine", bind), autoflush=False, expire_on_commit=False)
    target = SQLAlchemyStore(db)
    db.info[_ACTIVE] = True  # the existing repository commit_or_flush coordination
    db.info[_OWNED] = True
    try:
        begin_writer(db)
        with _actor(scope, db):
            _lock_booking(db, target, booking_id, reversal_of, changes)
            yield target
            _recheck_actor(scope, db)
            db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
        # Refresh clean booking models a direct caller may have read, without
        # discarding its unrelated pending edits or committing its transaction.
        for row in list(caller.identity_map.values()):
            if isinstance(row, (BookingORM, PaymentAllocationORM)) and row not in caller.dirty:
                caller.expire(row)
