"""Ordinary parent writes share measurement locks and preserve original links."""

from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import event, exists, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .. import auth
from ..db.measurement_history_models import MeasurementEvidenceORM, MeasurementFactORM, MeasurementLedgerORM
from ..db.measurement_history_schema import validate_measurement_schema
from ..db.orm_models import (
    AllocationKeyORM,
    BillingPeriodORM,
    ContractORM,
    DocumentORM,
    MeterORM,
    PortfolioORM,
    PropertyORM,
    TenantORM,
    UnitORM,
    UtilityStatementORM,
)
from ..permissions import may_write_resource
from .measurement_history import lock_measurement_property
from .measurement_history_validation import MeasurementIntegrityError
from .portfolio_scope import current_scope, refresh_scope
from .request_authority import require_fresh_request_authority

PARENTS = {model.__tablename__: model for model in
    (PortfolioORM, PropertyORM, UnitORM, ContractORM, TenantORM, AllocationKeyORM, MeterORM, DocumentORM, BillingPeriodORM, UtilityStatementORM)}
FIELDS = {"properties": ("portfolio_id",), "units": ("property_id",),
          "contracts": ("property_id", "unit_id", "tenant_id"), "allocation_keys": ("property_id",),
          "billing_periods": ("property_id",), "utility_statements": ("billing_period_id", "contract_id", "unit_id")}
MESSAGE = ("Bestätigte historische Abrechnungsquellen benötigen diese ursprüngliche Zuordnung. "
           "Originale erhalten; fehlerhafte Quellen begründet korrigieren oder für eine tatsächlich neue "
           "Zuordnung einen eigenen Stammdatensatz anlegen. Bezeichnungen bleiben bearbeitbar.")


def _resource(table):
    return "billing" if table in {"allocation_keys", "billing_periods", "utility_statements"} else table


def fresh(table, captured):
    if captured is None:
        return
    refresh_scope(captured)
    require_fresh_request_authority(captured.user_id)
    if not may_write_resource(captured.role, _resource(table)):
        raise HTTPException(403, "Keine aktuelle Berechtigung für diese Stammdatenänderung.")


def _available(store):
    if not hasattr(store, "db"):
        names = {"measurement_ledgers", "measurement_commands", "measurement_facts", "measurement_evidence"}
        present = names & store.__dict__.keys()
        if present and present != names:
            raise HTTPException(409, "Historische Quellenfamilie unvollständig. Wiederherstellung prüfen.")
        return bool(present)
    try:
        return validate_measurement_schema(store.db.connection())
    except MeasurementIntegrityError as error:
        raise HTTPException(409, str(error)) from error


def _references(table, identifier):
    if table in {"portfolios", "properties", "units"}:
        field = {"portfolios": "portfolio_id", "properties": "property_id", "units": "id"}[table]
        return MeasurementLedgerORM, field
    fact_field = {"contracts": "contract_id", "tenants": "tenant_id", "allocation_keys": "allocation_key_id", "meters": "meter_id"}.get(table)
    return (MeasurementFactORM, fact_field) if fact_field else (None, None)


def guard_retained(store, table, identifier):
    """Existence only, including hidden originals; caller owns locks and auth."""
    if table not in PARENTS:
        return
    from .billing_dispute_recovery import guard_parent
    guard_parent(store, table, identifier)
    if table in {"billing_periods", "utility_statements"} or not _available(store):
        return
    model, field = _references(table, identifier)
    if model is None:
        # Document originals already have their immutable guard. Evidence also
        # protects a Memory document before any parent cascade starts.
        from ..db.document_version_models import DocumentVersionORM
        if hasattr(store, "db"):
            versions = select(DocumentVersionORM.id).where(DocumentVersionORM.document_id == identifier)
            retained = store.db.connection().scalar(select(exists(select(MeasurementEvidenceORM.id).where(MeasurementEvidenceORM.version_id.in_(versions)))))
        else:
            version_ids = {row.id for row in store.__dict__.get("document_versions", {}).values() if row.document_id == identifier}
            retained = any(row.version_id in version_ids for row in store.__dict__.get("measurement_evidence", {}).values())
    elif hasattr(store, "db"):
        db = store.db
        retained = any(isinstance(row, model) and getattr(row, field) == identifier for row in db.new | db.dirty | db.deleted)
        retained = retained or db.connection().scalar(select(exists(select(model.id).where(getattr(model, field) == identifier))))
    else:
        retained = any(getattr(row, field) == identifier for row in store.__dict__.get(model.__tablename__, {}).values())
    if retained:
        raise HTTPException(409, MESSAGE)


def guard_edit(store, table, current, changes):
    if current is not None and any(name in changes and changes[name] != getattr(current, name) for name in FIELDS.get(table, ())):
        from .billing_dispute_recovery import guard_parent
        guard_parent(store, table, current.id)
        if table in {"billing_periods", "utility_statements"}:
            return
        if _repairs_original_binding(store, table, current, changes):
            return
        guard_retained(store, table, current.id)


def _repairs_original_binding(store, table, current, changes):
    """Allow an ordinary correction back to every preserved original binding.

    Read booleans only, including hidden facts. Ambiguous original bindings
    cannot be resolved by overwriting evidence or choosing an arbitrary parent.
    """
    if not _available(store):
        return False
    model, field = _references(table, current.id)
    fields = {"properties": {"portfolio_id": "portfolio_id"},
              "units": {"property_id": "property_id"},
              "contracts": {"property_id": "property_id", "unit_id": "ledger_id", "tenant_id": "tenant_id"},
              "allocation_keys": {"property_id": "property_id"}}[table]
    values = {stored: changes.get(live, getattr(current, live)) for live, stored in fields.items()}
    if hasattr(store, "db"):
        pending = [row for row in store.db.new | store.db.dirty | store.db.deleted
                   if isinstance(row, model) and getattr(row, field) == current.id]
        if any(any(getattr(row, name) != value for name, value in values.items()) for row in pending):
            return False
        predicate = getattr(model, field) == current.id
        present = store.db.connection().scalar(select(exists(select(model.id).where(predicate))))
        mismatch = store.db.connection().scalar(select(exists(select(model.id).where(predicate,
            or_(*(getattr(model, name).is_distinct_from(value) for name, value in values.items()))))))
        return bool((present or pending) and not mismatch)
    originals = [row for row in store.__dict__.get(model.__tablename__, {}).values() if getattr(row, field) == current.id]
    return bool(originals) and all(all(getattr(row, name) == value for name, value in values.items()) for row in originals)


def _properties(db, table, row):
    if table == "properties":
        return {row.id}
    if table in {"units", "contracts", "allocation_keys", "documents", "billing_periods"}:
        return {row.property_id} - {None}
    if table == "utility_statements":
        return set(db.scalars(select(BillingPeriodORM.property_id).where(BillingPeriodORM.id == row.billing_period_id)))
    if table == "meters":
        return set(db.scalars(select(UnitORM.property_id).where(UnitORM.id == row.unit_id)))
    if table == "portfolios":
        return set(db.scalars(select(PropertyORM.id).where(PropertyORM.portfolio_id == row.id)))
    if table == "tenants":
        return set(db.scalars(select(ContractORM.property_id).where(ContractORM.tenant_id == row.id)))
    return set()


def guard_sql_write(db, table, identifier, changes=None):
    """Before lifecycle/parent locks, shared by repository PUT/PATCH/DELETE."""
    try:
        _guard_sql_write(db, table, identifier, changes)
    except OperationalError as error:
        sqlite_code = getattr(error.orig, "sqlite_errorcode", 0) & 255
        postgres_code = getattr(error.orig, "sqlstate", getattr(error.orig, "pgcode", None))
        if sqlite_code not in {5, 6} and postgres_code not in {"55P03", "40P01", "40001"}:
            raise
        raise HTTPException(409, "Historische Quellen oder Stammdaten werden gerade bearbeitet. Bestand erneut laden und Änderung wiederholen.") from error


def _guard_sql_write(db, table, identifier, changes=None):
    if table not in PARENTS:
        return
    from ..repositories.sql_store import SQLAlchemyStore
    from .contract_occupancy import begin_writer
    active = SQLAlchemyStore(db)
    captured = current_scope()
    fresh(table, captured)
    begin_writer(db)
    if isinstance(auth._user_store, auth.SQLUserStore):
        auth._user_store._lock_management(db)
    row = db.get(PARENTS[table], identifier, populate_existing=True)
    if row is None:
        return  # Existing repository preserves conditional 412 / ordinary 404.
    previous = {name: getattr(row, name) for name in FIELDS.get(table, ())}
    properties = _properties(db, table, row)
    from .billing_dispute_recovery import property_ids
    properties |= property_ids(active, table, identifier)
    if changes:
        properties |= {changes.get("property_id")} - {None}
        if changes.get("unit_id"):
            properties.update(db.scalars(select(UnitORM.property_id).where(UnitORM.id == changes["unit_id"])))
    for property_id in sorted(properties):
        lock_measurement_property(active, property_id)
    row = db.get(PARENTS[table], identifier, populate_existing=True)
    if row is None or any(getattr(row, key) != value for key, value in previous.items()):
        raise HTTPException(409, "Stammdatenzuordnung wurde gleichzeitig geändert. Bestand erneut laden.")
    if changes is None:
        guard_retained(active, table, identifier)
    else:
        guard_edit(active, table, row, changes)
    fresh(table, captured)
    if captured is not None:
        db.info.setdefault("measurement_parent_authority", {})[(captured.user_id, table)] = captured


@event.listens_for(Session, "before_commit")
def _fresh_commit(db):
    pending = db.info.get("measurement_parent_authority", {})
    if not pending:
        return
    lock = getattr(auth._user_store, "_lock", None)
    if lock is not None:
        lock.acquire()
        db.info["measurement_parent_account_lock"] = lock
    try:
        for (_user, table), captured in pending.items():
            fresh(table, captured)
    except BaseException:
        held = db.info.pop("measurement_parent_account_lock", None)
        if held is not None:
            held.release()
        raise


@event.listens_for(Session, "after_transaction_end")
def _release_commit(db, transaction):
    if transaction.parent is None:
        db.info.pop("measurement_parent_authority", None)
        held = db.info.pop("measurement_parent_account_lock", None)
        if held is not None:
            held.release()


@contextmanager
def memory_write(store, table, current, changes=None):
    from .tenant_privacy import _memory_privacy_lock
    with _memory_privacy_lock():
        captured = current_scope()
        if table in PARENTS:
            fresh(table, captured)
            if current is not None:
                current = getattr(store, table).get(current.id)
            if current is not None:
                if changes is None:
                    guard_retained(store, table, current.id)
                else:
                    guard_edit(store, table, current, changes)
            fresh(table, captured)
        yield
