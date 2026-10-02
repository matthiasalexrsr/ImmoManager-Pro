"""Keep source identity and historical evidence through every CRUD path."""

from sqlalchemy import select

from ..db.document_version_models import DocumentVersionORM
from ..db.orm_models import Base, DocumentORM, PropertyORM, UnitORM
from ..storage import ValidationError
from .contract_occupancy import begin_writer

PROTECTED = ("file_url", "property_id", "unit_id", "contract_id")
MESSAGE = "Archivierte Dokumentfassungen benötigen ihre ursprüngliche Zuordnung. Neue Datei bewusst als neue Version veröffentlichen."


def guard_edit(store, table, old, updates):
    if table not in {"documents", "properties", "units"}:
        return
    fields = PROTECTED if table == "documents" else ("portfolio_id",) if table == "properties" else ("property_id",)
    if not any(key in updates and updates[key] != getattr(old, key) for key in fields):
        return
    db = getattr(store, "db", None)
    name = {"documents": "document_id", "properties": "property_id", "units": "unit_id"}[table]
    field = getattr(DocumentVersionORM, name)
    if db is not None:
        begin_writer(db)
        model_id = {"documents": DocumentORM.id, "properties": PropertyORM.id, "units": UnitORM.id}[table]
        db.scalar(select(model_id).where(model_id == old.id).with_for_update())
        present = db.scalar(select(DocumentVersionORM.id).where(field == old.id).limit(1))
    else:
        present = any(getattr(row, name) == old.id for row in store.__dict__.get("document_versions", {}).values())
    if present:
        raise ValidationError(MESSAGE)


def guard_delete_link(store, table, identifier):
    field_name = {"documents": "document_id", "properties": "property_id", "units": "unit_id",
        "contracts": "contract_id", "tenants": "tenant_id", "portfolios": "portfolio_id"}.get(table)
    if field_name is None:
        return
    db = getattr(store, "db", None)
    if db is not None:
        begin_writer(db)
        parent = Base.metadata.tables[table]
        db.scalar(select(parent.c.id).where(parent.c.id == identifier).with_for_update())
        present = db.scalar(select(DocumentVersionORM.id).where(getattr(DocumentVersionORM, field_name) == identifier).limit(1))
    else:
        present = any(getattr(row, field_name) == identifier for row in store.__dict__.get("document_versions", {}).values())
    if present:
        raise ValidationError("Dokumentoriginale und Versionshistorie sind vorhanden. Quelle und Zuordnung müssen erhalten bleiben.")


def guard_partial_transfer(store):
    db = getattr(store, "db", None)
    present = (db.scalar(select(DocumentVersionORM.id).limit(1)) is not None) if db is not None else bool(
        store.__dict__.get("document_versions"))
    if present:
        raise ValidationError("Dokumentversionen und Originalbytes sind nicht Teil des Geschäftsdatenteiltransfers. Vollständiges Backup verwenden.")
