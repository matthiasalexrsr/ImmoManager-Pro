"""Real joined receipt history, bounded pages and explicit scope failures."""
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import event

from backend.models import AccountPatch
from backend.services.bank_matching import MatchError
from backend.services.payment_history import PaymentHistoryPage, PaymentHistoryQuery, payment_history
from backend.services.payments import PaymentCreate, PaymentReversalCreate
from backend.services.portfolio_scope import scope_context
from backend.tests.test_bank_imports_http import bank_http  # noqa: F401 fixture
from backend.tests.test_bank_matching import setup
from backend.tests.test_bank_matching_http import matching_http  # noqa: F401 fixture
from backend.tests.test_bank_payments import active_store  # noqa: F401


def test_invoice_and_bank_history_pages_retain_reversals_without_count_or_n_plus_one(active_store):  # noqa: F811
    invoice, booking = setup(active_store, "invoice", amount="-100.30")
    receipts = [active_store.record_payment("invoice", invoice.id, PaymentCreate(idempotency_key=str(uuid4()), amount="1.01",
        booking_id=booking.id, payment_date=booking.booking_date)) for _ in range(13)]
    reversed_receipt = receipts[2]
    active_store.reverse_payment("invoice", invoice.id, reversed_receipt.id, PaymentReversalCreate(idempotency_key=str(uuid4()),
        reversal_date=date(2026, 9, 6), reason="Synthetic retained correction"))
    reads = []
    engine = active_store.db.get_bind() if hasattr(active_store, "db") else None
    def capture(_, __, statement, *args):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            reads.append(statement)
    if engine:
        event.listen(engine, "before_cursor_execute", capture)
    try:
        first = payment_history(active_store, "invoice", invoice.id, PaymentHistoryQuery(page_size=2))
    finally:
        if engine:
            event.remove(engine, "before_cursor_execute", capture)
    PaymentHistoryPage.model_validate(first)
    assert first["has_more"] and len(first["items"]) == 2
    if engine:
        assert len(reads) <= 2 and any("LIMIT" in statement and "payment_reversals" in statement for statement in reads)
        assert not any("count(" in statement.lower() for statement in reads)
    seen = list(first["items"])
    page = first
    while page["has_more"]:
        page = payment_history(active_store, "invoice", invoice.id, PaymentHistoryQuery(page_size=2, cursor=page["next_cursor"]))
        seen.extend(page["items"])
    expected = sorted(receipts, key=lambda item: (item.created_at.replace(tzinfo=None), item.id.encode()))
    assert [receipt.id for receipt in seen] == [receipt.id for receipt in expected]
    assert next(item for item in seen if item.id == reversed_receipt.id).reversal.reason == "Synthetic retained correction"
    bank = payment_history(active_store, "booking", booking.id, PaymentHistoryQuery(page_size=25))
    assert len(bank["items"]) == 13 and not bank["has_more"]
    with pytest.raises(MatchError) as foreign:
        payment_history(active_store, "booking", booking.id, PaymentHistoryQuery(cursor=first["next_cursor"]))
    assert foreign.value.code == "MATCH_SOURCE_CHANGED"


def test_legacy_invoice_history_http_shape_and_bounded_readonly_shape(matching_http):  # noqa: F811
    client, store, _, finance, readonly, _, _, target, booking, _ = matching_http
    for _ in range(3):
        store.record_payment("invoice", target.id, PaymentCreate(idempotency_key=str(uuid4()), amount="1.01",
            booking_id=booking.id, payment_date=booking.booking_date))
    path = f"/api/v1/invoices/{target.id}/payments"
    legacy = client.get(path, headers=readonly)
    assert legacy.status_code == 200 and isinstance(legacy.json(), list) and len(legacy.json()) == 3
    page = client.get(path + "?page_size=2", headers=readonly)
    assert page.status_code == 200, page.text
    assert page.json()["has_more"] and len(page.json()["items"]) == 2
    source = client.get(f"/api/v1/bookings/{booking.id}/allocations?page_size=2", headers=readonly)
    assert source.status_code == 200, source.text
    assert source.json()["items"][0]["entity_type"] == "invoice"


def test_visible_invoice_does_not_publish_a_false_empty_history_after_bank_parent_moves(matching_http):  # noqa: F811
    client, store, _, finance, _, _, accounts, target, booking, _ = matching_http
    store.record_payment("invoice", target.id, PaymentCreate(idempotency_key=str(uuid4()), amount="1.01",
        booking_id=booking.id, payment_date=booking.booking_date))
    with scope_context(None):
        store._patch_entity("account", accounts[0].id, AccountPatch(portfolio_id=accounts[1].portfolio_id))
    response = client.get(f"/api/v1/invoices/{target.id}/payments?page_size=25", headers=finance)
    assert response.status_code == 403, response.text
    assert "payment_history_scope_incomplete" in response.text
    with scope_context(None):
        assert len(store.list_payments("invoice", target.id)) == 1

