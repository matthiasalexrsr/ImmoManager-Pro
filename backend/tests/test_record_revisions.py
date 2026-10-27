"""Revision checks in unit-backed row writes also survive a stalled clock."""

from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.orm_models import Base
from backend.models import InvoiceCreate
from backend.repositories import SQLAlchemyStore
from backend.services import maintenance_rows
from backend.services.document_versions import memory_archive
from backend.services.record_revisions import ExpectedRevision, expected_revision, revision_scope
from backend.storage import InMemoryStore


@pytest.mark.parametrize("backend", ["memory", "sql"])
def test_rows_consume_exact_revision_and_advance_even_when_clock_stalls(backend, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        target = InMemoryStore() if backend == "memory" else SQLAlchemyStore(session)
        original = target.create_invoice(InvoiceCreate(
            supplier="Original", invoice_date=date(2026, 1, 1), net_amount=100, gross_amount=100, vat_rate=0))
        expected = ExpectedRevision("invoices", original.id, original.updated_at)
        monkeypatch.setattr(maintenance_rows, "stamp", lambda table: original.updated_at)
        rows = maintenance_rows.Rows.reading(target)
        with revision_scope(expected), memory_archive(target).lock:
            first = rows.update("invoices", original.id, supplier="First edit")
            session.commit()
            assert expected_revision("invoices", original.id) is None
        assert first.updated_at == original.updated_at + timedelta(milliseconds=2)
        with revision_scope(expected), memory_archive(target).lock:
            with pytest.raises(HTTPException) as refused:
                rows.update("invoices", original.id, supplier="Lost edit")
            assert refused.value.status_code == 409
            session.rollback()
        assert rows.get("invoices", original.id).supplier == "First edit"
        assert expected_revision("invoices", original.id) is None
    engine.dispose()
