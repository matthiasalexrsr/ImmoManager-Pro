"""Actual contract receipts and a monthly rent view derived from the existing lease engine.

The older rent_charge.amount_paid and receivable.status fields are manually maintained
records, not evidence of cash. This workflow never changes them. One receipt is a booking
and an explicit contract allocation. Its command receipt lives in the existing contract
history, so a retry cannot recreate a booking that someone has subsequently deleted.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db.orm_models import (
    AccountORM,
    ChangeHistoryORM,
    ContractORM,
    PaymentAllocationORM,
    PropertyORM,
    TenantORM,
    UnitORM,
)
from ..domain.lease_engine import LeaseEngine
from ..domain.money import ZERO, as_number, money
from ..domain.occupancy import NON_BILLABLE_STATUSES
from ..models import Booking, ChangeHistoryEntry, PaymentAllocation
from ..storage import NotFoundError
from . import document_versions as archive
from .housing_confirmation import etag
from .jobs.schedule import local_today
from .maintenance_rows import Rows
from .payment_allocations import contract_payments, credited_by_tenant, deposit_shares
from .portfolio_scope import scope_context
from .read_cache import CachedReads
from .rent_history import rent_steps


class ContractPaymentRequest(BaseModel):
    contract_id: str = Field(min_length=1)
    contract_revision: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    booking_date: date
    payment_text: str = Field(default="", max_length=2000)
    idempotency_key: UUID


class PaymentConflict(HTTPException):
    def __init__(self, code: str, message: str, *, booking_id: str | None = None, status_code: int = 409):
        super().__init__(status_code, message)
        self.code = code
        self.details = {"booking_id": booking_id} if booking_id else None


def _revision(contract: Any) -> str:
    return etag("contracts", contract.id, contract.updated_at)


def _insert_allocation(unit: archive.Unit, item: PaymentAllocation) -> None:
    if unit.db is None:
        unit.insert(unit.store.payment_allocations, item.id, item)
    else:
        unit.db.add(PaymentAllocationORM(**item.model_dump()))
        unit.db.flush()


def record_payment(store: Any, request: ContractPaymentRequest, actor_id: str) -> dict:
    try:
        return _record_payment(store, request, actor_id)
    except NotFoundError:
        # The first unit has rolled back. Recheck this actor's command key under its
        # account lock. Only existence is inspected outside the portfolio fence: no
        # former contract, account or payment information is exposed. This also works
        # after a parent was deleted or the actor lost access to its former portfolio.
        receipt_id = str(uuid5(NAMESPACE_URL, f"immo:contract-payment:v1:{actor_id}:{request.idempotency_key}"))
        with archive.work(store, actor_id, write_areas=("/bookings",)) as unit:
            if unit.db is not None:
                with scope_context(None):
                    recorded = unit.db.scalar(select(ChangeHistoryORM.id).where(
                        ChangeHistoryORM.id == receipt_id, ChangeHistoryORM.changed_by == actor_id,
                        ChangeHistoryORM.field_name == "contract_payment")) is not None
            else:
                receipt = object.__getattribute__(unit.store, "__dict__")["change_history"].get(receipt_id)
                recorded = bool(receipt and receipt.changed_by == actor_id and receipt.field_name == "contract_payment")
        if recorded:
            raise PaymentConflict("RENT_PAYMENT_RECORDED_UNAVAILABLE", "Dieser Vorgang wurde bereits gebucht. "
                                  "Seine Zuordnung ist derzeit nicht mehr zugänglich. Es wird nichts erneut gebucht.",
                                  status_code=404) from None
        raise PaymentConflict("RENT_PAYMENT_NOT_CREATED", "Es wurde nichts gebucht: Vertrag oder Zahlungskonto "
                              "sind nicht verfügbar. Bitte die Mietübersicht neu laden.", status_code=404) from None


def _record_payment(store: Any, request: ContractPaymentRequest, actor_id: str) -> dict:
    """Create the cash and its allocation once, under the current actor and parent locks."""
    receipt_id = str(uuid5(NAMESPACE_URL, f"immo:contract-payment:v1:{actor_id}:{request.idempotency_key}"))
    booking_id = str(uuid5(NAMESPACE_URL, receipt_id + ":booking"))
    allocation_id = str(uuid5(NAMESPACE_URL, receipt_id + ":allocation"))
    canonical = request.model_dump(mode="json")
    canonical["amount"] = str(money(request.amount))
    fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with archive.work(store, actor_id, write_areas=("/bookings",)) as unit:
        contract = unit.store.get_contract(request.contract_id)
        original_binding = (contract.tenant_id, contract.property_id, contract.unit_id)
        if unit.db is not None:
            # The same parent order as the existing generated-document/deposit writers.
            for model, key in ((TenantORM, contract.tenant_id), (PropertyORM, contract.property_id),
                               (UnitORM, contract.unit_id), (ContractORM, contract.id),
                               (AccountORM, request.account_id)):
                if unit.db.scalar(select(model.id).where(model.id == key).with_for_update()) is None:
                    raise NotFoundError("Vertrag oder Zahlungskonto nicht vorhanden")
            unit.db.expire_all()
            contract = unit.store.get_contract(request.contract_id)
        prop = unit.store.get_property(contract.property_id)
        location = unit.store.get_unit(contract.unit_id)
        unit.store.get_tenant(contract.tenant_id)
        account = unit.store.get_account(request.account_id)
        rows = Rows.of(unit)
        receipt = rows.get("change_history", receipt_id)
        if receipt is not None:
            if (receipt.entity_type != "contract" or receipt.entity_id != contract.id
                    or receipt.field_name != "contract_payment" or receipt.changed_by != actor_id
                    or receipt.old_value != fingerprint):
                raise PaymentConflict("RENT_PAYMENT_KEY_REUSED", "Diese Vorgangskennung wurde bereits mit anderen Angaben verwendet.")
            try:
                booking = unit.store.get_booking(booking_id)
            except NotFoundError:
                raise PaymentConflict("RENT_PAYMENT_REMOVED", "Diese Zahlung wurde bereits gebucht und später gelöscht. "
                                      "Sie wird nicht erneut angelegt.") from None
            allocations = unit.store.list_payment_allocations(booking_id=booking_id)
            if (booking.account_id != request.account_id or money(booking.amount) != money(request.amount)
                    or booking.status != "booked" or booking.reverses_booking_id is not None
                    or booking.booking_date != request.booking_date
                    or booking.payment_text != (request.payment_text or f"Mietzahlung {contract.contract_number}")
                    or (booking.tenant_id, booking.property_id, booking.unit_id) != (
                        contract.tenant_id, contract.property_id, contract.unit_id)
                    or len(allocations) != 1 or allocations[0].id != allocation_id
                    or allocations[0].source != "manual" or allocations[0].contract_id != contract.id
                    or money(allocations[0].amount) != money(request.amount)
                    or unit.store.list_booking_reversals(booking_id)
                    or deposit_shares(unit.store, [booking_id]).get(booking_id, ZERO)):
                raise PaymentConflict("RENT_PAYMENT_CHANGED", "Diese Zahlung wurde bereits gebucht und danach "
                                      "bearbeitet oder storniert. Bitte die aktuelle Buchung prüfen; "
                                      "es wird keine weitere Zahlung angelegt.", booking_id=booking_id)
            return {"booking": booking.model_dump(mode="json"), "contract_id": contract.id, "replayed": True}
        if original_binding != (contract.tenant_id, contract.property_id, contract.unit_id):
            raise PaymentConflict("RENT_PAYMENT_NOT_CREATED", "Es wurde nichts gebucht: Die Vertragszuordnung wurde geändert. Bitte neu laden.")
        if account.portfolio_id != prop.portfolio_id or location.property_id != prop.id:
            raise HTTPException(422, "Das Zahlungskonto muss zum Portfolio des Vertrags gehören.")
        if request.contract_revision != _revision(contract):
            raise PaymentConflict("RENT_PAYMENT_NOT_CREATED", "Es wurde nichts gebucht: Der Vertrag wurde geändert. Bitte die Mietübersicht neu laden.")
        if contract.status in NON_BILLABLE_STATUSES:
            raise HTTPException(422, "Für einen Vertragsentwurf kann noch kein Mieteingang gebucht werden.")
        if request.booking_date > local_today():
            raise HTTPException(422, "Ein Zahlungseingang darf nicht in der Zukunft liegen.")
        booking = Booking(id=booking_id, account_id=account.id, property_id=prop.id,
                          unit_id=contract.unit_id, tenant_id=contract.tenant_id,
                          booking_date=request.booking_date, amount=as_number(request.amount), status="booked",
                          payment_text=request.payment_text or f"Mietzahlung {contract.contract_number}")
        allocation = PaymentAllocation(id=allocation_id, booking_id=booking.id, contract_id=contract.id,
                                       amount=booking.amount, source="manual")
        rows.add("bookings", booking)
        _insert_allocation(unit, allocation)
        rows.add("change_history", ChangeHistoryEntry(
            id=receipt_id, entity_type="contract", entity_id=contract.id, field_name="contract_payment",
            old_value=fingerprint, new_value=json.dumps({"booking_id": booking.id, "allocation_id": allocation.id,
                                                        "request": canonical}, ensure_ascii=False),
            changed_by=actor_id, reason="Zahlungseingang mit Vertragszuordnung gebucht"))
        return {"booking": booking.model_dump(mode="json"), "contract_id": contract.id, "replayed": False}


def monthly_ledger(store: Any, month: str, as_of: date, property_id: str | None = None) -> dict:
    """One row per contract in the selected month; FIFO also includes every earlier rent period."""
    try:
        selected = date.fromisoformat(month + "-01")
    except ValueError:
        raise HTTPException(422, "Bitte einen gültigen Monat im Format JJJJ-MM wählen.") from None
    if selected > as_of.replace(day=1):
        raise HTTPException(422, "Der Mietmonat liegt nach dem gewählten Stichtag.")
    store = CachedReads(store)
    contracts = [c for c in store.list_contracts() if c.status not in NON_BILLABLE_STATUSES
                 and (not property_id or c.property_id == property_id)
                 and c.start_date <= as_of and c.start_date.strftime("%Y-%m") <= month
                 and (c.end_date is None or c.end_date.strftime("%Y-%m") >= month)]
    credited = credited_by_tenant(store, {c.tenant_id for c in contracts}, until=as_of) if contracts else {}
    properties = {p.id: p for p in store.list_properties()}
    units = {u.id: u for u in store.list_units()}
    tenants = {t.id: t for t in store.list_tenants()}
    totals = {"expected": ZERO, "paid": ZERO, "outstanding": ZERO, "contract_credit": ZERO}
    result = []
    for contract in contracts:
        dashboard = LeaseEngine.build_dashboard(
            contract_start=contract.start_date, contract_end=contract.end_date,
            rent_steps=rent_steps(store, contract), today=as_of,
            payments=contract_payments(store, contract, credited.get(contract.tenant_id, []), until=as_of))
        line = next((line for line in dashboard.settlement_lines if line.period_start == selected), None)
        if line is None:
            continue
        values = {"expected": line.total_amount, "paid": line.paid_amount, "outstanding": line.outstanding_amount,
                  "contract_credit": dashboard.balance.overpaid_total}
        for key, value in values.items():
            totals[key] += value
        prop = properties.get(contract.property_id)
        result.append({"id": f"{contract.id}:{month}", "contract_id": contract.id,
                       "contract_revision": _revision(contract), "contract_number": contract.contract_number,
                       "tenant_id": contract.tenant_id, "tenant_name": getattr(tenants.get(contract.tenant_id), "full_name", "—"),
                       "property_id": contract.property_id, "property_name": getattr(prop, "name", "—"),
                       "portfolio_id": getattr(prop, "portfolio_id", None),
                       "unit_label": getattr(units.get(contract.unit_id), "label", "—"),
                       "month": month, "due_date": line.due_date.isoformat(), "status": line.status,
                       **{key: as_number(value) for key, value in values.items()}})
    result.sort(key=lambda row: (row["property_name"], row["unit_label"], row["contract_number"]))
    return {"month": month, "as_of": as_of.isoformat(), "property_id": property_id,
            "rows": result, "totals": {key: as_number(value) for key, value in totals.items()}}
