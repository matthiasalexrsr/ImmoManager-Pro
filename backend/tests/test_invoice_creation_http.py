"""New invoice HTTP records cannot manufacture an unrecorded paid balance."""

from datetime import date

from backend.models import InvoiceCreate
from backend.services.portfolio_scope import scope_context
from backend.tests.test_form_drafts_http import draft_http  # noqa: F401


def test_full_api_new_invoice_status_requires_receipts_and_rejection_leaves_no_rows(draft_http):  # noqa: F811
    active = draft_http
    headers = active.headers(active.owner)
    body = {"property_id": active.properties[0].id, "supplier": "Synthetic new invoice",
        "invoice_date": "2026-01-01", "net_amount": 100.30, "gross_amount": 100.30, "vat_rate": 0}
    for invalid in ("paid", "partial", "PAID", " partial "):
        response = active.client.post("/api/v1/invoices", headers=headers, json={**body, "status": invalid})
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "INVOICE_PAYMENT_REQUIRED"
    for invalid in ("unknown", "partiallyPaid"):
        response = active.client.post("/api/v1/invoices", headers=headers, json={**body, "status": invalid})
        assert response.status_code == 422 and response.json()["error"]["code"] == "INVOICE_STATUS_INVALID"
    assert active.client.get("/api/v1/invoices", headers=headers).json() == []
    for allowed in ("open", "overdue", "cancelled"):
        response = active.client.post("/api/v1/invoices", headers=headers, json={**body, "status": allowed})
        assert response.status_code == 201, response.text
        invoice = response.json()
        assert invoice["amount_paid"] == 0 and invoice["status"] == allowed
        assert active.client.get(f"/api/v1/invoices/{invoice['id']}/payments", headers=headers).json() == []
    assert len(active.client.get("/api/v1/invoices", headers=headers).json()) == 3
    active.assert_connections_returned()


def test_legacy_internal_invoice_balance_remains_readable_without_invented_receipt(draft_http):  # noqa: F811
    active = draft_http
    with scope_context(None):
        legacy = active.store.create_invoice(InvoiceCreate(property_id=active.properties[0].id,
            supplier="Synthetic explicitly carried-over balance", invoice_date=date(2026, 1, 1),
            net_amount=100.30, gross_amount=100.30, vat_rate=0, status="paid"))
        if active.engine is not None:
            active.store.db.remove()
    headers = active.headers(active.owner)
    opened = active.client.get(f"/api/v1/invoices/{legacy.id}", headers=headers)
    assert opened.status_code == 200
    assert opened.json()["amount_paid"] == 100.30 and opened.json()["status"] == "paid"
    assert active.client.get(f"/api/v1/invoices/{legacy.id}/payments", headers=headers).json() == []
    metadata = active.client.patch(f"/api/v1/invoices/{legacy.id}", headers={**headers, "If-Match": opened.headers["etag"]},
        json={"notes": "Metadata edit preserves the carried-over record"})
    assert metadata.status_code == 200, metadata.text
    assert metadata.json()["amount_paid"] == 100.30 and metadata.json()["status"] == "paid"
    active.assert_connections_returned()
