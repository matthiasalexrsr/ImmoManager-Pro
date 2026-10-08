"""Property service contracts (Objektverträge): rules, views, deadlines, payments, cost transfer.

The stores keep the records (storage_service_contracts, repositories/service_contract_repo);
the portfolio boundary is enforced by services/portfolio_scope.py on every read and write.
This module checks what the stores cannot: references and their consistency, the
calendar of terms and notices (domain.service_contract_terms), and money that must
count once (domain.service_contract_finance).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from ..domain.money import ZERO, as_number, cents, money
from ..domain.service_contract_finance import (
    overlap_days,
    planned_instalments,
    property_share,
    property_weights,
    prorated,
    reconcile,
    recoverable_part,
    tariff_at,
)
from ..domain.service_contract_terms import Terms
from ..models import CostItemCreate
from ..models_service_contracts import (
    CancellationRequest,
    CostTransferRequest,
    InvoiceLinkRequest,
    LocationInput,
    PaymentLinkRequest,
    ServiceContract,
    ServiceContractCreate,
    ServiceContractCreateRequest,
    ServiceContractDocumentCreate,
    ServiceContractInvoiceCreate,
    ServiceContractLocationCreate,
    ServiceContractPaymentCreate,
    ServiceContractTariffCreate,
    TariffInput,
)
from ..store_errors import NotFoundError, ValidationError
from .final_statements import EDITABLE_STATUSES
from .jobs.schedule import local_today
from .portfolio_scope import contract_has_hidden_locations, scope_context

# deadlines overview and planned instalments: bounded windows, stated in the answer
MAX_WINDOW_DAYS = 3700
MAX_CANDIDATE_DAYS = 400
DEADLINE_KINDS = ("notice", "price_guarantee", "contract_end")


def today() -> date:
    """The installation's date (Europe/Berlin), like the scheduled jobs."""
    return local_today()


def _day(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _de(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else "—"


def provider_name(contact: Any) -> str:
    if contact is None:
        return "Unbekannter Anbieter"
    person = " ".join(p.strip() for p in (contact.first_name, contact.last_name) if p and p.strip())
    return (contact.company_name or "").strip() or person or (contact.email or "").strip() or "Kontakt"


def _try(getter, key):
    try:
        return getter(key) if key else None
    except NotFoundError:
        return None


def _group(rows: Iterable[Any], key: str = "service_contract_id") -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[getattr(row, key)].append(row)
    return grouped


def check_window(date_from: date, date_to: date) -> None:
    if date_to < date_from:
        raise ValidationError("Der Zeitraum endet vor seinem Beginn")
    if (date_to - date_from).days > MAX_WINDOW_DAYS:
        raise ValidationError(f"Der Zeitraum ist zu lang (höchstens {MAX_WINDOW_DAYS} Tage)")


# --- checks --------------------------------------------------------------------------------------

def check_contract(store: Any, data: ServiceContractCreate) -> None:
    if _try(store.get_contact, data.provider_contact_id) is None:
        raise ValidationError("Der Anbieter (Kontakt) existiert nicht")


def check_location(store: Any, location: LocationInput, siblings: Iterable[Any] = ()) -> None:
    """The property, unit and meter exist, belong together and are not on the contract twice."""
    if _try(store.get_property, location.property_id) is None:
        raise ValidationError("Immobilie existiert nicht")
    unit = _try(store.get_unit, location.unit_id)
    if location.unit_id and unit is None:
        raise ValidationError("Einheit existiert nicht")
    if unit is not None and unit.property_id != location.property_id:
        raise ValidationError("Die Einheit gehört nicht zur gewählten Immobilie")
    if location.meter_id:
        meter = _try(store.get_meter, location.meter_id)
        if meter is None:
            raise ValidationError("Zähler existiert nicht")
        meter_unit = _try(store.get_unit, meter.unit_id)
        if meter_unit is None or meter_unit.property_id != location.property_id:
            raise ValidationError("Der Zähler gehört nicht zur gewählten Immobilie")
        if location.unit_id and meter.unit_id != location.unit_id:
            raise ValidationError("Der Zähler gehört nicht zur gewählten Einheit")
    key = (location.property_id, location.unit_id, location.meter_id)
    if any((s.property_id, s.unit_id, s.meter_id) == key for s in siblings):
        raise ValidationError("Dieser Standort ist dem Vertrag bereits zugeordnet")


def _check_tariff_in_contract(contract: Any, tariff: TariffInput) -> None:
    if tariff.valid_from < contract.start_date:
        raise ValidationError("Ein Tarif kann nicht vor Vertragsbeginn gelten")
    end = Terms.of(contract).effective_end
    if end is not None and tariff.valid_from > end:
        raise ValidationError("Ein Tarif kann nicht nach Vertragsende beginnen")


def require_whole_contract(store: Any, contract_id: str) -> None:
    """Contract-level actions on other records (cost transfer) need every location visible."""
    if contract_has_hidden_locations(store, contract_id):
        raise HTTPException(403, "Dieser Objektvertrag hat Standorte in Portfolios, auf die Sie keinen Zugriff "
                                 "haben. Das kann nur ein Konto mit Zugriff auf alle zugehörigen Portfolios.")


# --- contracts -----------------------------------------------------------------------------------

def create_contract(store: Any, request: ServiceContractCreateRequest) -> ServiceContract:
    data = ServiceContractCreate.model_validate(request.model_dump(include=set(ServiceContractCreate.model_fields)))
    check_contract(store, data)
    seen: list[LocationInput] = []
    for location in request.locations:
        check_location(store, location, seen)
        seen.append(location)
    if request.tariff is not None:
        _check_tariff_in_contract(data, request.tariff)
    return store.create_service_contract(data, request.locations, request.tariff)


def update_contract(store: Any, contract_id: str, data: ServiceContractCreate) -> ServiceContract:
    current = store.get_service_contract(contract_id)
    require_whole_contract(store, contract_id)
    check_contract(store, data)
    tariffs = store.list_service_contract_tariffs(contract_id)
    if tariffs and min(t.valid_from for t in tariffs) < data.start_date:
        raise ValidationError("Es gibt Tarife vor dem neuen Vertragsbeginn")
    if (data.cancelled_on, data.cancellation_effective) != (current.cancelled_on, current.cancellation_effective):
        _check_cancellation_date(data, data.cancelled_on, data.cancellation_effective, extraordinary=False)
    return store.update_service_contract(contract_id, data)


def _check_cancellation_date(contract: Any, cancelled_on: date | None, effective: date | None, *,
                             extraordinary: bool) -> None:
    if cancelled_on is None or effective is None or extraordinary:
        return
    earliest = Terms.of(contract.model_copy(update={"cancelled_on": None, "cancellation_effective": None})
                        ).earliest_end(cancelled_on)
    if earliest is not None and effective < earliest:
        raise ValidationError(f"Eine am {_de(cancelled_on)} zugegangene Kündigung wirkt frühestens zum "
                              f"{_de(earliest)}")


def cancel_contract(store: Any, contract_id: str, request: CancellationRequest, *,
                    extraordinary: bool = False) -> ServiceContract:
    contract = store.get_service_contract(contract_id)
    require_whole_contract(store, contract_id)
    if request.cancelled_on < contract.start_date - timedelta(days=3660):
        raise ValidationError("Das Datum der Kündigung ist nicht plausibel")
    base = Terms.of(contract.model_copy(update={"cancelled_on": None, "cancellation_effective": None}))
    effective = request.effective_date or base.earliest_end(request.cancelled_on)
    if effective is None:
        raise ValidationError("Zu welchem Termin die Kündigung wirkt, lässt sich nicht berechnen; bitte angeben")
    _check_cancellation_date(contract, request.cancelled_on, effective, extraordinary=extraordinary)
    data = ServiceContractCreate.model_validate({
        **contract.model_dump(include=set(ServiceContractCreate.model_fields)),
        "cancelled_on": request.cancelled_on, "cancellation_effective": effective})
    return store.update_service_contract(contract_id, data)


def withdraw_cancellation(store: Any, contract_id: str) -> ServiceContract:
    contract = store.get_service_contract(contract_id)
    require_whole_contract(store, contract_id)
    data = ServiceContractCreate.model_validate({
        **contract.model_dump(include=set(ServiceContractCreate.model_fields)),
        "cancelled_on": None, "cancellation_effective": None})
    return store.update_service_contract(contract_id, data)


def delete_contract(store: Any, contract_id: str) -> None:
    store.get_service_contract(contract_id)
    require_whole_contract(store, contract_id)
    with scope_context(None):    # bills and payments of every portfolio count
        bills = store.list_service_contract_invoices(contract_id)
        payments = store.list_service_contract_payments(contract_id)
    if bills or payments:
        raise HTTPException(409, f"Der Objektvertrag hat {len(bills)} Rechnung(en) und {len(payments)} Zahlung(en) "
                                 "und wird deshalb nicht gelöscht. Bitte stattdessen kündigen bzw. beenden.")
    store.delete_service_contract(contract_id)


# --- locations -----------------------------------------------------------------------------------

def add_location(store: Any, contract_id: str, location: LocationInput) -> Any:
    store.get_service_contract(contract_id)
    require_whole_contract(store, contract_id)
    check_location(store, location, store.list_service_contract_locations(contract_id))
    return store.create_service_contract_location(
        ServiceContractLocationCreate(service_contract_id=contract_id, **location.model_dump()))


def update_location(store: Any, contract_id: str, location_id: str, location: LocationInput) -> Any:
    current = store.get_service_contract_location(location_id)
    if current.service_contract_id != contract_id:
        raise NotFoundError("Standort nicht gefunden")
    require_whole_contract(store, contract_id)
    siblings = [s for s in store.list_service_contract_locations(contract_id) if s.id != location_id]
    check_location(store, location, siblings)
    return store.update_service_contract_location(
        location_id, ServiceContractLocationCreate(service_contract_id=contract_id, **location.model_dump()))


def remove_location(store: Any, contract_id: str, location_id: str) -> None:
    current = store.get_service_contract_location(location_id)
    if current.service_contract_id != contract_id:
        raise NotFoundError("Standort nicht gefunden")
    require_whole_contract(store, contract_id)
    if len(store.list_service_contract_locations(contract_id)) <= 1:
        raise ValidationError("Ein Objektvertrag braucht mindestens einen Standort")
    store.delete_service_contract_location(location_id)


# --- tariffs -------------------------------------------------------------------------------------

def add_tariff(store: Any, contract_id: str, tariff: TariffInput) -> Any:
    contract = store.get_service_contract(contract_id)
    require_whole_contract(store, contract_id)
    _check_tariff_in_contract(contract, tariff)
    return store.create_service_contract_tariff(
        ServiceContractTariffCreate(service_contract_id=contract_id, **tariff.model_dump()))


def update_tariff(store: Any, contract_id: str, tariff_id: str, tariff: TariffInput) -> Any:
    contract = store.get_service_contract(contract_id)
    require_whole_contract(store, contract_id)
    if store.get_service_contract_tariff(tariff_id).service_contract_id != contract_id:
        raise NotFoundError("Tarif nicht gefunden")
    _check_tariff_in_contract(contract, tariff)
    return store.update_service_contract_tariff(
        tariff_id, ServiceContractTariffCreate(service_contract_id=contract_id, **tariff.model_dump()))


def remove_tariff(store: Any, contract_id: str, tariff_id: str) -> None:
    require_whole_contract(store, contract_id)
    if store.get_service_contract_tariff(tariff_id).service_contract_id != contract_id:
        raise NotFoundError("Tarif nicht gefunden")
    store.delete_service_contract_tariff(tariff_id)


def tariff_view(tariff: Any) -> dict:
    data = tariff.model_dump(mode="json")
    data["advance_amount"] = as_number(money(tariff.advance_amount)) if tariff.advance_amount is not None else None
    data["base_price"] = as_number(money(tariff.base_price)) if tariff.base_price is not None else None
    return data


# --- terms and deadlines -------------------------------------------------------------------------

@dataclass(frozen=True)
class Deadline:
    kind: str                    # notice | price_guarantee | contract_end
    day: date
    contract_id: str
    end: date | None = None      # notice: the end it reaches
    renews_to: date | None = None
    tariff_id: str | None = None

    def as_dict(self, as_of: date) -> dict:
        return {"kind": self.kind, "date": _day(self.day), "days_left": (self.day - as_of).days,
                "service_contract_id": self.contract_id, "end": _day(self.end), "renews_to": _day(self.renews_to),
                "tariff_id": self.tariff_id}


def deadlines(contract: Any, tariffs: list[Any], as_of: date, horizon_days: int) -> list[Deadline]:
    """Notice deadline, price guarantee ends and the contract end from as_of to as_of + horizon."""
    terms = Terms.of(contract)
    if terms.status(as_of) == "ended":
        return []
    until = as_of + timedelta(days=horizon_days)
    found: list[Deadline] = []
    notice = terms.next_notice_deadline(as_of)
    if notice and notice[0] <= until:
        renewal = terms.renewal_after(notice[1])
        found.append(Deadline("notice", notice[0], contract.id, end=notice[1],
                              renews_to=renewal[1] if renewal else None))
    end = terms.effective_end
    if end is not None and as_of <= end <= until:
        found.append(Deadline("contract_end", end, contract.id, end=end))
    for tariff in tariffs:
        guarantee = tariff.price_guarantee_until
        if guarantee is None or not as_of <= guarantee <= until or (end is not None and guarantee >= end):
            continue
        if tariff_at(tariffs, guarantee) is tariff:       # a later tariff already replaced it
            found.append(Deadline("price_guarantee", guarantee, contract.id, tariff_id=tariff.id))
    return sorted(found, key=lambda d: (d.day, DEADLINE_KINDS.index(d.kind)))


def due_reminders(contract: Any, tariffs: list[Any], as_of: date) -> list[Deadline]:
    """The deadlines whose reminder window (reminder_days before) has begun."""
    return deadlines(contract, tariffs, as_of, contract.reminder_days)


def terms_view(contract: Any, tariffs: list[Any], as_of: date) -> dict:
    terms = Terms.of(contract)
    term = terms.term_containing(as_of)
    notice = terms.next_notice_deadline(as_of)
    renewal = terms.renewal_after(notice[1]) if notice else None
    current = tariff_at(tariffs, as_of)
    return {
        "as_of": _day(as_of),
        "status": terms.status(as_of),
        "first_term_end": _day(terms.first_term_end),
        "current_term": {"start": _day(term[0]), "end": _day(term[1])} if term else None,
        "effective_end": _day(terms.effective_end),
        "renewal_mode": contract.renewal_mode,
        "renewal_months": contract.renewal_months,
        "notice": ({"value": contract.notice_period_value, "unit": contract.notice_period_unit,
                    "to": contract.notice_to} if terms.has_notice_period else None),
        "next_notice_deadline": ({"date": _day(notice[0]), "end": _day(notice[1]),
                                  "days_left": (notice[0] - as_of).days,
                                  "renews_to": _day(renewal[1]) if renewal else None} if notice else None),
        "earliest_end_if_cancelled_today": _day(terms.earliest_end(as_of)) if terms.effective_end is None else None,
        "cancellation": ({"cancelled_on": _day(contract.cancelled_on),
                          "effective": _day(contract.cancellation_effective)} if contract.cancelled_on else None),
        "current_tariff_id": current.id if current else None,
        "price_guarantee_until": _day(current.price_guarantee_until) if current else None,
        "upcoming": [d.as_dict(as_of) for d in deadlines(contract, tariffs, as_of, 400)],
    }


# --- views ---------------------------------------------------------------------------------------

class Labels:
    """Names of properties, units, meters and providers for a page of contracts (read once)."""

    def __init__(self, store: Any):
        self.store = store
        self._properties: dict[str, Any] | None = None
        self._units: dict[str, Any] | None = None
        self._meters: dict[str, Any] | None = None
        self._contacts: dict[str, Any] = {}

    def property(self, key: str | None) -> Any:
        if self._properties is None:
            self._properties = {p.id: p for p in self.store.list_properties()}
        return self._properties.get(key or "")

    def unit(self, key: str | None) -> Any:
        if self._units is None:
            self._units = {u.id: u for u in self.store.list_units()}
        return self._units.get(key or "")

    def meter(self, key: str | None) -> Any:
        if self._meters is None:
            self._meters = {m.id: m for m in self.store.list_meters()}
        return self._meters.get(key or "")

    def provider(self, key: str) -> Any:
        if key not in self._contacts:
            self._contacts[key] = _try(self.store.get_contact, key)
        return self._contacts[key]


def location_view(location: Any, labels: Labels) -> dict:
    data = location.model_dump(mode="json")
    prop, unit, meter = labels.property(location.property_id), labels.unit(location.unit_id), labels.meter(
        location.meter_id)
    data["property_name"] = prop.name if prop else None
    data["unit_label"] = unit.label if unit else None
    data["meter_label"] = (" · ".join(p for p in (meter.meter_type, meter.serial_number) if p) if meter else None)
    data["label"] = " / ".join(p for p in (data["property_name"], data["unit_label"], data["meter_label"]) if p)
    return data


def summary_view(contract: Any, locations: list[Any], tariffs: list[Any], labels: Labels, as_of: date) -> dict:
    terms = Terms.of(contract)
    upcoming = deadlines(contract, tariffs, as_of, 400)
    current = tariff_at(tariffs, as_of)
    provider = labels.provider(contract.provider_contact_id)
    return {
        **contract.model_dump(mode="json"),
        "provider_name": provider_name(provider),
        "status": terms.status(as_of),
        "effective_end": _day(terms.effective_end),
        "next_deadline": upcoming[0].as_dict(as_of) if upcoming else None,
        "locations": [location_view(location, labels) for location in locations],
        "property_ids": sorted({location.property_id for location in locations}),
        "current_advance": as_number(money(current.advance_amount)) if current and current.advance_amount else None,
        "current_advance_interval": current.advance_interval if current else None,
    }


def list_view(store: Any, *, as_of: date, property_id: str | None = None, unit_id: str | None = None,
              meter_id: str | None = None, contract_type: str | None = None, provider_contact_id: str | None = None,
              status: str | None = None, q: str | None = None) -> list[dict]:
    contracts = store.list_service_contracts()
    if contract_type:
        contracts = [c for c in contracts if c.contract_type == contract_type]
    if provider_contact_id:
        contracts = [c for c in contracts if c.provider_contact_id == provider_contact_id]
    ids = [c.id for c in contracts]
    locations = _group(store.list_service_contract_locations(service_contract_ids=ids)) if ids else {}
    tariffs = _group(store.list_service_contract_tariffs(service_contract_ids=ids)) if ids else {}
    labels = Labels(store)
    rows = []
    needle = (q or "").strip().lower()
    for contract in contracts:
        own = locations.get(contract.id, [])
        if property_id and not any(loc.property_id == property_id for loc in own):
            continue
        if unit_id and not any(loc.unit_id == unit_id for loc in own):
            continue
        if meter_id and not any(loc.meter_id == meter_id for loc in own):
            continue
        row = summary_view(contract, own, tariffs.get(contract.id, []), labels, as_of)
        if status and row["status"] != status:
            continue
        if needle and needle not in " ".join(str(row.get(k) or "") for k in (
                "title", "contract_number", "customer_number", "provider_name")).lower():
            continue
        rows.append(row)
    return sorted(rows, key=lambda r: (r["title"].lower(), r["id"]))


def detail_view(store: Any, contract_id: str, as_of: date) -> dict:
    contract = store.get_service_contract(contract_id)
    locations = store.list_service_contract_locations(contract_id)
    tariffs = store.list_service_contract_tariffs(contract_id)
    labels = Labels(store)
    provider = labels.provider(contract.provider_contact_id)
    return {
        **summary_view(contract, locations, tariffs, labels, as_of),
        "provider": provider.model_dump(mode="json") if provider else None,
        "tariffs": [tariff_view(t) for t in tariffs],
        "terms": terms_view(contract, tariffs, as_of),
        # some locations belong to portfolios this account cannot see: read only, partial figures
        "restricted": contract_has_hidden_locations(store, contract_id),
    }


def deadline_overview(store: Any, as_of: date, days: int) -> list[dict]:
    contracts = store.list_service_contracts()
    ids = [c.id for c in contracts]
    tariffs = _group(store.list_service_contract_tariffs(service_contract_ids=ids)) if ids else {}
    labels = Labels(store)
    found = []
    for contract in contracts:
        for deadline in deadlines(contract, tariffs.get(contract.id, []), as_of, days):
            found.append({**deadline.as_dict(as_of), "title": contract.title, "contract_type": contract.contract_type,
                          "provider_name": provider_name(labels.provider(contract.provider_contact_id))})
    return sorted(found, key=lambda d: (d["date"], d["title"], d["kind"]))


# --- money: expectation, bills, payments ---------------------------------------------------------

def instalments_view(store: Any, contract_id: str, date_from: date, date_to: date) -> dict:
    check_window(date_from, date_to)
    contract = store.get_service_contract(contract_id)
    tariffs = store.list_service_contract_tariffs(contract_id)
    items = planned_instalments(tariffs, contract.start_date, Terms.of(contract).effective_end, date_from, date_to)
    return {"date_from": _day(date_from), "date_to": _day(date_to),
            "total": as_number(sum((i.amount for i in items), ZERO)),
            "items": [{"due_date": _day(i.due_date), "amount": as_number(i.amount), "tariff_id": i.tariff_id}
                      for i in items]}


def _bills(store: Any, contract_id: str) -> list[tuple[Any, Any]]:
    pairs = []
    for link in store.list_service_contract_invoices(contract_id):
        invoice = _try(store.get_invoice, link.invoice_id)
        if invoice is not None:
            pairs.append((link, invoice))
    return sorted(pairs, key=lambda pair: (pair[1].invoice_date, pair[0].id))


def _payments(store: Any, contract_id: str) -> list[tuple[Any, Any]]:
    pairs = []
    for payment in store.list_service_contract_payments(contract_id):
        booking = _try(store.get_booking, payment.booking_id)
        if booking is not None:
            pairs.append((payment, booking))
    return sorted(pairs, key=lambda pair: (pair[1].booking_date, pair[0].id))


def _transfers_by_link(store: Any, link_ids: set[str]) -> dict[str, list[Any]]:
    periods = {p.id: p for p in store.list_billing_periods()}
    found: dict[str, list[Any]] = defaultdict(list)
    for item in store.list_cost_items():
        if item.service_contract_invoice_id in link_ids:
            period = periods.get(item.billing_period_id)
            found[item.service_contract_invoice_id].append({
                "cost_item_id": item.id, "billing_period_id": item.billing_period_id,
                "billing_period_label": period.label if period else None,
                "property_id": period.property_id if period else None, "amount": as_number(money(item.amount))})
    return found


def bills_view(store: Any, contract_id: str) -> list[dict]:
    contract = store.get_service_contract(contract_id)
    tariffs = store.list_service_contract_tariffs(contract_id)
    end = Terms.of(contract).effective_end
    bills = _bills(store, contract_id)
    paid: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for payment, _booking in _payments(store, contract_id):
        if payment.service_contract_invoice_id:
            paid[payment.service_contract_invoice_id] += money(payment.amount)
    transfers = _transfers_by_link(store, {link.id for link, _ in bills})
    rows = []
    for link, invoice in bills:
        gross, credited = money(invoice.gross_amount), money(link.advances_credited)
        planned = sum((i.amount for i in planned_instalments(tariffs, contract.start_date, end,
                                                              link.period_start, link.period_end)), ZERO)
        rows.append({
            **link.model_dump(mode="json"),
            "invoice": {"id": invoice.id, "supplier": invoice.supplier, "invoice_date": _day(invoice.invoice_date),
                        "due_date": _day(invoice.due_date), "invoice_number": getattr(invoice, "invoice_number", None),
                        "net_amount": as_number(money(invoice.net_amount)), "gross_amount": as_number(gross),
                        "status": invoice.status, "property_id": invoice.property_id,
                        "source_document_id": invoice.source_document_id},
            "advances_credited": as_number(credited),
            "balance": as_number(gross - credited),
            "planned_advances": as_number(planned),
            "paid": as_number(paid[link.id]),
            "open": as_number(gross - credited - paid[link.id]),
            "transfers": transfers.get(link.id, []),
        })
    return rows


def add_bill(store: Any, contract_id: str, request: InvoiceLinkRequest) -> Any:
    store.get_service_contract(contract_id)
    require_whole_contract(store, contract_id)
    invoice_id = request.invoice_id
    if invoice_id is not None and _try(store.get_invoice, invoice_id) is None:
        raise ValidationError("Rechnung existiert nicht")
    fields = request.model_dump(exclude={"invoice_id", "invoice"})
    data = ServiceContractInvoiceCreate(service_contract_id=contract_id, invoice_id=invoice_id or "new", **fields)
    if invoice_id is not None:
        with scope_context(None):          # a bill already linked elsewhere, also in another portfolio
            taken = store.list_service_contract_invoices(invoice_id=invoice_id)
        if taken:
            raise ValidationError("Diese Rechnung ist bereits einem Objektvertrag zugeordnet")
    return store.create_service_contract_invoice(data, request.invoice)


def update_bill(store: Any, contract_id: str, link_id: str, request: InvoiceLinkRequest) -> Any:
    current = store.get_service_contract_invoice(link_id)
    if current.service_contract_id != contract_id:
        raise NotFoundError("Rechnungszuordnung nicht gefunden")
    require_whole_contract(store, contract_id)
    if request.invoice is not None or (request.invoice_id and request.invoice_id != current.invoice_id):
        raise ValidationError("Die Rechnung einer Zuordnung wird nicht ausgetauscht; bitte neu zuordnen")
    if _transfers_by_link(store, {link_id}):
        raise ValidationError("Die Rechnung ist in eine Nebenkostenabrechnung übernommen; zuerst die "
                              "Kostenposition entfernen")
    fields = request.model_dump(exclude={"invoice_id", "invoice"})
    return store.update_service_contract_invoice(link_id, ServiceContractInvoiceCreate(
        service_contract_id=contract_id, invoice_id=current.invoice_id, **fields))


def remove_bill(store: Any, contract_id: str, link_id: str) -> None:
    current = store.get_service_contract_invoice(link_id)
    if current.service_contract_id != contract_id:
        raise NotFoundError("Rechnungszuordnung nicht gefunden")
    require_whole_contract(store, contract_id)
    with scope_context(None):
        transferred = _transfers_by_link(store, {link_id})
    if transferred:
        labels = ", ".join(t["billing_period_label"] or t["billing_period_id"] for t in transferred[link_id])
        raise HTTPException(409, f"Die Rechnung ist in die Nebenkostenabrechnung übernommen ({labels}). Zuerst "
                                 "die Kostenposition entfernen; eine finalisierte Abrechnung behält sie.")
    store.delete_service_contract_invoice(link_id)


def payments_view(store: Any, contract_id: str) -> list[dict]:
    store.get_service_contract(contract_id)
    rows = []
    for payment, booking in _payments(store, contract_id):
        rows.append({**payment.model_dump(mode="json"), "amount": as_number(money(payment.amount)),
                     "booking": {"id": booking.id, "booking_date": _day(booking.booking_date),
                                 "amount": as_number(money(booking.amount)), "payment_text": booking.payment_text,
                                 "account_id": booking.account_id, "property_id": booking.property_id}})
    return rows


def _allocated_elsewhere(store: Any, booking_id: str) -> Decimal:
    with scope_context(None):            # allocations of every contract count against the booking
        return sum((money(p.amount) for p in store.list_service_contract_payments(booking_id=booking_id)), ZERO)


def _is_tenant_money(store: Any, booking: Any) -> bool:
    return bool(booking.tenant_id) or bool(store.list_payment_allocations(booking_id=booking.id))


def add_payment(store: Any, contract_id: str, request: PaymentLinkRequest) -> Any:
    """Allocate (part of) a booking: paid = -booking amount; never more than the booking."""
    store.get_service_contract(contract_id)
    require_whole_contract(store, contract_id)
    booking = _try(store.get_booking, request.booking_id)
    if booking is None:
        raise ValidationError("Buchung existiert nicht")
    if _is_tenant_money(store, booking):
        raise ValidationError("Die Buchung ist eine Mieterzahlung und gehört nicht zu einem Objektvertrag")
    if request.service_contract_invoice_id:
        link = _try(store.get_service_contract_invoice, request.service_contract_invoice_id)
        if link is None or link.service_contract_id != contract_id:
            raise ValidationError("Die Rechnung gehört nicht zu diesem Vertrag")
    paid_total = -money(booking.amount)                     # outgoing booking: positive payment
    available = paid_total - _allocated_elsewhere(store, booking.id)
    amount = money(request.amount) if request.amount is not None else available
    if amount == 0:
        raise ValidationError("Die Buchung ist bereits vollständig zugeordnet")
    if (amount > 0) != (paid_total > 0):
        raise ValidationError("Das Vorzeichen passt nicht zur Buchung (Zahlung an den Anbieter positiv, "
                              "Erstattung negativ)")
    if abs(amount) > abs(available):
        raise ValidationError(f"Höchstens {as_number(available):.2f} € der Buchung sind noch nicht zugeordnet")
    return store.create_service_contract_payment(ServiceContractPaymentCreate(
        service_contract_id=contract_id, booking_id=booking.id, amount=float(amount),
        service_contract_invoice_id=request.service_contract_invoice_id, notes=request.notes))


def remove_payment(store: Any, contract_id: str, payment_id: str) -> None:
    require_whole_contract(store, contract_id)
    if store.get_service_contract_payment(payment_id).service_contract_id != contract_id:
        raise NotFoundError("Zahlungszuordnung nicht gefunden")
    store.delete_service_contract_payment(payment_id)


def payment_candidates(store: Any, contract_id: str, date_from: date, date_to: date, skip: int,
                       limit: int) -> dict:
    """Bookings that may pay the contract: not tenant money, not fully allocated, best matches first."""
    if date_to < date_from or (date_to - date_from).days > MAX_CANDIDATE_DAYS:
        raise ValidationError(f"Der Suchzeitraum muss zwischen 1 und {MAX_CANDIDATE_DAYS} Tagen liegen")
    contract = store.get_service_contract(contract_id)
    tariffs = store.list_service_contract_tariffs(contract_id)
    property_ids = {loc.property_id for loc in store.list_service_contract_locations(contract_id)}
    provider = provider_name(_try(store.get_contact, contract.provider_contact_id)).lower()
    provider_words = [w for w in provider.replace(",", " ").split() if len(w) >= 4]
    numbers = [n.lower() for n in (contract.contract_number, contract.customer_number) if n]
    already = {p.booking_id for p in store.list_service_contract_payments(contract_id)}
    bookings, page = [], 0
    while True:
        chunk = store._list_paginated("booking", skip=page * 1000, limit=1000,
                                      range_filters={"booking_date": (date_from, date_to)})
        bookings += chunk
        if len(chunk) < 1000:
            break
        page += 1
    tenant_bookings = {a.booking_id for a in store.list_payment_allocations(booking_ids=[b.id for b in bookings])} \
        if bookings else set()
    allocated: dict[str, Decimal] = defaultdict(lambda: ZERO)
    with scope_context(None):            # allocations of every contract count against a booking
        for payment in store.list_service_contract_payments():
            allocated[payment.booking_id] += money(payment.amount)
    found = []
    for booking in bookings:
        if booking.id in already or booking.tenant_id or booking.id in tenant_bookings or money(booking.amount) == 0:
            continue
        open_amount = -money(booking.amount) - allocated[booking.id]
        if open_amount == 0:
            continue
        text = (booking.payment_text or "").lower()
        score = 0
        reasons = []
        if any(n in text for n in numbers):
            score += 3
            reasons.append("number")
        if any(w in text for w in provider_words):
            score += 2
            reasons.append("provider")
        tariff = tariff_at(tariffs, booking.booking_date)
        if tariff and tariff.advance_amount and money(tariff.advance_amount) == open_amount:
            score += 2
            reasons.append("advance")
        if booking.property_id and booking.property_id in property_ids:
            score += 1
            reasons.append("property")
        found.append({"booking_id": booking.id, "booking_date": _day(booking.booking_date),
                      "amount": as_number(money(booking.amount)), "open_amount": as_number(open_amount),
                      "payment_text": booking.payment_text, "property_id": booking.property_id, "score": score,
                      "reasons": reasons})
    found.sort(key=lambda c: (-c["score"], c["booking_date"], c["booking_id"]))
    return {"date_from": _day(date_from), "date_to": _day(date_to), "total": len(found),
            "items": found[skip:skip + limit], "has_more": skip + limit < len(found)}


def reconciliation_view(store: Any, contract_id: str, date_from: date, date_to: date) -> dict:
    check_window(date_from, date_to)
    contract = store.get_service_contract(contract_id)
    result = reconcile(tariffs=store.list_service_contract_tariffs(contract_id), contract_start=contract.start_date,
                       contract_end=Terms.of(contract).effective_end, invoices=_bills(store, contract_id),
                       payments=_payments(store, contract_id), window_from=date_from, window_to=date_to)
    return {
        "date_from": _day(date_from), "date_to": _day(date_to),
        "expected": as_number(result.expected),
        "invoiced": as_number(result.invoiced),
        "credited": as_number(result.credited),
        "invoice_balance": as_number(result.invoice_balance),
        "obligations": as_number(result.obligations),
        "paid": as_number(result.paid),
        "open": as_number(result.open),
        "costs": as_number(result.costs),
        "instalments": [{"due_date": _day(i.due_date), "amount": as_number(i.amount), "tariff_id": i.tariff_id}
                        for i in result.instalments],
        "invoices": [{"service_contract_invoice_id": f.link_id, "invoice_id": f.invoice_id,
                      "invoice_date": _day(f.invoice_date), "period_start": _day(f.period_start),
                      "period_end": _day(f.period_end), "gross": as_number(f.gross),
                      "credited": as_number(f.credited), "balance": as_number(f.balance),
                      "planned_advances": as_number(f.planned_advances), "paid": as_number(f.paid)}
                     for f in result.invoices],
        # an account that misses some locations sees only the bills and payments it may see
        "partial": contract_has_hidden_locations(store, contract_id),
    }


# --- documents -----------------------------------------------------------------------------------

def documents_view(store: Any, contract_id: str) -> list[dict]:
    store.get_service_contract(contract_id)
    rows = []
    for link in store.list_service_contract_documents(contract_id):
        document = _try(store.get_document, link.document_id)
        if document is not None:
            rows.append({"link_id": link.id, "source": "contract", **document.model_dump(mode="json")})
    linked = {row["id"] for row in rows}
    for _link, invoice in _bills(store, contract_id):
        document = _try(store.get_document, invoice.source_document_id)
        if document is not None and document.id not in linked:
            linked.add(document.id)
            rows.append({"link_id": None, "source": "invoice", "invoice_id": invoice.id,
                         **document.model_dump(mode="json")})
    return rows


def add_document(store: Any, contract_id: str, document_id: str) -> Any:
    store.get_service_contract(contract_id)
    require_whole_contract(store, contract_id)
    if _try(store.get_document, document_id) is None:
        raise ValidationError("Dokument existiert nicht")
    return store.create_service_contract_document(
        ServiceContractDocumentCreate(service_contract_id=contract_id, document_id=document_id))


def remove_document(store: Any, contract_id: str, link_id: str) -> None:
    require_whole_contract(store, contract_id)
    if store.get_service_contract_document(link_id).service_contract_id != contract_id:
        raise NotFoundError("Dokumentzuordnung nicht gefunden")
    store.delete_service_contract_document(link_id)


# --- utility billing: recoverable bills become cost items ----------------------------------------

def transfers_view(store: Any, contract_id: str) -> list[dict]:
    links = {link.id for link in store.list_service_contract_invoices(contract_id)}
    return [{"service_contract_invoice_id": link_id, **row}
            for link_id, rows in _transfers_by_link(store, links).items() for row in rows]


def transfer_costs(store: Any, contract_id: str, request: CostTransferRequest) -> dict:
    """Recoverable bills of the contract enter a billing period as cost items, each bill once per period.

    Amount: the bill's gross, prorated to the service days inside the billing period,
    the property's share of the location weights, the recoverable percentage.
    """
    contract = store.get_service_contract(contract_id)
    if not contract.recoverable:
        raise ValidationError("Der Vertrag ist nicht als umlagefähig markiert")
    require_whole_contract(store, contract_id)
    period = _try(store.get_billing_period, request.billing_period_id)
    if period is None:
        raise ValidationError("Abrechnungsperiode existiert nicht")
    if period.status not in EDITABLE_STATUSES:
        raise HTTPException(409, f"Die Abrechnungsperiode ist '{period.status}' und nimmt keine Kosten mehr auf; "
                                 "Änderungen nur über eine Korrektur")
    key = _try(store.get_allocation_key, request.allocation_key_id)
    if key is None or key.property_id != period.property_id:
        raise ValidationError("Der Verteilerschlüssel gehört nicht zum Objekt der Abrechnungsperiode")
    locations = store.list_service_contract_locations(contract_id)
    if not property_weights(locations, period.start_date, period.end_date).get(period.property_id):
        raise ValidationError("Das Objekt der Abrechnungsperiode ist im Zeitraum kein Standort dieses Vertrags")
    bills = _bills(store, contract_id)
    wanted = set(request.invoice_link_ids) if request.invoice_link_ids is not None else None
    if wanted is not None and wanted - {link.id for link, _ in bills}:
        raise ValidationError("Eine gewählte Rechnung gehört nicht zu diesem Vertrag")
    present = {item.service_contract_invoice_id for item in store.list_cost_items()
               if item.billing_period_id == period.id and item.service_contract_invoice_id}
    items: list[CostItemCreate] = []
    skipped: list[dict] = []
    for link, invoice in bills:
        if wanted is not None and link.id not in wanted:
            continue
        if link.id in present:
            skipped.append({"service_contract_invoice_id": link.id, "reason": "already_transferred"})
            continue
        if not overlap_days(link.period_start, link.period_end, period.start_date, period.end_date):
            if wanted is not None:
                skipped.append({"service_contract_invoice_id": link.id, "reason": "outside_period"})
            continue
        gross = money(invoice.gross_amount)
        inside = prorated(gross, link.period_start, link.period_end, period.start_date, period.end_date)
        start, end = max(link.period_start, period.start_date), min(link.period_end, period.end_date)
        share = property_share(inside, property_weights(locations, start, end), period.property_id)
        amount = recoverable_part(share, contract.recoverable_percent)
        if amount == 0:
            skipped.append({"service_contract_invoice_id": link.id, "reason": "zero"})
            continue
        net = cents(amount * money(invoice.net_amount) / gross) if gross else amount
        number = getattr(invoice, "invoice_number", None)
        what = f"Rechnung {number}" if number else f"Rechnung vom {_de(invoice.invoice_date)}"
        notes = []
        if inside != gross:
            notes.append(f"{_de(start)}–{_de(end)}")
        if share != inside:
            notes.append("Anteil des Objekts")
        if amount != share:
            notes.append(f"{float(contract.recoverable_percent):g} % umlagefähig")
        items.append(CostItemCreate(
            billing_period_id=period.id, allocation_key_id=key.id, is_recoverable=True,
            description=f"{contract.title}: {what} (Leistung {_de(link.period_start)}–{_de(link.period_end)}"
                        + (f"; {', '.join(notes)}" if notes else "") + ")",
            amount=float(amount), gross_amount=float(amount), net_amount=float(net),
            vat_rate=invoice.vat_rate, cost_category=contract.cost_category,
            source_document_id=invoice.source_document_id, service_contract_invoice_id=link.id))
    created = store.create_cost_items_together(items) if items else []
    return {"created": [item.model_dump(mode="json") for item in created], "skipped": skipped}


def check_cost_item_origin(store: Any, data: Any, exclude_id: str | None = None) -> None:
    """A cost item that names a contract bill: the bill exists and its contract covers the period's property."""
    link_id = getattr(data, "service_contract_invoice_id", None)
    if not link_id:
        return
    link = _try(store.get_service_contract_invoice, link_id)
    period = _try(store.get_billing_period, data.billing_period_id)
    if link is None or period is None:
        raise ValidationError("Die Herkunftsrechnung des Objektvertrags existiert nicht")
    if any(item.billing_period_id == period.id and item.service_contract_invoice_id == link_id
           and item.id != exclude_id for item in store.list_cost_items()):
        raise ValidationError("Diese Rechnung ist in der Abrechnungsperiode bereits enthalten")
    if not any(loc.property_id == period.property_id
               for loc in store.list_service_contract_locations(link.service_contract_id)):
        raise ValidationError("Der Objektvertrag der Herkunftsrechnung hat keinen Standort im Objekt der Periode")
