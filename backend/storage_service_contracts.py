"""In-memory store of property service contracts (mixed into storage.InMemoryStore).

Business rules live in services/service_contracts.py; this keeps the records, the
cascades the SQL schema has (ON DELETE) and all-or-nothing writes of one operation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from .models_service_contracts import (
    LocationInput,
    ServiceContract,
    ServiceContractCreate,
    ServiceContractDocument,
    ServiceContractDocumentCreate,
    ServiceContractInvoice,
    ServiceContractInvoiceCreate,
    ServiceContractLocation,
    ServiceContractLocationCreate,
    ServiceContractPayment,
    ServiceContractPaymentCreate,
    ServiceContractTariff,
    ServiceContractTariffCreate,
    TariffInput,
)
from .store_errors import NotFoundError, ValidationError

CONTRACT_CHILDREN = ("service_contract_locations", "service_contract_tariffs", "service_contract_documents",
                     "service_contract_payments", "service_contract_invoices")


def _id() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get(collection: Any, key: str, message: str) -> Any:
    try:
        return collection[key]
    except KeyError as exc:
        raise NotFoundError(message) from exc


@dataclass
class ServiceContractMemoryStore:
    service_contracts: Dict[str, ServiceContract] = field(default_factory=dict)
    service_contract_locations: Dict[str, ServiceContractLocation] = field(default_factory=dict)
    service_contract_tariffs: Dict[str, ServiceContractTariff] = field(default_factory=dict)
    service_contract_invoices: Dict[str, ServiceContractInvoice] = field(default_factory=dict)
    service_contract_payments: Dict[str, ServiceContractPayment] = field(default_factory=dict)
    service_contract_documents: Dict[str, ServiceContractDocument] = field(default_factory=dict)

    def _raw_collection(self, name: str) -> dict:
        return object.__getattribute__(self, name)

    def _write_all(self, rows: list[tuple[str, Any]], together: Iterable[tuple[str, str]] = ()) -> None:
        """Write the rows in order; on any refusal none of them stays."""
        from .services.portfolio_scope import created_together

        written: list[tuple[str, str]] = []
        try:
            with created_together(together):
                for name, row in rows:
                    getattr(self, name)[row.id] = row
                    written.append((name, row.id))
        except BaseException:
            for name, key in reversed(written):
                self._raw_collection(name).pop(key, None)
            raise

    # --- contracts --------------------------------------------------------------------------

    def list_service_contracts(self) -> List[ServiceContract]:
        return list(self.service_contracts.values())

    def list_service_contracts_after(self, after: str, limit: int) -> List[ServiceContract]:
        return sorted((c for c in self.service_contracts.values() if c.id > after), key=lambda c: c.id)[:limit]

    def get_service_contract(self, contract_id: str) -> ServiceContract:
        return _get(self.service_contracts, contract_id, "Objektvertrag nicht gefunden")

    def create_service_contract(self, data: ServiceContractCreate, locations: List[LocationInput],
                                tariff: Optional[TariffInput] = None) -> ServiceContract:
        contract = ServiceContract(id=_id(), **data.model_dump())
        rows: list[tuple[str, Any]] = [("service_contracts", contract)]
        rows += [("service_contract_locations", ServiceContractLocation(
            id=_id(), service_contract_id=contract.id, **location.model_dump())) for location in locations]
        if tariff is not None:
            rows.append(("service_contract_tariffs", ServiceContractTariff(
                id=_id(), service_contract_id=contract.id, **tariff.model_dump())))
        self._write_all(rows, together=[("service_contracts", contract.id)])
        return contract

    def update_service_contract(self, contract_id: str, data: ServiceContractCreate) -> ServiceContract:
        old = self.get_service_contract(contract_id)
        contract = ServiceContract(id=contract_id, created_at=old.created_at, updated_at=_now(), **data.model_dump())
        self.service_contracts[contract_id] = contract
        return contract

    def delete_service_contract(self, contract_id: str) -> None:
        self.get_service_contract(contract_id)
        # children first: each removal is checked against the account's portfolios
        for name in CONTRACT_CHILDREN:
            collection = getattr(self, name)
            for key in [k for k, row in self._raw_collection(name).items() if row.service_contract_id == contract_id]:
                del collection[key]
        del self.service_contracts[contract_id]

    # --- locations ----------------------------------------------------------------------------

    def list_service_contract_locations(self, service_contract_id: Optional[str] = None,
                                        service_contract_ids: Optional[Iterable[str]] = None
                                        ) -> List[ServiceContractLocation]:
        wanted = set(service_contract_ids) if service_contract_ids is not None else None
        return [row for row in self.service_contract_locations.values()
                if (service_contract_id is None or row.service_contract_id == service_contract_id)
                and (wanted is None or row.service_contract_id in wanted)]

    def get_service_contract_location(self, location_id: str) -> ServiceContractLocation:
        return _get(self.service_contract_locations, location_id, "Standort nicht gefunden")

    def create_service_contract_location(self, data: ServiceContractLocationCreate) -> ServiceContractLocation:
        row = ServiceContractLocation(id=_id(), **data.model_dump())
        self.service_contract_locations[row.id] = row
        return row

    def update_service_contract_location(self, location_id: str,
                                         data: ServiceContractLocationCreate) -> ServiceContractLocation:
        old = self.get_service_contract_location(location_id)
        row = ServiceContractLocation(id=location_id, created_at=old.created_at, updated_at=_now(), **data.model_dump())
        self.service_contract_locations[location_id] = row
        return row

    def delete_service_contract_location(self, location_id: str) -> None:
        self.get_service_contract_location(location_id)
        del self.service_contract_locations[location_id]

    # --- tariffs ------------------------------------------------------------------------------

    def list_service_contract_tariffs(self, service_contract_id: Optional[str] = None,
                                      service_contract_ids: Optional[Iterable[str]] = None
                                      ) -> List[ServiceContractTariff]:
        wanted = set(service_contract_ids) if service_contract_ids is not None else None
        rows = [row for row in self.service_contract_tariffs.values()
                if (service_contract_id is None or row.service_contract_id == service_contract_id)
                and (wanted is None or row.service_contract_id in wanted)]
        return sorted(rows, key=lambda row: (row.service_contract_id, row.valid_from))

    def get_service_contract_tariff(self, tariff_id: str) -> ServiceContractTariff:
        return _get(self.service_contract_tariffs, tariff_id, "Tarif nicht gefunden")

    def _check_tariff_date(self, data: ServiceContractTariffCreate, exclude_id: Optional[str] = None) -> None:
        if any(row.id != exclude_id and row.service_contract_id == data.service_contract_id
               and row.valid_from == data.valid_from for row in self._raw_collection("service_contract_tariffs").values()):
            raise ValidationError("Für dieses Datum gibt es schon einen Tarif")

    def create_service_contract_tariff(self, data: ServiceContractTariffCreate) -> ServiceContractTariff:
        self._check_tariff_date(data)
        row = ServiceContractTariff(id=_id(), **data.model_dump())
        self.service_contract_tariffs[row.id] = row
        return row

    def update_service_contract_tariff(self, tariff_id: str, data: ServiceContractTariffCreate) -> ServiceContractTariff:
        old = self.get_service_contract_tariff(tariff_id)
        self._check_tariff_date(data, exclude_id=tariff_id)
        row = ServiceContractTariff(id=tariff_id, created_at=old.created_at, updated_at=_now(), **data.model_dump())
        self.service_contract_tariffs[tariff_id] = row
        return row

    def delete_service_contract_tariff(self, tariff_id: str) -> None:
        self.get_service_contract_tariff(tariff_id)
        del self.service_contract_tariffs[tariff_id]

    # --- bills --------------------------------------------------------------------------------

    def list_service_contract_invoices(self, service_contract_id: Optional[str] = None,
                                       invoice_id: Optional[str] = None) -> List[ServiceContractInvoice]:
        return [row for row in self.service_contract_invoices.values()
                if (service_contract_id is None or row.service_contract_id == service_contract_id)
                and (invoice_id is None or row.invoice_id == invoice_id)]

    def get_service_contract_invoice(self, link_id: str) -> ServiceContractInvoice:
        return _get(self.service_contract_invoices, link_id, "Rechnungszuordnung nicht gefunden")

    def _check_invoice_free(self, invoice_id: str, exclude_id: Optional[str] = None) -> None:
        if any(row.invoice_id == invoice_id and row.id != exclude_id
               for row in self._raw_collection("service_contract_invoices").values()):
            raise ValidationError("Diese Rechnung ist bereits einem Objektvertrag zugeordnet")

    def create_service_contract_invoice(self, data: ServiceContractInvoiceCreate,
                                        invoice: Any = None) -> ServiceContractInvoice:
        """Link a bill; with `invoice` (InvoiceCreate) the bill is created in the same step."""
        from .models import Invoice

        rows: list[tuple[str, Any]] = []
        if invoice is not None:
            if invoice.property_id and invoice.property_id not in self.properties:  # type: ignore[attr-defined]
                raise ValidationError("Immobilie existiert nicht")
            created = Invoice(id=_id(), **invoice.model_dump())
            rows.append(("invoices", created))
            data = data.model_copy(update={"invoice_id": created.id})
        self._check_invoice_free(data.invoice_id)
        link = ServiceContractInvoice(id=_id(), **data.model_dump())
        rows.append(("service_contract_invoices", link))
        self._write_all(rows)
        return link

    def update_service_contract_invoice(self, link_id: str,
                                        data: ServiceContractInvoiceCreate) -> ServiceContractInvoice:
        old = self.get_service_contract_invoice(link_id)
        self._check_invoice_free(data.invoice_id, exclude_id=link_id)
        row = ServiceContractInvoice(id=link_id, created_at=old.created_at, updated_at=_now(), **data.model_dump())
        self.service_contract_invoices[link_id] = row
        return row

    def delete_service_contract_invoice(self, link_id: str) -> None:
        self.get_service_contract_invoice(link_id)
        # ON DELETE SET NULL of the payments that settled this bill
        payments = self._raw_collection("service_contract_payments")
        for key, payment in list(payments.items()):
            if payment.service_contract_invoice_id == link_id:
                payments[key] = payment.model_copy(update={"service_contract_invoice_id": None})
        del self.service_contract_invoices[link_id]

    # --- payments -----------------------------------------------------------------------------

    def list_service_contract_payments(self, service_contract_id: Optional[str] = None,
                                       booking_id: Optional[str] = None) -> List[ServiceContractPayment]:
        return [row for row in self.service_contract_payments.values()
                if (service_contract_id is None or row.service_contract_id == service_contract_id)
                and (booking_id is None or row.booking_id == booking_id)]

    def get_service_contract_payment(self, payment_id: str) -> ServiceContractPayment:
        return _get(self.service_contract_payments, payment_id, "Zahlungszuordnung nicht gefunden")

    def create_service_contract_payment(self, data: ServiceContractPaymentCreate) -> ServiceContractPayment:
        if any(row.service_contract_id == data.service_contract_id and row.booking_id == data.booking_id
               for row in self._raw_collection("service_contract_payments").values()):
            raise ValidationError("Diese Buchung ist dem Vertrag bereits zugeordnet")
        row = ServiceContractPayment(id=_id(), **data.model_dump())
        self.service_contract_payments[row.id] = row
        return row

    def delete_service_contract_payment(self, payment_id: str) -> None:
        self.get_service_contract_payment(payment_id)
        del self.service_contract_payments[payment_id]

    # --- documents ----------------------------------------------------------------------------

    def list_service_contract_documents(self, service_contract_id: Optional[str] = None,
                                        document_id: Optional[str] = None) -> List[ServiceContractDocument]:
        return [row for row in self.service_contract_documents.values()
                if (service_contract_id is None or row.service_contract_id == service_contract_id)
                and (document_id is None or row.document_id == document_id)]

    def get_service_contract_document(self, link_id: str) -> ServiceContractDocument:
        return _get(self.service_contract_documents, link_id, "Dokumentzuordnung nicht gefunden")

    def create_service_contract_document(self, data: ServiceContractDocumentCreate) -> ServiceContractDocument:
        if any(row.service_contract_id == data.service_contract_id and row.document_id == data.document_id
               for row in self._raw_collection("service_contract_documents").values()):
            raise ValidationError("Das Dokument ist dem Vertrag bereits zugeordnet")
        row = ServiceContractDocument(id=_id(), **data.model_dump())
        self.service_contract_documents[row.id] = row
        return row

    def delete_service_contract_document(self, link_id: str) -> None:
        self.get_service_contract_document(link_id)
        del self.service_contract_documents[link_id]

    # --- utility billing ----------------------------------------------------------------------

    def create_cost_items_together(self, items: List[Any]) -> List[Any]:
        """Cost items of one transfer: all or none (a bill reaches a period once)."""
        from .models import CostItem

        rows: list[tuple[str, Any]] = []
        existing = self._raw_collection("cost_items")
        for data in items:
            if data.billing_period_id not in self.billing_periods:  # type: ignore[attr-defined]
                raise ValidationError("Abrechnungsperiode existiert nicht")
            if data.allocation_key_id not in self.allocation_keys:  # type: ignore[attr-defined]
                raise ValidationError("Verteilerschlüssel existiert nicht")
            if data.service_contract_invoice_id and any(
                    item.billing_period_id == data.billing_period_id
                    and item.service_contract_invoice_id == data.service_contract_invoice_id
                    for item in existing.values()):
                raise ValidationError("Diese Rechnung ist in der Abrechnungsperiode bereits enthalten")
            rows.append(("cost_items", CostItem(id=_id(), **data.model_dump())))
        self._write_all(rows)
        return [row for _, row in rows]

    # --- cascades of the SQL schema (called by the store's own deletes) ---------------------

    def _drop_service_contract_rows(self, name: str, field_name: str, value: str) -> None:
        raw = self._raw_collection(name)
        for key in [k for k, row in raw.items() if getattr(row, field_name) == value]:
            del raw[key]

    def _forget_meter_in_locations(self, meter_id: str) -> None:
        raw = self._raw_collection("service_contract_locations")
        for key, row in list(raw.items()):
            if row.meter_id == meter_id:
                raw[key] = row.model_copy(update={"meter_id": None})
