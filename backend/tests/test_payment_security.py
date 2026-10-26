"""Real invoice/payee/settlement state and atomic TOTP approval regressions."""
import base64
import hashlib
import hmac
import struct
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from archive_helpers import purge_originals, purge_payment_evidence
from fastapi import HTTPException
from sqlalchemy import delete

from backend import auth
from backend.db.payment_security_models import (
    PaymentAuthorizationORM,
    PaymentRecipientORM,
    PaymentSecuritySettingsORM,
    PaymentTotpUseORM,
)
from backend.dependencies import store
from backend.invoice_review_models import CheckRequest, DecisionRequest, InvoiceDraft, ReceiptRequest
from backend.maintenance_models import InvoicePaymentCreate
from backend.models import AccountCreate, BookingCreate, PortfolioCreate, PropertyCreate
from backend.payment_security_models import AuthorizePayment, RecipientChange, SecurityModeChange
from backend.services import invoice_review, maintenance_projects
from backend.services import payment_security as service
from backend.services.data_snapshot import clear_business_data

SECRET = "JBSWY3DPEHPK3PXP"
NOW = 1793000000


def _purge():
    purge_payment_evidence(store)
    models = [PaymentAuthorizationORM, PaymentRecipientORM, PaymentTotpUseORM, PaymentSecuritySettingsORM]
    if hasattr(store, "db"):
        for model in models:
            store.db.execute(delete(model))
        store.db.commit()
    else:
        for model in models:
            store.__dict__.get("_integration_connections", {}).pop(model.__tablename__, None)
    purge_originals(store)
    clear_business_data(store)
    auth.clear_users()


@pytest.fixture
def invoice():
    _purge()
    owner = auth.register_user("owner-bank", "owner@example.test", "Owner", "Secret123", "eigentuemer")
    portfolio = store.create_portfolio(PortfolioCreate(name="Bankpruefung"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Testhaus", property_type="residential",
        address_line="Testweg 1", postal_code="01099", city="Dresden"))
    data = invoice_review.start_review(store, None, ReceiptRequest(invoice=InvoiceDraft(property_id=prop.id,
        supplier="Testlieferant", invoice_date=date(2026, 10, 1), invoice_number="BANK-1", net_amount=100,
        vat_amount=19, gross_amount=119), property_id=prop.id), owner.id)
    identifier = data["invoice"]["id"]
    invoice_review.factual_check(store, identifier, CheckRequest(result="confirmed"), owner.id)
    invoice_review.arithmetic_check(store, identifier, CheckRequest(result="confirmed", checklist={
        key: True for key in ("supplier_name_address", "recipient_name_address", "tax_number", "description", "service_date", "discount_agreement")}), owner.id)
    invoice_review.decide(store, identifier, DecisionRequest(decision="approve"), owner.id)
    yield owner, identifier, prop, portfolio
    _purge()


def recipient(invoice, *, iban="DE89370400440532013000"):
    owner, identifier, _, _ = invoice
    current = service.read(store, owner.id, identifier)
    return service.change_recipient(store, owner.id, identifier, RecipientChange(expected_revision=current["revision"],
        idempotency_key=uuid4().hex, name="Testlieferant", iban=iban, reason="Bankverbindung laut Originalbeleg erfasst."))


def command(state, **changes):
    return AuthorizePayment(expected_revision=state["revision"], idempotency_key=uuid4().hex,
        reason="Originalbeleg und Zahlbetrag geprüft.", bank_verification="Bankverbindung durch Rückruf unter bekannter Vertragsnummer bestätigt.", **changes)


def other_user():
    return auth.register_user("second-bank", "second@example.test", "Second", "Secret123", "buchhaltung")


def otp(moment):
    digest = hmac.new(base64.b32decode(SECRET), struct.pack(">Q", moment // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return f'{(struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff) % 1000000:06d}'


def test_missing_recipient_and_standard_self_approval_are_blocked(invoice):
    owner, identifier, _, _ = invoice
    assert not service.read(store, owner.id, identifier)["authorized"]
    current = recipient(invoice)
    with pytest.raises(HTTPException) as error:
        service.authorize(store, owner.id, identifier, command(current))
    assert error.value.status_code == 403


def test_second_person_approves_exact_state_and_replay_is_safe(invoice):
    _, identifier, _, _ = invoice
    current = recipient(invoice)
    before = invoice_review.payment_proposals(store)
    assert before["items"] == [] and before["blocked_total"] == 1
    second = other_user()
    cmd = command(current)
    approved = service.authorize(store, second.id, identifier, cmd)
    again = service.authorize(store, second.id, identifier, cmd)
    assert approved["authorized"] and approved["amount"] == 119
    assert again["authorization"]["id"] == approved["authorization"]["id"]
    assert len(again["authorization_history"]) == 1
    after = invoice_review.payment_proposals(store)
    assert after["total"] == 1 and after["blocked_total"] == 0
    assert after["items"][0]["recipient"]["iban"] == "DE89370400440532013000"


def test_new_payee_invalidates_approval_and_stale_revision_is_refused(invoice):
    owner, identifier, _, _ = invoice
    current = recipient(invoice)
    second = other_user()
    service.authorize(store, second.id, identifier, command(current))
    updated = recipient(invoice, iban="DE02120300000000202051")
    assert not updated["authorized"] and updated["recipient"]["number"] == 2
    with pytest.raises(HTTPException) as error:
        service.authorize(store, second.id, identifier, command(current))
    assert error.value.status_code == 409
    assert service.authorize(store, second.id, identifier, command(updated))["authorized"]


def test_recorded_partial_payment_invalidates_old_amount(invoice):
    owner, identifier, prop, portfolio = invoice
    current = recipient(invoice)
    second = other_user()
    service.authorize(store, second.id, identifier, command(current))
    account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Testkonto", account_type="bank"))
    booking = store.create_booking(BookingCreate(account_id=account.id, property_id=prop.id, booking_date=date(2026, 10, 2), amount=-20))
    maintenance_projects.add_invoice_payment(store, identifier, InvoicePaymentCreate(booking_id=booking.id, amount=20), owner.id)
    after = service.read(store, owner.id, identifier)
    assert after["amount"] == 99 and not after["authorized"]


def test_single_user_requires_activation_totp_and_counter_replay_protection(invoice, monkeypatch):
    owner, identifier, _, _ = invoice
    recipient(invoice)
    auth.update_user(owner.id, {"totp_enabled": True, "totp_secret": SECRET})
    monkeypatch.setattr(service.time, "time", lambda: NOW)
    with pytest.raises(HTTPException):
        service.set_mode(store, owner.id, SecurityModeChange(expected_revision=0, idempotency_key=uuid4().hex, single_user_mode=True,
            reason="Ich betreibe die Verwaltung dauerhaft allein."))
    enabled = service.set_mode(store, owner.id, SecurityModeChange(expected_revision=0, idempotency_key=uuid4().hex, single_user_mode=True,
        reason="Ich betreibe die Verwaltung dauerhaft allein.", totp_code=otp(NOW)))
    assert enabled["effective_mode"] == "single_user"
    current = service.read(store, owner.id, identifier)
    with pytest.raises(HTTPException):
        service.authorize(store, owner.id, identifier, command(current))
    with pytest.raises(HTTPException) as error:
        service.authorize(store, owner.id, identifier, command(current, totp_code=otp(NOW)))
    assert error.value.status_code == 409
    monkeypatch.setattr(service.time, "time", lambda: NOW + 30)
    cmd = command(current, totp_code=otp(NOW + 30))
    approved = service.authorize(store, owner.id, identifier, cmd)
    assert approved["authorized"] and approved["authorization"]["mode"] == "single_user"
    assert service.authorize(store, owner.id, identifier, cmd)["authorized"]
    assert "totp_code" not in str(approved)


def test_additional_financial_user_disables_single_user_exception(invoice, monkeypatch):
    owner, identifier, _, _ = invoice
    recipient(invoice)
    auth.update_user(owner.id, {"totp_enabled": True, "totp_secret": SECRET})
    monkeypatch.setattr(service.time, "time", lambda: NOW)
    service.set_mode(store, owner.id, SecurityModeChange(expected_revision=0, idempotency_key=uuid4().hex, single_user_mode=True,
        reason="Ich betreibe die Verwaltung dauerhaft allein.", totp_code=otp(NOW)))
    other_user()
    current = service.read(store, owner.id, identifier)
    assert current["policy"]["effective_mode"] == "four_eyes"
    with pytest.raises(HTTPException) as error:
        service.authorize(store, owner.id, identifier, command(current, totp_code=otp(NOW + 30)))
    assert error.value.status_code == 403


def test_role_revocation_is_rechecked_before_recipient_change(invoice):
    owner, identifier, _, _ = invoice
    current = recipient(invoice)
    second = other_user()
    auth.update_user(second.id, {"role": "readonly"})
    with pytest.raises(HTTPException) as error:
        service.authorize(store, second.id, identifier, command(current))
    assert error.value.status_code == 403
    assert not service.read(store, owner.id, identifier)["authorized"]


def test_failed_totp_attempts_survive_rollback_and_are_limited(invoice, monkeypatch):
    owner, _, _, _ = invoice
    auth.update_user(owner.id, {"totp_enabled": True, "totp_secret": SECRET})
    monkeypatch.setattr(service.time, "time", lambda: NOW)
    monkeypatch.setattr(service.db, "now", lambda: datetime.fromtimestamp(service.time.time(), timezone.utc).replace(tzinfo=None))
    for _ in range(5):
        with pytest.raises(HTTPException) as error:
            service.set_mode(store, owner.id, SecurityModeChange(expected_revision=0, idempotency_key=uuid4().hex,
                single_user_mode=True, reason="Ich betreibe die Verwaltung dauerhaft allein.", totp_code="000000"))
        assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        service.set_mode(store, owner.id, SecurityModeChange(expected_revision=0, idempotency_key=uuid4().hex,
            single_user_mode=True, reason="Ich betreibe die Verwaltung dauerhaft allein.", totp_code=otp(NOW)))
    assert error.value.status_code == 429
    monkeypatch.setattr(service.time, "time", lambda: NOW + 301)
    cmd = SecurityModeChange(expected_revision=0, idempotency_key=uuid4().hex,
        single_user_mode=True, reason="Ich betreibe die Verwaltung dauerhaft allein.", totp_code=otp(NOW + 301))
    first = service.set_mode(store, owner.id, cmd)
    replay = service.set_mode(store, owner.id, cmd)
    assert first == replay and replay["revision"] == 1
