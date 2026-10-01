"""A filtered invoice beyond 10,000 historical rows must remain reachable."""
from datetime import date

from sqlalchemy import event

from backend.db.orm_models import InvoiceORM
from backend.services.invoice_list import filtered_invoices
from backend.tests.test_bank_matching import setup
from backend.tests.test_bank_payments import active_store  # noqa: F401


def test_date_filter_precedes_bounded_invoice_slice_without_count(active_store):  # noqa: F811
    target, _ = setup(active_store, "invoice", amount="-100.30")
    historical = [target.model_copy(update={"id": f"old-{index:05d}", "invoice_date": date(2020, 1, 1)}) for index in range(10001)]
    reads = []
    engine = active_store.db.get_bind() if hasattr(active_store, "db") else None
    if engine:
        active_store.db.execute(InvoiceORM.__table__.insert(), [item.model_dump() for item in historical])
        active_store.db.commit()
        def capture(_, __, statement, *args):
            reads.append(statement)
        event.listen(engine, "before_cursor_execute", capture)
    else:
        active_store.invoices.update({item.id: item for item in historical})
    try:
        result = filtered_invoices(active_store, skip=0, limit=1, filters={"supplier": target.supplier, "status": "open"},
            sort_by="invoice_date", descending=False, date_from=date(2026, 1, 1), date_to=date(2026, 12, 31))
    finally:
        if engine:
            event.remove(engine, "before_cursor_execute", capture)
    assert [item.id for item in result] == [target.id]
    if engine:
        assert len(reads) == 1 and "LIMIT" in reads[0] and "invoice_date >=" in reads[0]
        assert "count(" not in reads[0].lower()
