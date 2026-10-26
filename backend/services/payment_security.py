"""Bank-detail four-eyes check, independent of factual/arithmetic invoice checks.

No payment is sent. Authorizations become inapplicable automatically when the
invoice, payable amount, payee version or approval policy changes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, text

from .. import auth
from ..db.orm_models import UserORM
from ..db.payment_security_models import PaymentAuthorizationORM as Authorization
from ..db.payment_security_models import PaymentRecipientORM as Recipient
from ..db.payment_security_models import PaymentSecurityEventORM as ModeEvent
from ..db.payment_security_models import PaymentSecuritySettingsORM as Settings
from ..db.payment_security_models import PaymentTotpAttemptORM as TotpAttempt
from ..db.payment_security_models import PaymentTotpUseORM as TotpUse
from ..domain.clock import local_today
from ..domain.money import ZERO, money
from ..payment_security_models import AuthorizePayment, RecipientChange, SecurityModeChange
from . import document_versions as archive
from . import invoice_review
from .e_invoice.service import digest
from .integrations import connection_storage as db
from .maintenance_rows import Rows
from .portfolio_scope import scope_context, scope_from_user
from .workspace_contexts import bound_actor

FINANCIAL_ROLES = {"eigentuemer", "verwalter", "buchhaltung"}


@contextmanager
def work(store, actor_id, *, write=False, invoice_id=None, key=None):
    area = f"/invoices/{invoice_id}/payment-authorization" if invoice_id else "/payment-security/settings"
    with archive.work(store, actor_id, write_areas=(area,) if write else ()) as unit:
        with scope_context(scope_from_user(unit.user)), bound_actor(unit.user):
            if write and key and unit.db is not None and unit.db.get_bind().dialect.name == "postgresql":
                token = int.from_bytes(hashlib.sha256(("payment:" + actor_id + ":" + key).encode()).digest()[:8], "big", signed=True)
                unit.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": token})
            if write and invoice_id and not Rows.of(unit).lock("invoices", invoice_id):
                raise HTTPException(404, "Rechnung nicht gefunden.")
            yield unit


def _records(unit, model, **filters):
    if unit.db is not None:
        return list(unit.db.scalars(select(model).filter_by(**filters)))
    return [row for row in db.memory(unit, model).values() if all(getattr(row, key) == value for key, value in filters.items())]


def mode(unit):
    settings = db.row(unit, Settings, "default", required=False)
    requested = bool(settings and settings.single_user_mode)
    count = 0
    if requested:
        if unit.db is not None:
            count = len(list(unit.db.scalars(select(UserORM.id).where(UserORM.is_active.is_(True), UserORM.role.in_(FINANCIAL_ROLES)))))
        else:
            count = sum(user.is_active and user.role in FINANCIAL_ROLES for user in auth.list_users())
    return {"single_user_mode": requested, "effective_mode": "single_user" if requested and count == 1 else "four_eyes",
            "revision": settings.revision if settings else 0,
            "reason": settings.reason if settings else "Vier-Augen-Prüfung ist der Standard.",
            "inactive_reason": "Mehrere aktive Finanzbenutzer: Vier-Augen-Prüfung bleibt erforderlich." if requested and count != 1 else None}


def _state(unit, invoice_id, *, today=None):
    rows = Rows.of(unit)
    invoice = rows.require("invoices", invoice_id, "Rechnung nicht gefunden")
    review = next(iter(rows.find("invoice_reviews", invoice_id=invoice_id)), None)
    recipients = _records(unit, Recipient, invoice_id=invoice_id)
    current = max(recipients, key=lambda row: row.number, default=None)
    settlement = invoice_review.settlements(rows, [invoice], today or local_today())[invoice_id]
    amount = settlement.open - (settlement.skonto_amount if settlement.skonto_available and not settlement.paid else ZERO)
    policy = mode(unit)
    facts = {"invoice": invoice.model_dump(mode="json"), "review": review.model_dump(mode="json") if review else None,
             "recipient_id": current.id if current else None, "recipient_number": current.number if current else None,
             "amount": str(money(amount)), "policy_revision": policy["revision"], "mode": policy["effective_mode"]}
    fingerprint = digest(facts)
    eligible = bool(review and review.kind == "invoice" and review.status in {"approved", "partially_approved"}
                    and amount > 0 and invoice.status != "cancelled")
    approvals = _records(unit, Authorization, invoice_id=invoice_id)
    approved = max((row for row in approvals if row.fingerprint == fingerprint), key=lambda row: row.created_at, default=None)
    blockers = []
    if not eligible:
        blockers.append("Die Rechnung benötigt eine fachliche Freigabe und einen offenen Zahlbetrag.")
    if current is None:
        blockers.append("Ein versionierter Zahlungsempfänger fehlt.")
    if eligible and current and approved is None:
        blockers.append("Die Bankdatenfreigabe für diesen Betrag und Datensatzstand fehlt.")
    return {"revision": fingerprint, "invoice_id": invoice_id, "amount": float(money(amount)), "eligible": eligible,
            "recipient": db.values(current) if current else None,
            "authorization": db.values(approved) if approved else None,
            "authorized": bool(eligible and current and approved), "blockers": blockers,
            "policy": policy, "evidence": facts,
            "recipient_history": [db.values(row) for row in sorted(recipients, key=lambda row: row.number)],
            "authorization_history": [db.values(row) for row in sorted(approvals, key=lambda row: row.created_at)]}


def _public(state):
    result = {key: value for key, value in state.items() if key != "evidence"}
    for name in ("recipient_history", "authorization_history"):
        result[name] = [{k: v for k, v in row.items() if k not in {"request_sha256", "idempotency_key", "evidence"}} for row in result[name]]
    for name in ("recipient", "authorization"):
        if result[name]:
            result[name] = {k: v for k, v in result[name].items() if k not in {"request_sha256", "idempotency_key", "evidence"}}
    return result


def read(store, actor_id, invoice_id):
    with work(store, actor_id) as unit:
        return _public(_state(unit, invoice_id))


def proposal_gate(store, invoice_id, *, today=None):
    sql = getattr(store, "db", None)
    unit = archive.Unit(store, sql, {}, None if sql is not None else archive.memory_archive(store))
    return _public(_state(unit, invoice_id, today=today))


def _expected(state, expected):
    if state["revision"] != expected:
        raise HTTPException(409, "Betrag, Empfänger oder Rechnungsstand wurden geändert. Bitte erneut prüfen.")


def change_recipient(store, actor_id, invoice_id, command: RecipientChange):
    with work(store, actor_id, write=True, invoice_id=invoice_id, key=command.idempotency_key) as unit:
        request_hash = digest({"invoice_id": invoice_id, **command.model_dump(mode="json")})
        old = db.find_one(unit, Recipient, created_by=actor_id, idempotency_key=command.idempotency_key)
        if old:
            if old.request_sha256 != request_hash:
                raise HTTPException(409, "Die Wiederholungskennung gehört zu einer anderen Empfängeränderung.")
            return _public(_state(unit, invoice_id))
        state = _state(unit, invoice_id)
        _expected(state, command.expected_revision)
        _insert_recipient(unit, invoice_id, command.name, command.iban, command.bic, command.reason,
                          command.idempotency_key, request_hash, (state["recipient"] or {}).get("number", 0) + 1)
        return _public(_state(unit, invoice_id))


def _insert_recipient(unit, invoice_id, name, iban, bic, reason, key, request_hash, number):
    db.put(unit, Recipient, {"id": str(uuid4()), "invoice_id": invoice_id, "number": number,
        "name": name, "iban": iban, "bic": bic, "reason": reason, "created_by": unit.actor_id,
        "idempotency_key": key, "request_sha256": request_hash, "created_at": db.now()})


def import_suggestion(unit, invoice_id, reading):
    """A parsed IBAN is only an unapproved version, never a bank authorization."""
    accounts = reading["bank_accounts"]
    if len(accounts) != 1:
        return
    account = accounts[0]
    from pydantic import ValidationError
    try:
        candidate = RecipientChange(expected_revision="0" * 64, idempotency_key=uuid4().hex,
            name=account["name"] or reading["supplier"], iban=account["iban"], bic=account["bic"] or None,
            reason="Ungeprüfte Bankangaben aus dem Originalbeleg übernommen.")
    except ValidationError:
        return
    _insert_recipient(unit, invoice_id, candidate.name, candidate.iban, candidate.bic, candidate.reason,
                      candidate.idempotency_key, digest(candidate.model_dump(mode="json")), 1)


def _consume_totp(unit, code, purpose):
    user = unit.user
    if not user.get("totp_enabled") or not user.get("totp_secret") or not code:
        raise HTTPException(403, "Für diese Einzelbenutzeraktion ist eine erneute Zwei-Faktor-Bestätigung erforderlich.")
    try:
        secret = base64.b32decode(user["totp_secret"], casefold=True)
        step = int(time.time()) // 30
        counter = None
        for value in (step, step - 1, step + 1):
            digest_bytes = hmac.new(secret, struct.pack(">Q", value), "sha1").digest()  # RFC 6238 authenticator compatibility
            offset = digest_bytes[-1] & 15
            number = (struct.unpack(">I", digest_bytes[offset:offset + 4])[0] & 0x7fffffff) % 1000000
            if hmac.compare_digest(f"{number:06d}", code):
                counter = value
                break
    except (ValueError, TypeError):
        counter = None
    if counter is None:
        raise HTTPException(403, "Der Zwei-Faktor-Code ist ungültig oder abgelaufen.")
    if db.find_one(unit, TotpUse, user_id=unit.actor_id, counter=counter):
        raise HTTPException(409, "Dieser Zwei-Faktor-Code wurde bereits verwendet. Bitte den nächsten Code abwarten.")
    proof = db.put(unit, TotpUse, {"id": str(uuid4()), "user_id": unit.actor_id, "counter": counter,
                                 "purpose": purpose, "created_at": db.now()})
    return proof.id


def authorize(store, actor_id, invoice_id, command: AuthorizePayment):
    request_hash = digest({"invoice_id": invoice_id, **command.model_dump(mode="json", exclude={"totp_code"})})
    # Count guesses in a separate committed transaction. A rejected financial
    # command must not roll the admission counter back. Successful replays do
    # not consume another attempt or demand another TOTP.
    with work(store, actor_id) as read_unit:
        old = db.find_one(read_unit, Authorization, created_by=actor_id, idempotency_key=command.idempotency_key)
        if old and old.request_sha256 == request_hash:
            return _public(_state(read_unit, invoice_id))
    if command.totp_code:
        _reserve_totp_attempt(store, actor_id, invoice_id=invoice_id)
    with work(store, actor_id, write=True, invoice_id=invoice_id, key=command.idempotency_key) as unit:
        old = db.find_one(unit, Authorization, created_by=actor_id, idempotency_key=command.idempotency_key)
        if old:
            if old.request_sha256 != request_hash:
                raise HTTPException(409, "Die Wiederholungskennung gehört zu einer anderen Freigabe.")
            return _public(_state(unit, invoice_id))
        state = _state(unit, invoice_id)
        _expected(state, command.expected_revision)
        recipient = state["recipient"]
        if not state["eligible"] or not recipient:
            raise HTTPException(409, "Vor der Bankdatenfreigabe fehlen Empfänger, Rechnungsfreigabe oder offener Betrag.")
        if len(command.reason.strip()) < 10 or len(command.bank_verification.strip()) < 20:
            raise HTTPException(422, "Begründung und dokumentierte Gegenprüfung der Bankverbindung sind erforderlich.")
        selected_mode = state["policy"]["effective_mode"]
        if selected_mode == "four_eyes" and recipient["created_by"] == actor_id:
            raise HTTPException(403, "Vier-Augen-Prüfung: Die Person, die diese Bankdaten erfasst hat, darf sie nicht selbst freigeben.")
        proof_id = _consume_totp(unit, command.totp_code, "invoice:" + invoice_id) if selected_mode == "single_user" else None
        db.put(unit, Authorization, {"id": str(uuid4()), "invoice_id": invoice_id, "recipient_id": recipient["id"],
            "fingerprint": state["revision"], "amount": state["amount"], "mode": selected_mode,
            "reason": command.reason.strip(), "verification": command.bank_verification.strip(),
            "evidence": {"facts": state["evidence"], "totp_use_id": proof_id},
            "created_by": actor_id, "idempotency_key": command.idempotency_key, "request_sha256": request_hash, "created_at": db.now()})
        return _public(_state(unit, invoice_id))


def read_settings(store, actor_id):
    with work(store, actor_id) as unit:
        result = mode(unit)
        if unit.user["role"] == "eigentuemer":
            result["history"] = [{key: value for key, value in db.values(row).items()
                                  if key not in {"request_sha256", "idempotency_key"}}
                                 for row in sorted(_records(unit, ModeEvent), key=lambda row: row.revision)]
        return result


def set_mode(store, actor_id, command: SecurityModeChange):
    request_hash = digest({"actor_id": actor_id, **command.model_dump(mode="json", exclude={"totp_code"})})
    with work(store, actor_id) as read_unit:
        if read_unit.user["role"] != "eigentuemer":
            raise HTTPException(403, "Nur die Inhaberin oder der Inhaber darf diesen Sicherheitsmodus ändern.")
        old = db.find_one(read_unit, ModeEvent, created_by=actor_id, idempotency_key=command.idempotency_key)
        if old and old.request_sha256 == request_hash:
            return mode(read_unit)
    if command.single_user_mode and command.totp_code:
        _reserve_totp_attempt(store, actor_id)
    with work(store, actor_id, write=True, key="security-settings") as unit:
        if unit.user["role"] != "eigentuemer":
            raise HTTPException(403, "Nur die Inhaberin oder der Inhaber darf diesen Sicherheitsmodus ändern.")
        old = db.find_one(unit, ModeEvent, created_by=actor_id, idempotency_key=command.idempotency_key)
        if old:
            if old.request_sha256 != request_hash:
                raise HTTPException(409, "Diese Wiederholungskennung gehört zu einer anderen Einstellung.")
            return mode(unit)
        settings = db.row(unit, Settings, "default", lock=True, required=False)
        if (settings.revision if settings else 0) != command.expected_revision:
            raise HTTPException(409, "Die Sicherheitseinstellung wurde inzwischen geändert.")
        if len(command.reason.strip()) < 20:
            raise HTTPException(422, "Eine nachvollziehbare Begründung ist erforderlich.")
        proof_id = _consume_totp(unit, command.totp_code, "single-user-mode") if command.single_user_mode else None
        db.put(unit, Settings, {"id": "default", "single_user_mode": command.single_user_mode,
            "revision": command.expected_revision + 1, "reason": command.reason.strip(), "updated_by": actor_id, "updated_at": db.now()})
        selected = mode(unit)
        if command.single_user_mode and selected["effective_mode"] != "single_user":
            raise HTTPException(409, "Einzelbenutzermodus setzt genau einen aktiven Finanzbenutzer voraus.")
        db.put(unit, ModeEvent, {"id": str(uuid4()), "revision": command.expected_revision + 1,
            "totp_use_id": proof_id,
            "single_user_mode": command.single_user_mode, "reason": command.reason.strip(), "created_by": actor_id,
            "idempotency_key": command.idempotency_key, "request_sha256": request_hash, "created_at": db.now()})
        return selected


def _reserve_totp_attempt(store, actor_id, *, invoice_id=None):
    with work(store, actor_id, write=True, invoice_id=invoice_id, key="totp-admission") as unit:
        cutoff = db.now() - timedelta(minutes=5)
        if unit.db is not None:
            from sqlalchemy import func
            count = unit.db.scalar(select(func.count()).select_from(TotpAttempt).where(
                TotpAttempt.user_id == actor_id, TotpAttempt.created_at > cutoff))
        else:
            count = sum(row.created_at > cutoff for row in _records(unit, TotpAttempt, user_id=actor_id))
        if count >= 5:
            raise HTTPException(429, "Zu viele Zwei-Faktor-Versuche. Bitte nach fünf Minuten erneut versuchen.", headers={"Retry-After": "300"})
        db.put(unit, TotpAttempt, {"id": str(uuid4()), "user_id": actor_id, "created_at": db.now()})
