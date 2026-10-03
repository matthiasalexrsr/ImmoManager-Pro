"""Confirmation-only Account -> Operational -> Domain write fence.

This joins the caller's transaction. It never creates schema/singletons, seeds
jobs, commits, rolls back or changes evidence. Snapshot readers do not use it.
"""

from contextlib import ExitStack, contextmanager
from dataclasses import is_dataclass
from typing import Any, Iterator

from fastapi import HTTPException
from sqlalchemy import exists, inspect, or_, select, union
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.sql import CompoundSelect, Select

from .. import auth
from ..db.auth_models import AuthSetupORM
from ..db.operational_job_models import JOB_MODELS
from ..db.operational_models import (
    OperationalDispatchORM,
    OperationalLockORM,
    OperationalOccurrenceORM,
    OperationalScheduleORM,
    OperationalTickORM,
)
from ..db.orm_models import ContractORM, PropertyORM, TenantORM, UnitORM
from ..db.tenancy_workflow_models import TENANCY_WORKFLOW_MODELS, TenancyChangeORM
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause

OPERATIONAL_MODELS = (
    OperationalLockORM, OperationalScheduleORM, OperationalOccurrenceORM,
    OperationalDispatchORM, OperationalTickORM,
)
BUSY = "Personenbezogene Vorgänge werden gerade bearbeitet; der Datenstand kann gerade geändert werden. Vorschau neu laden und erneut versuchen."


def _conflict(message: str = BUSY):
    # Import only at use time: privacy owns staging and the public error type.
    from .tenant_privacy import PrivacyConflict
    return PrivacyConflict(message)


@contextmanager
def memory_account_fence(store: Any, *, sqlite_staged: bool = False) -> Iterator[None]:
    """Keep Memory auth stable, and enter operational state BEFORE domain.

    SQL domain + Memory auth is also supported. Its actual workflow writer does
    not take the Memory domain lock, so the SQL parent locks below remain vital.
    """
    db = getattr(store, "db", None)
    sqlite = db is not None and db.get_bind().dialect.name == "sqlite"
    if sqlite and not sqlite_staged:
        # SQLite writers take BEGIN IMMEDIATE, then recheck Memory auth before
        # commit. Do not hold their account mutex while waiting for that file
        # fence: it would prevent the existing writer from finishing. Once the
        # existing atomic writer owns SQLite, take auth before domain selection.
        try:
            yield
        except OperationalError as error:
            if getattr(error.orig, "sqlite_errorcode", 0) & 255 not in {5, 6}:
                raise
            raise _conflict() from error
        return
    if sqlite_staged and not sqlite:
        yield
        return
    from .operational_schedule import _state_lock
    from .payments import _memory_lock

    locks = [getattr(auth._user_store, "_lock", None)]
    if is_dataclass(store):
        locks.extend((_state_lock, _memory_lock))
    with ExitStack() as stack:
        for lock in locks:
            if lock is None:
                continue
            if not lock.acquire(blocking=False):
                raise _conflict()
            stack.callback(lock.release)
        yield


def _families(db: Session) -> set[str]:
    names = set(inspect(db.connection()).get_table_names())
    for models in (OPERATIONAL_MODELS, JOB_MODELS, TENANCY_WORKFLOW_MODELS):
        expected = {model.__tablename__ for model in models}
        present = expected & names
        if present and present != expected:
            raise _conflict("Unvollständige Vorgangstabellen. Migration prüfen; das Mieterprofil wurde nicht geändert.")
    if any(model.__tablename__ in names for model in JOB_MODELS) and OperationalLockORM.__tablename__ not in names:
        raise _conflict("Arbeitslisten benötigen die vollständige operative Sperrfamilie; das Mieterprofil wurde nicht geändert.")
    return names


def _singleton(db: Session, model: Any, *, required: bool, names: set[str]) -> None:
    if model.__tablename__ not in names:
        if required:
            raise _conflict("Die bestehende Benutzersperre fehlt. Migration prüfen; das Mieterprofil wurde nicht geändert.")
        return
    table = model.__table__
    if db.scalar(select(table.c.id).where(table.c.id == 1).with_for_update(nowait=True)) is None:
        # An unused, otherwise complete legacy family may have no singleton.
        # Lock its table against seed/UPDATE rather than silently repairing it.
        name = db.get_bind().dialect.identifier_preparer.format_table(table)
        db.connection().exec_driver_sql(f"LOCK TABLE {name} IN SHARE ROW EXCLUSIVE MODE NOWAIT")


def _lock_ids(db: Session, model: Any, identifiers: Select[Any] | CompoundSelect[Any]) -> None:
    table = model.__table__
    clause = scoped_clause(table)
    if clause is not None and db.connection().scalar(
        select(exists(select(table.c.id).where(table.c.id.in_(identifiers), ~clause)))
    ):
        raise HTTPException(403, "Der vollständige Personenbezug ist mit diesen Portfoliorechten nicht zugänglich.")
    result = db.execute(select(table.c.id).where(table.c.id.in_(identifiers))
        .order_by(table.c.id).with_for_update(nowait=True).execution_options(yield_per=100))
    try:
        for _ in result:
            pass
    finally:
        result.close()


def lock_subject_write_fence(store: Any, tenant_id: str) -> None:
    """Lock current and frozen subjects before recomputing the reviewed hash.

    SQLite's outer BEGIN IMMEDIATE already excludes independent SQL writers;
    schema validation still runs there. PostgreSQL takes only ID-projected row
    locks, in the same parent order as normal tenancy-change writers.
    """
    db = getattr(store, "db", None)
    if db is None:
        from .tenant_measurement_graph import lock_measurement_subject
        lock_measurement_subject(store, tenant_id)
        # Workflow.work initializes its whole Memory family. Job collections
        # are deliberately lazy (a queued job has no work-items yet), so absent
        # Memory job dictionaries are empty, not a missing SQL migration.
        for models in (TENANCY_WORKFLOW_MODELS,):
            expected = {model.__tablename__ for model in models}
            present = expected & store.__dict__.keys()
            if present and present != expected:
                raise _conflict("Unvollständige Vorgangssammlungen; das Mieterprofil wurde nicht geändert.")
        contracts = store.__dict__.get("contracts", {})
        for change in store.__dict__.get(TenancyChangeORM.__tablename__, {}).values():
            snapshot = change.snapshot
            current_party = any(identifier in contracts and contracts[identifier].tenant_id == tenant_id
                                for identifier in (change.previous_contract_id, change.next_contract_id))
            frozen_party = any((snapshot.get(key) or {}).get("tenant_id") == tenant_id
                               for key in ("previous_contract", "next_contract"))
            if (current_party or frozen_party) and not memory_visible(store, TenancyChangeORM.__tablename__, change):
                raise HTTPException(403, "Der vollständige Personenbezug ist mit diesen Portfoliorechten nicht zugänglich.")
        return
    names = _families(db)
    postgres = db.get_bind().dialect.name == "postgresql"
    try:
        if postgres:
            if isinstance(auth._user_store, auth.SQLUserStore):
                _singleton(db, AuthSetupORM, required=True, names=names)
            _singleton(db, OperationalLockORM, required=False, names=names)
        # Close the refresh -> management-lock gap before subject selection.
        # SQL account writers now cannot publish another grant/role change.
        refresh_scope(current_scope())

        contracts = ContractORM.__table__
        current = select(contracts.c.id).where(contracts.c.tenant_id == tenant_id)
        properties: Select[Any] | CompoundSelect[Any] = select(contracts.c.property_id).where(contracts.c.tenant_id == tenant_id)
        units: Select[Any] | CompoundSelect[Any] = select(contracts.c.unit_id).where(contracts.c.tenant_id == tenant_id)
        contract_ids: Select[Any] | CompoundSelect[Any] = current
        changes = None
        if TenancyChangeORM.__tablename__ in names:
            table = TenancyChangeORM.__table__
            condition = or_(
                table.c.previous_contract_id.in_(current), table.c.next_contract_id.in_(current),
                table.c.snapshot["previous_contract"]["tenant_id"].as_string() == tenant_id,
                table.c.snapshot["next_contract"]["tenant_id"].as_string() == tenant_id,
            )
            changes = select(table.c.id).where(condition)
            properties = union(properties, select(table.c.property_id).where(condition))
            units = union(units, select(table.c.unit_id).where(condition))
            contract_ids = union(current,
                select(table.c.previous_contract_id).where(condition),
                select(table.c.next_contract_id).where(condition))

        from .tenant_measurement_graph import lock_measurement_subject
        lock_measurement_subject(store, tenant_id)

        # SELECT subqueries keep large histories out of Python memory. Domain
        # locks are NOWAIT too: a writer's earlier Tenant read-lock (original
        # evidence) must not turn an opposite parent order into a deadlock.
        for model, identifiers in ((PropertyORM, properties), (UnitORM, units), (ContractORM, contract_ids)):
            _lock_ids(db, model, identifiers)
        tenant = db.scalar(select(TenantORM).where(TenantORM.id == tenant_id).with_for_update(nowait=postgres))
        if tenant is None:
            from .tenant_data_graph import TenantNotFoundError
            raise TenantNotFoundError("Tenant not found")
        if changes is not None:
            _lock_ids(db, TenancyChangeORM, changes)
    except OperationalError as error:
        if getattr(error.orig, "sqlstate", getattr(error.orig, "pgcode", None)) != "55P03":
            raise
        raise _conflict() from error
