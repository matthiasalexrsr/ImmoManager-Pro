"""Verify retained payee versions, approvals and step-up evidence offline."""
from decimal import Decimal

from sqlalchemy import inspect, select

from ..db.payment_security_models import PaymentAuthorizationORM as Authorization
from ..db.payment_security_models import PaymentRecipientORM as Recipient
from ..db.payment_security_models import PaymentSecurityEventORM as ModeEvent
from ..db.payment_security_models import PaymentSecuritySettingsORM as Settings
from ..db.payment_security_models import PaymentTotpAttemptORM as Attempt
from ..db.payment_security_models import PaymentTotpUseORM as TotpUse
from .e_invoice.service import digest
from .sepa_rules import iban_problem


def verify(connection) -> dict:
    models = (Recipient, Authorization, Settings, TotpUse, ModeEvent, Attempt)
    names = {model.__tablename__ for model in models}
    tables = set(inspect(connection).get_table_names())
    if not names & tables:
        return {"recipients": 0, "authorizations": 0, "mode_changes": 0}
    if not names <= tables:
        raise ValueError("Partial payment security evidence")
    recipients = {row["id"]: row for row in connection.execute(select(Recipient.__table__)).mappings()}
    proofs = {row["id"]: row for row in connection.execute(select(TotpUse.__table__)).mappings()}
    grouped: dict[str, list[int]] = {}
    for row in recipients.values():
        if iban_problem(row["iban"]) or not row["name"].strip():
            raise ValueError("Invalid retained recipient")
        grouped.setdefault(row["invoice_id"], []).append(row["number"])
    if any(sorted(numbers) != list(range(1, len(numbers) + 1)) for numbers in grouped.values()):
        raise ValueError("Incomplete payee version history")

    def proof_for(proof_id, actor, purpose):
        proof = proofs.get(proof_id)
        if proof is None or proof["user_id"] != actor or proof["purpose"] != purpose:
            raise ValueError("Missing step-up evidence")

    count = 0
    for row in connection.execute(select(Authorization.__table__)).mappings():
        count += 1
        recipient = recipients.get(row["recipient_id"])
        facts = row["evidence"].get("facts")
        if recipient is None or recipient["invoice_id"] != row["invoice_id"] or not facts or digest(facts) != row["fingerprint"]:
            raise ValueError("Payment authorization binding mismatch")
        if facts["recipient_id"] != recipient["id"] or facts["invoice"]["id"] != row["invoice_id"] or Decimal(facts["amount"]) != Decimal(str(row["amount"])):
            raise ValueError("Payment authorization amount mismatch")
        if row["mode"] == "single_user":
            proof_for(row["evidence"].get("totp_use_id"), row["created_by"], "invoice:" + row["invoice_id"])
        elif row["mode"] != "four_eyes" or row["created_by"] == recipient["created_by"]:
            raise ValueError("Invalid four-eyes authorization")
    events = list(connection.execute(select(ModeEvent.__table__).order_by(ModeEvent.revision)).mappings())
    for revision, event in enumerate(events, 1):
        if event["revision"] != revision:
            raise ValueError("Incomplete approval policy history")
        if event["single_user_mode"]:
            proof_for(event["totp_use_id"], event["created_by"], "single-user-mode")
    current = connection.execute(select(Settings.__table__)).mappings().first()
    if current and (not events or events[-1]["revision"] != current["revision"] or events[-1]["single_user_mode"] != current["single_user_mode"]):
        raise ValueError("Approval policy differs from its evidence")
    return {"recipients": len(recipients), "authorizations": count, "mode_changes": len(events)}
