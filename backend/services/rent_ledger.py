"""Monthly rental obligations, replay-safe generation and historical snapshots."""

import hashlib
import json
from calendar import monthrange
from datetime import date
from decimal import Decimal
from threading import RLock
from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from ..domain.lease_engine import PaymentLine, ReceivableLine
from ..models import RentCharge, RentChargeCreate
from ..storage import NotFoundError, ValidationError

Month = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")]
CENT = Decimal("0.01")
GENERATION_POLICY = "full_month"
_generation_lock = RLock()


class RentGenerationRequest(BaseModel):
    start_month: Month
    end_month: Month
    contract_ids: list[str] | None = Field(default=None, min_length=1, max_length=500)
    preview_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_range(self):
        start = month_date(self.start_month)
        end = month_date(self.end_month)
        if end < start:
            raise ValueError("Der Endmonat darf nicht vor dem Startmonat liegen.")
        if (end.year - start.year) * 12 + end.month - start.month >= 120:
            raise ValueError("Pro Lauf sind maximal 120 Monate erlaubt.")
        if self.contract_ids is not None and len(set(self.contract_ids)) != len(self.contract_ids):
            raise ValueError("Verträge dürfen nicht mehrfach ausgewählt werden.")
        return self


def month_date(month: str) -> date:
    try:
        return date.fromisoformat(f"{month}-01")
    except ValueError as exc:
        raise ValueError("Monat muss ein gültiger Wert im Format YYYY-MM sein.") from exc


def next_month(value: date) -> date:
    return date(value.year + value.month // 12, value.month % 12 + 1, 1)


def charge_total(charge) -> Decimal:
    return sum((Decimal(str(getattr(charge, field) or 0)) for field in
                ("cold_rent", "service_charge", "heating_charge", "other_charges")), Decimal("0")).quantize(CENT)


def _preview(store, request: RentGenerationRequest) -> dict:
    contracts = {c.id: c for c in store.list_contracts()}
    selected = request.contract_ids or sorted(contracts)
    unknown = set(selected) - set(contracts)
    if unknown:
        raise ValidationError("Ausgewählte Verträge existieren nicht: " + ", ".join(sorted(unknown)))
    existing = {(r.contract_id, r.month): r for r in store.list_rent_charges()}
    candidates, already_booked, skipped = [], [], []
    start, end = month_date(request.start_month), month_date(request.end_month)
    for contract_id in selected:
        contract = contracts[contract_id]
        if contract.status != "active":
            skipped.append({"contract_id": contract_id, "reason": "inactive_contract"})
            continue
        last_day = end.replace(day=monthrange(end.year, end.month)[1])
        if contract.start_date > last_day or (contract.end_date and contract.end_date < start):
            skipped.append({"contract_id": contract_id, "reason": "outside_contract_term"})
            continue
        unit = store.get_unit(contract.unit_id)
        current = max(start, contract.start_date.replace(day=1))
        last = min(end, contract.end_date.replace(day=1)) if contract.end_date else end
        while current <= last:
            month = current.strftime("%Y-%m")
            known = existing.get((contract_id, month))
            if known:
                already_booked.append({"contract_id": contract_id, "month": month, "charge_id": known.id})
            else:
                payload = RentChargeCreate(contract_id=contract_id, month=month,
                    cold_rent=unit.cold_rent or 0, service_charge=unit.service_charge_advance or 0,
                    heating_charge=unit.heating_advance or 0)
                candidates.append({**payload.model_dump(mode="json"),
                    "contract_number": contract.contract_number, "due_date": current.replace(day=3).isoformat(),
                    "partial_month": contract.start_date > current or bool(contract.end_date and
                        contract.end_date < current.replace(day=monthrange(current.year, current.month)[1])),
                    "total_amount": float(charge_total(payload))})
            current = next_month(current)
    fingerprint = hashlib.sha256(json.dumps({"candidates": candidates, "existing": already_booked,
        "skipped_contracts": skipped}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"policy": GENERATION_POLICY, "preview_hash": fingerprint,
        "policy_description": "Aktuelle Einheitenbeträge, auch für ungebuchte Altmonate: vor dem Erzeugen prüfen. Jeder berührte Vertragsmonat wird vollständig berechnet; keine automatische Tagesanteilberechnung. Fälligkeit: 3. des Monats.",
        "start_month": request.start_month, "end_month": request.end_month,
        "candidates": candidates, "existing": already_booked, "skipped_contracts": skipped,
        "total_amount": float(sum((Decimal(str(c["total_amount"])) for c in candidates), Decimal("0"))),
        "created": [], "created_count": 0, "skipped_count": len(already_booked)}


def preview_generation(store, request: RentGenerationRequest) -> dict:
    """Read-only inclusive monthly preview; never changes existing obligations."""
    with _generation_lock:
        return _preview(store, request)


def generate_rent_charges(store, request: RentGenerationRequest) -> dict:
    """Create every candidate atomically, with DB uniqueness handling concurrent replays."""
    with _generation_lock:
        result = _preview(store, request)
        if request.preview_hash and request.preview_hash != result["preview_hash"] and result["candidates"]:
            raise ValidationError("Die Vorschau wurde zwischenzeitlich geändert. Bitte erneut prüfen.")
        fields = set(RentChargeCreate.model_fields)
        payloads = [RentChargeCreate(**{k: v for k, v in row.items() if k in fields})
                    for row in result["candidates"]]
        if hasattr(store, "db"):
            from ..db.orm_models import RentChargeORM
            db = store.db
            try:
                # Python's sqlite legacy transaction mode does not start a transaction
                # for SELECT. A released first SAVEPOINT would otherwise commit early.
                if db.get_bind().dialect.name == "sqlite" and not db.connection().connection.driver_connection.in_transaction:
                    db.execute(text("BEGIN"))
                for payload in payloads:
                    try:
                        with db.begin_nested():
                            row = RentChargeORM(id=str(uuid4()), **payload.model_dump())
                            db.add(row)
                            db.flush()
                            result["created"].append(RentCharge.model_validate(row, from_attributes=True).model_dump(mode="json"))
                    except IntegrityError:
                        known = db.scalar(select(RentChargeORM).where(
                            RentChargeORM.contract_id == payload.contract_id, RentChargeORM.month == payload.month))
                        if known is None:
                            raise
                        result["existing"].append({"contract_id": payload.contract_id, "month": payload.month, "charge_id": known.id})
                db.commit()
            except Exception:
                db.rollback()
                raise
        else:
            # Validate everything before mutation and restore the complete batch on failure.
            before = dict(store.rent_charges)
            try:
                for payload in payloads:
                    result["created"].append(store.create_rent_charge(payload).model_dump(mode="json"))
            except Exception:
                store.rent_charges = before
                raise
        result["created_count"] = len(result["created"])
        result["skipped_count"] = len(result["existing"])
        return result


def validate_unique_month(store, payload: RentChargeCreate, exclude_id: str | None = None) -> None:
    try:
        store.get_contract(payload.contract_id)
    except NotFoundError as exc:
        raise ValidationError("Vertrag existiert nicht") from exc
    if any(r.contract_id == payload.contract_id and r.month == payload.month and r.id != exclude_id
           for r in store.list_rent_charges()):
        raise ValidationError("Für diesen Vertrag und Monat besteht bereits eine Sollstellung.")


def validate_charge_identity(current, payload, has_history: bool) -> None:
    if ((current.contract_id, current.month) != (payload.contract_id, payload.month)
            and (has_history or current.amount_paid > 0)):
        from .payments import FinancialConsistencyError
        raise FinancialConsistencyError("Vertrag und Monat einer Sollstellung mit Zahlungshistorie dürfen nicht verschoben werden.")


def ensure_unique_month_schema(connection) -> None:
    """Add the legacy local SQLite index, refusing to discard duplicate financial history."""
    from typing import cast

    from sqlalchemy import Table

    from ..db.orm_models import RentChargeORM
    duplicates = connection.execute(text("SELECT contract_id, month, COUNT(*) FROM rent_charges "
        "GROUP BY contract_id, month HAVING COUNT(*) > 1")).all()
    if duplicates:
        detail = "; ".join(f"Vertrag {c}, Monat {m}: {n} Einträge" for c, m, n in duplicates[:10])
        raise RuntimeError("Doppelte monatliche Sollstellungen verhindern die Migration. " + detail +
            ". Vollständige Sicherung erstellen und die betroffenen Einträge samt Zahlungen/Bankzuordnungen prüfen. "
            "Keine Zahlungsbelege löschen; getrennte Zusatzforderungen fachlich zuordnen. "
            "Die Migration verändert oder entfernt keine Finanzhistorie.")
    name = "uq_rent_charges_contract_month"
    if name not in {index["name"] for index in inspect(connection).get_indexes("rent_charges")}:
        next(index for index in cast(Table, RentChargeORM.__table__).indexes if index.name == name).create(connection, checkfirst=True)


def contract_ledger_inputs(store, contract, as_of: date) -> tuple[list[ReceivableLine], list[PaymentLine]]:
    """Historical booked amounts and targeted receipts; unallocated bookings aren't payments."""
    charges = sorted((c for c in store.list_rent_charges() if c.contract_id == contract.id and c.status not in {"cancelled", "void"}
                      and month_date(c.month) <= as_of), key=lambda c: c.month)
    all_receipts = store.list_payments("rent_charge")
    lines, payments = [], []
    for charge in charges:
        start = month_date(charge.month)
        due = start.replace(day=3)
        lines.append(ReceivableLine(period_start=start, period_end=next_month(start), due_date=due,
            cold_rent=Decimal(str(charge.cold_rent)), service_charge_advance=Decimal(str(charge.service_charge)),
            heating_advance=Decimal(str(charge.heating_charge)), other_charges=Decimal(str(charge.other_charges)),
            total_amount=charge_total(charge)))
        receipts = [p for p in all_receipts if p.entity_id == charge.id]
        for receipt in receipts:
            reversal = getattr(receipt, "reversal", None)
            if receipt.payment_date <= as_of and (reversal is None or reversal.reversal_date > as_of):
                payments.append(PaymentLine(booking_date=receipt.payment_date, amount=receipt.amount, period_start=start))
        # Keep old paid balances without manufacturing auditable receipts or guessing their dates.
        legacy_paid = Decimal(str(charge.amount_paid)) - sum((p.amount for p in receipts
            if not getattr(p, "reversal", None)), Decimal("0"))
        if legacy_paid > 0:
            payments.append(PaymentLine(booking_date=start, amount=legacy_paid, period_start=start))
    return lines, payments


def ungenerated_contract_preview(store, contract, as_of: date) -> dict:
    if as_of < contract.start_date:
        return {"candidates": [], "total_amount": 0, "policy": GENERATION_POLICY}
    # This read-only history view may span older contracts than one write batch allows.
    return preview_generation(store, RentGenerationRequest.model_construct(start_month=contract.start_date.strftime("%Y-%m"),
        end_month=as_of.strftime("%Y-%m"), contract_ids=[contract.id]))


def list_open_items(store) -> dict:
    """Single reporting view: monthly rent plus separately entered other obligations."""
    items = []
    for entity_type, targets in (("rent_charge", store.list_rent_charges()), ("receivable", store.list_receivables())):
        for target in targets:
            if target.status in {"cancelled", "void"}:
                continue
            total = charge_total(target) if entity_type == "rent_charge" else Decimal(str(target.amount_due))
            remaining = total - Decimal(str(target.amount_paid or 0))
            if remaining <= 0:
                continue
            due = month_date(target.month).replace(day=3) if entity_type == "rent_charge" else target.due_date
            items.append({"entity_type": entity_type, "entity_id": target.id, "contract_id": target.contract_id,
                "month": target.month if entity_type == "rent_charge" else None,
                "due_date": due.isoformat(), "amount_due": float(total), "amount_paid": target.amount_paid,
                "outstanding_amount": float(remaining.quantize(CENT)), "status": target.status})
    return {"items": sorted(items, key=lambda i: (i["due_date"], i["entity_type"], i["entity_id"])),
            "total_outstanding": float(sum((Decimal(str(i["outstanding_amount"])) for i in items), Decimal("0"))),
            "source": "monthly_rent_and_other_receivables"}
