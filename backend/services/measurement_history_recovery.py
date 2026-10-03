"""Registration-free backup/privacy helpers. Root owns central integration."""

from fastapi import HTTPException
from sqlalchemy import exists, or_, select

from ..db.measurement_history_models import (
    MEASUREMENT_MODELS,
    MEASUREMENT_TABLES,
    MeasurementCommandORM,
    MeasurementFactORM,
)
from ..db.orm_models import ContractORM
from .measurement_history import _rows, verified_rows
from .measurement_history_validation import payload, validate_measurement_snapshot
from .portfolio_scope import memory_visible, scoped_clause

RESTORE_ORDER = MEASUREMENT_TABLES
RESTORE_PARENTS = ("portfolios", "properties", "units", "meters", "allocation_keys", "contracts", "tenants", "document_versions")
VALIDATE_SNAPSHOT = validate_measurement_snapshot


def iter_measurement_family(store, name):
    """Streaming rows for an already authorized backup snapshot, no side effects."""
    model = next((candidate for candidate in MEASUREMENT_MODELS if candidate.__tablename__ == name), None)
    if model is None:
        raise ValueError("Unknown measurement family")
    if hasattr(store, "db"):
        query = select(model).order_by(model.id).execution_options(yield_per=100)
        result = store.db.scalars(query)
        try:
            for row in result:
                yield payload(row)
        finally:
            result.close()
    else:
        for row in _rows(store, model):
            yield payload(row)


def retained_measurement_subject(store, tenant_id):
    """Only the exact subject's frozen/current occupancy evidence, no peer text.

    Embed in the existing authorized privacy snapshot. Do not expose a whole
    command request: a single command may contain the next tenant's private
    notes. Shared technical meter evidence remains retained at property level.
    """
    store.get_tenant(tenant_id)
    if hasattr(store, "db"):
        contract_ids = select(ContractORM.id).where(ContractORM.tenant_id == tenant_id)
        subject = or_(MeasurementFactORM.tenant_id == tenant_id, MeasurementFactORM.contract_id.in_(contract_ids))
        clause = scoped_clause(MeasurementFactORM)
        if clause is not None and store.db.connection().scalar(select(exists(select(MeasurementFactORM.id).where(subject, ~clause)))):
            raise HTTPException(403, "Der vollständige historische Personenbezug ist mit diesen Portfoliorechten nicht zugänglich.")
        rows = list(store.db.scalars(select(MeasurementFactORM).where(or_(
            MeasurementFactORM.tenant_id == tenant_id, MeasurementFactORM.contract_id.in_(contract_ids)))
            .order_by(MeasurementFactORM.ledger_id, MeasurementFactORM.revision, MeasurementFactORM.position)))
    else:
        contracts = {contract.id for contract in store.list_contracts() if contract.tenant_id == tenant_id}
        rows = sorted((row for row in _rows(store, MeasurementFactORM)
            if row.tenant_id == tenant_id or row.contract_id in contracts), key=lambda row: (row.ledger_id, row.revision, row.position))
        if any(not memory_visible(store, MeasurementFactORM.__tablename__, row) for row in rows):
            raise HTTPException(403, "Der vollständige historische Personenbezug ist mit diesen Portfoliorechten nicht zugänglich.")
    items = verified_rows(store, rows)
    command_ids = {row.command_id for row in rows}
    if hasattr(store, "db"):
        commands = [row for offset in range(0, len(command_ids), 500)
            for row in store.db.scalars(select(MeasurementCommandORM).where(
                MeasurementCommandORM.id.in_(sorted(command_ids)[offset:offset + 500])))]
    else:
        commands = [row for row in _rows(store, MeasurementCommandORM) if row.id in command_ids]
    return {"facts": items, "commands": [{key: getattr(row, key) for key in
        ("id", "ledger_id", "actor_id", "revision", "request_hash", "created_at")} for row in commands],
        "retention": "Unveränderliche historische Abrechnungsquellen bleiben mit ihrem ursprünglichen Personenbezug erhalten. Gemeinsam erfasste Angaben anderer Mietverhältnisse werden hier nicht ausgegeben."}


def assert_no_measurement_cascade(store, entity_type, entity_id):
    """Memory/delete integration hook; SQL RESTRICT FKs already retain rows."""
    if entity_type == "tenant":
        if retained_measurement_subject(store, entity_id)["facts"]:
            raise ValueError("Historische Abrechnungsgrundlagen müssen erhalten bleiben.")
        return
    fields = {"unit": "ledger_id", "property": "property_id", "portfolio": "portfolio_id",
              "contract": "contract_id", "meter": "meter_id", "allocation_key": "allocation_key_id"}
    name = fields.get(entity_type)
    if name is None:
        return
    if hasattr(store, "db"):
        found = store.db.scalar(select(MeasurementFactORM.id).where(getattr(MeasurementFactORM, name) == entity_id).limit(1))
    else:
        found = next((row.id for row in _rows(store, MeasurementFactORM) if getattr(row, name) == entity_id), None)
    if found:
        raise ValueError("Historische Abrechnungsgrundlagen müssen erhalten bleiben.")
