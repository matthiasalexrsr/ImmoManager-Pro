"""Prove customer archive sources before merging; historical approvals stay inert."""
import hashlib
import io
import math
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, LargeBinary, Numeric, String

from ...db.data_transfer_models import ImportedEvidenceORM
from ...db.e_invoice_models import EInvoiceIntakeORM, EInvoiceValidationORM
from ...db.payment_security_models import PaymentRecipientORM
from ..e_invoice.backup import verify_rows
from ..file_storage import get_file_storage
from ..integrations import connection_storage as db
from ..sepa_rules import iban_problem
from . import portable_archive as package
from .common import digest


def typed(model, payload, extract):
    result = {}
    for column in model.__table__.columns:
        value = payload[column.name]
        if value is None:
            if not column.nullable:
                raise ValueError("Pflichtwert fehlt im Fachnachweis.")
        elif isinstance(column.type, LargeBinary):
            value = extract(value)
        elif isinstance(column.type, DateTime):
            value = datetime.fromisoformat(value)
        elif isinstance(column.type, Date):
            value = date.fromisoformat(value)
        elif isinstance(column.type, Boolean):
            if type(value) is not bool:
                raise ValueError("Boolescher Wert erwartet.")
        elif isinstance(column.type, Integer):
            if type(value) is not int or abs(value) > 2_147_483_647:
                raise ValueError("Ganzzahl außerhalb des Wertebereichs.")
        elif isinstance(column.type, (Numeric, Float)):
            value = float(Decimal(str(value)))
            if not math.isfinite(value):
                raise ValueError("Endliche Zahl erwartet.")
        elif isinstance(column.type, JSON):
            if not isinstance(value, (dict, list)):
                raise ValueError("Strukturierter Nachweis erwartet.")
        elif isinstance(column.type, String):
            if not isinstance(value, str) or (column.type.length and len(value) > column.type.length):
                raise ValueError("Textwert außerhalb des Wertebereichs.")
        result[column.name] = value
    return result


def prepare(unit, content, prepared):
    snapshot, evidence, assets, extract, manifest = package.read(content)
    final = {spec.key: {row.id: row for row in prepared.backend.records(spec)} for spec, _ in prepared.plan}
    for spec, rows in prepared.plan:
        final[spec.key].update((row.id, row) for row in rows)
    active, history = {}, []
    active_by_name = {model.__tablename__: model for model in package.ACTIVE_MODELS}
    for record in evidence:
        model = active_by_name.get(record["source_type"]) if not record.get("historical") else None
        if model:
            value = typed(model, record["payload"], extract)
            key = (record["source_type"], value["id"])
            if key in active:
                raise ValueError("Fachnachweis doppelt im Kundenexport.")
            for column in model.__table__.columns:
                for fk in column.foreign_keys:
                    target = fk.column.table.name
                    identifier = value[column.name]
                    if identifier is not None and target in final and identifier not in final[target]:
                        raise ValueError("Fachnachweis verweist auf fehlende Geschäftsdaten.")
            old = db.row(unit, model, value["id"], required=False)
            if old is not None:
                before = db.values(old)
                if any(before[name] != item for name, item in value.items() if name not in {"validation_actor_id", "created_by", "idempotency_key", "revision", "updated_at", "state", "blockers"}):
                    raise ValueError("Vorhandener Fachnachweis ist nicht identisch.")
            active[key] = (model, value, old is None)
        if model not in (EInvoiceIntakeORM, EInvoiceValidationORM):
            history.append(record)
    intakes = [value for model, value, _ in active.values() if model is EInvoiceIntakeORM]
    validations = [value for model, value, _ in active.values() if model is EInvoiceValidationORM]
    verify_rows(intakes, validations, {key: row.model_dump() for key, row in final.get("invoices", {}).items()})
    payees: dict[str, list[int]] = {}
    for model, value, _ in active.values():
        if model is PaymentRecipientORM:
            if iban_problem(value["iban"]) or value["number"] < 1:
                raise ValueError("Ungültige Bankverbindung im Fachnachweis.")
            payees.setdefault(value["invoice_id"], []).append(value["number"])
    if any(sorted(numbers) != list(range(1, len(numbers) + 1)) for numbers in payees.values()):
        raise ValueError("Die Empfängerversionen sind lückenhaft.")
    storage = get_file_storage()
    for key, raw in assets:
        current = storage.get(key)
        if current is not None and hashlib.sha256(current).digest() != hashlib.sha256(raw).digest():
            raise ValueError("Ein vorhandener Dateipfad enthält andere Daten; keine Überschreibung.")
    # The producer's totals are part of the archive and must match its typed data.
    parsed, problems = package.snapshots._parse(snapshot, package.snapshots.entity_specs())
    if problems or manifest["controls"] != package._controls([(spec, parsed[spec.key]) for spec in package.snapshots.entity_specs()]):
        raise ValueError("Die Mengen- oder Betragskontrolle des Kundenexports stimmt nicht.")
    versions = snapshot[package.originals.SNAPSHOT_KEY]
    if manifest["originals"] != [{"id": row["id"], "sha256": row["sha256"]} for row in versions]:
        raise ValueError("Der Originalnachweis des Kundenexports stimmt nicht.")
    return list(active.values()), history, assets


def apply(unit, batch, plan):
    active, history, assets = plan
    for model in package.ACTIVE_MODELS:
        for incoming_model, value, fresh in active:
            if model is not incoming_model or not fresh:
                continue
            value = dict(value)
            if model is EInvoiceIntakeORM:
                value["validation_actor_id"] = unit.actor_id
                if value["state"] != "accepted":
                    value.update(state="technical_error", revision=value["revision"] + 1,
                        blockers=["Kundenexport übernommen. Vor einer neuen Übernahme lokal erneut validieren."])
            elif model is PaymentRecipientORM:
                # Importer's confirmation is one eye; a different current user
                # must check this recipient before a new payment authorization.
                value["created_by"] = unit.actor_id
                value["idempotency_key"] = "import-" + batch.id + "-" + value["id"]
            db.put(unit, model, value)
    for record in history:
        identifier = digest([record["source_type"], record["record_id"], record["sha256"]])
        if db.row(unit, ImportedEvidenceORM, identifier, required=False) is None:
            db.put(unit, ImportedEvidenceORM, {"id": identifier, "source_type": record["source_type"], "record_id": record["record_id"],
                "payload": record["payload"], "sha256": record["sha256"], "batch_id": batch.id, "imported_at": db.now()})
    # Write only verified, immutable source paths after every data check. A failed
    # transaction can leave an unreferenced source copy, never a partial business
    # record or a replacement of an existing file. It is safe to retry this step.
    storage = get_file_storage()
    for key, raw in assets:
        if storage.get(key) is None:
            storage.save(key, io.BytesIO(raw))
