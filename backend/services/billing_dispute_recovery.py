"""Complete recovery family and ordinary-parent retention hooks for Root."""

from fastapi import HTTPException
from sqlalchemy import exists, select

from ..db.billing_dispute_models import DISPUTE_MODELS, DISPUTE_TABLES
from ..db.billing_dispute_models import BillingDisputeCaseORM as Case
from ..db.billing_dispute_models import BillingDisputeEvidenceORM as Evidence
from ..db.billing_dispute_schema import validate_dispute_schema
from ..db.document_version_models import DocumentVersionORM
from ..storage import ValidationError
from .billing_dispute_validation import DisputeIntegrityError, payload, validate_dispute_snapshot

RESTORE_ORDER = DISPUTE_TABLES
RESTORE_PARENTS = ("portfolios", "properties", "units", "contracts", "tenants", "billing_periods", "utility_statements", "document_versions")
VALIDATE_SNAPSHOT = validate_dispute_snapshot
PARENT_FIELDS = {"portfolios": "portfolio_id", "properties": "property_id", "units": "unit_id",
                 "contracts": "contract_id", "tenants": "tenant_id", "billing_periods": "period_id",
                 "utility_statements": "statement_id"}


def available(store):
    if hasattr(store, "db"):
        return validate_dispute_schema(store.db.connection())
    present = set(DISPUTE_TABLES) & store.__dict__.keys()
    if present and present != set(DISPUTE_TABLES):
        raise DisputeIntegrityError("Unvollständiges Widerspruchsjournal.")
    return bool(present)


def iter_dispute_family(store, name):
    model = next((row for row in DISPUTE_MODELS if row.__tablename__ == name), None)
    if model is None:
        raise ValueError("Unknown dispute collection")
    order = ("case_id", "revision") if name in {"billing_dispute_commands", "billing_dispute_events"} else ("id",)
    if hasattr(store, "db"):
        result = store.db.scalars(select(model).order_by(*(getattr(model, key) for key in order)).execution_options(yield_per=100))
        try:
            for row in result:
                yield payload(row)
        finally:
            result.close()
    else:
        for row in sorted(store.__dict__.get(name, {}).values(), key=lambda item: tuple(getattr(item, key) for key in order)):
            yield payload(row)


def guard_parent(store, table, identifier):
    if table not in {*PARENT_FIELDS, "documents"} or not available(store):
        return
    field = PARENT_FIELDS.get(table)
    if hasattr(store, "db"):
        if field:
            retained = store.db.connection().scalar(select(exists(select(Case.__table__.c.id).where(getattr(Case.__table__.c, field) == identifier))))
        else:
            versions = select(DocumentVersionORM.__table__.c.id).where(DocumentVersionORM.__table__.c.document_id == identifier)
            retained = store.db.connection().scalar(select(exists(select(Evidence.__table__.c.id).where(Evidence.__table__.c.version_id.in_(versions)))))
    else:
        if field:
            retained = any(getattr(row, field) == identifier for row in store.__dict__.get(Case.__tablename__, {}).values())
        else:
            memory_versions = {row.id for row in store.__dict__.get("document_versions", {}).values() if row.document_id == identifier}
            retained = any(row.version_id in memory_versions for row in store.__dict__.get(Evidence.__tablename__, {}).values())
    if retained:
        raise HTTPException(409, "Das Widerspruchsjournal benötigt diese ursprüngliche Zuordnung und seine Originalanlagen. Originale erhalten; eine neue tatsächliche Zuordnung als eigenen Stammdatensatz erfassen.")


def property_ids(store, table, identifier):
    field = PARENT_FIELDS.get(table)
    if field is None or not available(store):
        return set()
    if hasattr(store, "db"):
        raw = Case.__table__
        return set(store.db.connection().scalars(select(raw.c.property_id).where(getattr(raw.c, field) == identifier).distinct()))
    return {row.property_id for row in store.__dict__.get(Case.__tablename__, {}).values() if getattr(row, field) == identifier}


def guard_partial_transfer(store):
    if not available(store):
        return
    if hasattr(store, "db"):
        retained = store.db.connection().scalar(select(exists(select(Case.__table__.c.id))))
    else:
        retained = bool(store.__dict__.get(Case.__tablename__))
    if retained:
        raise ValidationError("Widerspruchsoriginale und Anlagen benötigen ein vollständiges Backup. Ein Geschäftsdatenteiltransfer würde den ursprünglichen Bezug verlieren.")
