"""Independent writers cannot turn a snapshot export into silently mixed data."""

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from backend.db.orm_models import DocumentORM, MaintenanceCaseORM, UnitORM
from backend.services import document_inventory_export, maintenance_inventory_export, unit_inventory_export
from backend.services.document_inventory import DocumentInventoryQuery
from backend.services.maintenance_inventory import MaintenanceInventoryQuery
from backend.services.unit_inventory import UnitInventoryQuery
from backend.tests.test_contract_workspace import active as active
from backend.tests.test_document_inventory import make_documents
from backend.tests.test_maintenance_date_filter import cases
from backend.tests.test_unit_inventory import make_units


@pytest.mark.parametrize("kind", ["units", "documents", "maintenance"])
def test_sql_concurrent_source_change_aborts_complete_export(active, kind):
    if not hasattr(active, "db"):
        pytest.skip("SQL snapshot and independent writer gate")
    if kind == "units":
        make_units(active, 3)
        chunks = unit_inventory_export.csv_chunks(active, UnitInventoryQuery(search="Einheit"), chunk_size=1)
        table, identifier, changes = UnitORM.__table__, "inventory-000001", {"label": "Einheit changed concurrently"}
    elif kind == "documents":
        make_documents(active, 3)
        chunks = document_inventory_export.csv_chunks(active, DocumentInventoryQuery(search="Dokument"), chunk_size=1)
        table, identifier, changes = DocumentORM.__table__, "document-000001", {"title": "Dokument changed concurrently"}
    else:
        cases(active, 3)
        chunks = maintenance_inventory_export.csv_chunks(active, MaintenanceInventoryQuery(sort_by="title"), chunk_size=1)
        table, identifier, changes = MaintenanceCaseORM.__table__, "case-000001", {"title": "Fall changed concurrently"}
    engine = active.db.get_bind()
    if engine.dialect.name == "sqlite":
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    try:
        assert next(chunks).startswith(b"\xef\xbb\xbf")
        with engine.begin() as writer:
            writer.execute(update(table).where(table.c.id == identifier).values(**changes))
        with pytest.raises(HTTPException) as error:
            next(chunks)
        assert error.value.status_code == 409
    finally:
        chunks.close()
