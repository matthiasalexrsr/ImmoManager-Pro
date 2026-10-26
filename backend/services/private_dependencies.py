"""Restrictive references of additive evidence, shared by API and memory delete."""
from fastapi import HTTPException
from sqlalchemy import select

from ..db.orm_models import Base

FAMILIES = ("e_invoice_", "payment_recipient_", "payment_authorization", "data_", "external_portal_")


def ensure_unbound(store, table_name, identifier):
    for table in Base.metadata.tables.values():
        if not table.name.startswith(FAMILIES):
            continue
        for column in table.columns:
            if not any(fk.column.table.name == table_name and fk.ondelete in (None, "RESTRICT", "NO ACTION") for fk in column.foreign_keys):
                continue
            if hasattr(store, "db"):
                present = store.db.scalar(select(1).select_from(table).where(column == identifier).limit(1)) is not None
            else:
                present = any(getattr(row, column.name) == identifier for row in store.__dict__.get("_integration_connections", {}).get(table.name, {}).values())
            if present:
                raise HTTPException(409, "Der Datensatz wird für einen gespeicherten Beleg-, Freigabe-, Übernahme- oder Portalnachweis benötigt und kann nicht gelöscht werden.")
