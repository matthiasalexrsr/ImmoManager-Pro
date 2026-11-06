"""Dispute resolution uses only credits effective on its resolution day."""
from datetime import date

import pytest
from fastapi import HTTPException

from backend.invoice_review_models import DisputeResolution, InvoiceReview
from backend.models import InvoiceCreate
from backend.services import invoice_review
from backend.services.maintenance_rows import Rows
from backend.tests.test_financial_input_and_cutoff import estate as _estate_fixture  # noqa: F401


@pytest.fixture(name="estate")
def _finance_estate(_estate_fixture):  # noqa: F811 - pytest injects the imported parametrized fixture
    return _estate_fixture


@pytest.mark.parametrize("credit_day", [date(2026, 1, 31), date(2026, 2, 1)])
def test_dispute_cannot_be_closed_with_a_credit_effective_tomorrow(estate, monkeypatch, credit_day):
    store, prop, _ = estate
    today = date(2026, 1, 31)
    monkeypatch.setattr(invoice_review, "local_today", lambda: today)
    original = store.create_invoice(InvoiceCreate(property_id=prop.id, supplier="Lieferant",
        invoice_date=date(2026, 1, 1), net_amount=100, vat_rate=0, gross_amount=100))
    note = store.create_invoice(InvoiceCreate(property_id=prop.id, supplier="Lieferant",
        invoice_date=credit_day, net_amount=20, vat_rate=0, gross_amount=20))
    rows = Rows.reading(store)
    rows.add("invoice_reviews", InvoiceReview(id="disputed-review", invoice_id=original.id,
        received_on=today, status="partially_approved", approved_amount=80, dispute_status="open"))
    rows.add("invoice_reviews", InvoiceReview(id="credit-review", invoice_id=note.id,
        received_on=today, kind="credit_note", credit_for_invoice_id=original.id,
        status="approved", approved_amount=20))
    if hasattr(store, "db"):
        store.db.commit()
    request = DisputeResolution(outcome="credit", reason="Mit Gutschrift erledigt")
    if credit_day > today:
        with pytest.raises(HTTPException) as error:
            invoice_review.resolve_dispute(store, original.id, request, actor_id=None)
        assert error.value.status_code == 409
        current = Rows.reading(store)
        assert current.get("invoice_reviews", "disputed-review").dispute_status == "open"
        assert current.find("invoice_review_events", invoice_id=original.id) == []
    else:
        resolved = invoice_review.resolve_dispute(store, original.id, request, actor_id=None)
        assert resolved["dispute_status"] == "resolved"
        assert resolved["dispute_written_off"] == 0
