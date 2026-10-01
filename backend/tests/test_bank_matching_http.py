"""Fresh server roles, exact scopes and actual central invoice-payment routes."""
from datetime import date
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend import auth, dependencies
from backend.middleware import DBSessionMiddleware
from backend.models import BookingCreate, InvoiceCreate, PropertyCreate
from backend.routers import invoices
from backend.routers.bank_matching import router
from backend.routing import build_api_v1
from backend.services.bank_matching import MatchConfirm, SuggestionQuery, confirm_match, suggestions
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.tests.test_bank_imports_http import bank_http  # noqa: F401


@pytest.fixture
def matching_http(bank_http, monkeypatch):  # noqa: F811
    client, store, owner, finance, readonly, member, accounts, portfolios, engine = bank_http
    monkeypatch.setattr(invoices, "store", store)
    client.app.app.include_router(router, prefix="/api/v1")
    client.app.app.include_router(invoices.router, prefix="/api/v1", dependencies=[Depends(auth.require_auth)])
    with scope_context(None):
        prop = store.create_property(PropertyCreate(portfolio_id=portfolios[0].id, name="Supplier property", property_type="residential"))
        target = store.create_invoice(InvoiceCreate(property_id=prop.id, supplier="Synthetic supplier", invoice_number="INV-41",
            invoice_date=date(2026, 9, 1), net_amount=100.30, gross_amount=100.30, vat_rate=0))
        booking = store.create_booking(BookingCreate(account_id=accounts[0].id, booking_date=date(2026, 9, 5),
            amount=-100.30, payment_text="Supplier INV-41"))
    return client, store, owner, finance, readonly, member, accounts, target, booking, engine


def test_http_explicit_invoice_receipt_and_reversal_with_readonly_preview_and_no_automatic_cash(matching_http):
    client, store, _, finance, readonly, _, _, target, booking, _ = matching_http
    base = f"/api/v1/bookings/{booking.id}"
    assert client.get(base + "/suggestions?kind=invoice").status_code == 401
    assert client.get(base + "/suggestions?kind=invoice", headers=readonly).status_code == 200
    review = client.get(base + "/suggestions?kind=invoice", headers=finance).json()
    assert store.list_payments() == []
    command = {"review_token": review["items"][0]["review_token"], "amount": "40.10", "idempotency_key": str(uuid4())}
    assert client.post(base + "/matching", headers=readonly, json=command).status_code == 403
    receipt = client.post(base + "/matching", headers=finance, json=command)
    assert receipt.status_code == 201, receipt.text
    assert receipt.json()["entity_type"] == "invoice" and receipt.json()["amount"] == "40.10"
    replay = client.post(base + "/matching", headers=finance, json=command)
    assert replay.json()["id"] == receipt.json()["id"]
    history = client.get(f"/api/v1/invoices/{target.id}/payments", headers=readonly)
    assert len(history.json()) == 1
    reversed_response = client.post(f"/api/v1/invoices/{target.id}/payments/{receipt.json()['id']}/reversal", headers=finance,
        json={"idempotency_key": str(uuid4()), "reversal_date": "2026-09-06", "reason": "Explicit correction"})
    assert reversed_response.status_code == 201, reversed_response.text
    assert store.get_booking(booking.id).allocated_amount == 0
    assert store.get_invoice(target.id).amount_paid == 0 and len(store.list_bookings()) == 1


def test_invoice_status_edit_requires_receipt_and_returns_recoverable_conflict(matching_http):
    client, store, _, finance, _, _, _, target, _, _ = matching_http
    response = client.patch(f"/api/v1/invoices/{target.id}", headers=finance, json={"status": "paid"})
    assert response.status_code == 409, response.text
    assert store.get_invoice(target.id).status == "open" and not store.list_payments()
    edited = client.patch(f"/api/v1/invoices/{target.id}", headers=finance, json={"supplier": "Reviewed metadata"})
    assert edited.status_code == 200 and edited.json()["supplier"] == "Reviewed metadata"


def test_actual_application_router_publishes_one_scoped_invoice_receipt(matching_http, monkeypatch):
    _, store, _, finance, readonly, _, accounts, target, booking, _ = matching_http
    if hasattr(store, "db"):
        monkeypatch.setattr(dependencies, "_scoped_session", store.db)
    app = FastAPI()
    app.include_router(build_api_v1())
    with TestClient(DBSessionMiddleware(PortfolioScopeMiddleware(app))) as client:
        base = f"/api/v1/bookings/{booking.id}"
        assert client.get(base + "/suggestions?kind=invoice").status_code == 401
        page = client.get(base + "/suggestions?kind=invoice", headers=finance)
        assert page.status_code == 200, page.text
        assert page.json()["items"][0]["id"] == target.id
        assert store.list_payments() == []
        command = {"review_token": page.json()["items"][0]["review_token"],
                   "amount": "40.10", "idempotency_key": str(uuid4())}
        assert client.post(base + "/matching", headers=readonly, json=command).status_code == 403
        receipt = client.post(base + "/matching", headers=finance, json=command)
        assert receipt.status_code == 201, receipt.text
        replay = client.post(base + "/matching", headers=finance, json=command)
        assert replay.status_code == 201 and replay.json()["id"] == receipt.json()["id"]
        assert store.get_invoice(target.id).amount_paid == pytest.approx(40.10)
        assert store.get_booking(booking.id).allocated_amount == pytest.approx(40.10)
        assert len(store.list_bookings()) == len(store.list_payments()) == 1
        foreign = store.create_booking(BookingCreate(account_id=accounts[1].id,
            booking_date=date(2026, 9, 5), amount=-100.30))
        assert client.get(f"/api/v1/bookings/{foreign.id}/suggestions?kind=invoice",
            headers=finance).status_code == 404


@pytest.mark.parametrize("change", ["role", "scope", "account"])
def test_http_review_rechecks_actual_role_grants_and_current_account(matching_http, change):
    client, store, _, finance, _, member, accounts, _, booking, _ = matching_http
    base = f"/api/v1/bookings/{booking.id}"
    review = client.get(base + "/suggestions?kind=invoice", headers=finance).json()
    if change == "role":
        auth.update_user(member.id, {"role": "readonly"})
    elif change == "scope":
        auth.update_user(member.id, {"portfolio_ids": [accounts[1].portfolio_id]})
    else:
        from backend.models import AccountPatch
        with scope_context(None):
            store._patch_entity("account", accounts[0].id, AccountPatch(portfolio_id=accounts[1].portfolio_id))
    response = client.post(base + "/matching", headers=finance, json={"review_token": review["items"][0]["review_token"],
        "amount": "100.30", "idempotency_key": str(uuid4())})
    assert response.status_code in {403, 404, 409}, response.text
    with scope_context(None):
        assert not store.list_payments() and store.get_booking(booking.id).allocated_amount == 0


def test_sql_permission_change_after_receipt_flush_rolls_back_booking_and_invoice(matching_http, monkeypatch):
    _, store, _, _, _, member, _, target, booking, _ = matching_http
    if not hasattr(store, "db"):
        pytest.skip("Independent SQL receipt transaction; memory confirms under mutation RLock")
    from backend.repositories import payment_repo
    scope = scope_from_user(auth.get_user_by_id(member.id))
    page = suggestions(store, booking.id, SuggestionQuery(kind="invoice"), scope=scope)
    original = payment_repo.record_payment
    def revoked(*args, **kwargs):
        receipt = original(*args, **kwargs)
        # Avoid an artificial second SQLite writer blocked behind the current
        # receipt transaction. The real fresh auth lookup reports a changed
        # active principal immediately after the flush.
        current = auth.get_user_by_id(member.id)
        monkeypatch.setattr(auth, "get_user_by_id", lambda _: {**current, "role": "readonly"})
        return receipt
    monkeypatch.setattr(payment_repo, "record_payment", revoked)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as denied:
        confirm_match(store, booking.id, MatchConfirm(review_token=page["items"][0]["review_token"],
            amount="100.30", idempotency_key=str(uuid4())), scope=scope)
    assert denied.value.status_code == 403
    with scope_context(None):
        assert not store.list_payments()
        assert store.get_invoice(target.id).amount_paid == 0 and store.get_booking(booking.id).allocated_amount == 0
