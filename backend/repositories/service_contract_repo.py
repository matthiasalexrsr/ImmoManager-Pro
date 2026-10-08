"""SQL store of property service contracts: records, all-or-nothing writes, the job's paging.

Every write goes through the request's session, so the portfolio boundary checks each
row (services/portfolio_scope.py). Multi-row operations commit once; a contract and
its locations are flushed in two steps (parent first) inside one transaction.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db.orm_models import AllocationKeyORM, BillingPeriodORM, CostItemORM, InvoiceORM, PropertyORM
from ..db.service_contract_models import (
    ServiceContractDocumentORM,
    ServiceContractInvoiceORM,
    ServiceContractLocationORM,
    ServiceContractORM,
    ServiceContractPaymentORM,
    ServiceContractTariffORM,
)
from ..models import CostItem
from ..models_service_contracts import (
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
from ..store_errors import ValidationError
from .base import BaseRepository

logger = logging.getLogger(__name__)


def _id() -> str:
    return str(uuid4())


class ServiceContractRepository:
    def __init__(self, db: Session):
        self.db = db
        self._contracts = BaseRepository(db, ServiceContractORM, ServiceContract, "Objektvertrag nicht gefunden")
        self._locations = BaseRepository(db, ServiceContractLocationORM, ServiceContractLocation,
                                         "Standort nicht gefunden")
        self._tariffs = BaseRepository(db, ServiceContractTariffORM, ServiceContractTariff, "Tarif nicht gefunden")
        self._invoices = BaseRepository(db, ServiceContractInvoiceORM, ServiceContractInvoice,
                                        "Rechnungszuordnung nicht gefunden")
        self._payments = BaseRepository(db, ServiceContractPaymentORM, ServiceContractPayment,
                                        "Zahlungszuordnung nicht gefunden")
        self._documents = BaseRepository(db, ServiceContractDocumentORM, ServiceContractDocument,
                                         "Dokumentzuordnung nicht gefunden")
        self._cost_items = BaseRepository(db, CostItemORM, CostItem, "Kostenposition nicht gefunden")

    def _commit_or_explain(self, message: str) -> None:
        """Commit; a broken unique rule or reference becomes a readable refusal (nothing is kept)."""
        try:
            self.db.flush()
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            logger.info("Service contract write refused: %s", exc.orig)
            raise ValidationError(message) from exc
        except BaseException:
            self.db.rollback()
            raise

    def _stage(self, *rows: Any, refusal: str = "Die Angaben widersprechen gespeicherten Daten") -> None:
        try:
            self.db.add_all(rows)
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            logger.info("Service contract write refused: %s", exc.orig)
            raise ValidationError(refusal) from exc
        except BaseException:
            self.db.rollback()
            raise

    # --- contracts --------------------------------------------------------------------------

    def list_service_contracts(self) -> list[ServiceContract]:
        return self._contracts.list_all()

    def list_service_contracts_after(self, after: str, limit: int) -> list[ServiceContract]:
        query = self.db.query(ServiceContractORM).filter(ServiceContractORM.id > after).order_by(
            ServiceContractORM.id).limit(limit)
        return self._contracts._read(query)

    def get_service_contract(self, contract_id: str) -> ServiceContract:
        return self._contracts.get(contract_id)

    def create_service_contract(self, data: ServiceContractCreate, locations: list[LocationInput],
                                tariff: TariffInput | None = None) -> ServiceContract:
        contract_id = _id()
        self._stage(ServiceContractORM(id=contract_id, **data.model_dump()))
        children: list[Any] = [ServiceContractLocationORM(id=_id(), service_contract_id=contract_id,
                                                          **location.model_dump()) for location in locations]
        if tariff is not None:
            children.append(ServiceContractTariffORM(id=_id(), service_contract_id=contract_id,
                                                     **tariff.model_dump()))
        self._stage(*children)
        self._commit_or_explain("Der Objektvertrag konnte nicht gespeichert werden")
        return self._contracts.get(contract_id)

    def update_service_contract(self, contract_id: str, data: ServiceContractCreate) -> ServiceContract:
        result = self._contracts.update(contract_id, data)
        self.db.commit()
        return result

    def delete_service_contract(self, contract_id: str) -> None:
        # locations, tariffs, links: ON DELETE CASCADE
        self._contracts.delete(contract_id)
        self.db.commit()

    # --- locations ----------------------------------------------------------------------------

    def list_service_contract_locations(self, service_contract_id: str | None = None,
                                        service_contract_ids: Iterable[str] | None = None
                                        ) -> list[ServiceContractLocation]:
        if service_contract_ids is not None:
            return self._locations.filter_in("service_contract_id", service_contract_ids)
        return self._locations.filter_by(service_contract_id=service_contract_id)

    def get_service_contract_location(self, location_id: str) -> ServiceContractLocation:
        return self._locations.get(location_id)

    def create_service_contract_location(self, data: ServiceContractLocationCreate) -> ServiceContractLocation:
        result = self._locations.create(data)
        self.db.commit()
        return result

    def update_service_contract_location(self, location_id: str,
                                         data: ServiceContractLocationCreate) -> ServiceContractLocation:
        result = self._locations.update(location_id, data)
        self.db.commit()
        return result

    def delete_service_contract_location(self, location_id: str) -> None:
        self._locations.delete(location_id)
        self.db.commit()

    # --- tariffs ------------------------------------------------------------------------------

    def list_service_contract_tariffs(self, service_contract_id: str | None = None,
                                      service_contract_ids: Iterable[str] | None = None
                                      ) -> list[ServiceContractTariff]:
        if service_contract_ids is not None:
            rows = self._tariffs.filter_in("service_contract_id", service_contract_ids)
        else:
            rows = self._tariffs.filter_by(service_contract_id=service_contract_id)
        return sorted(rows, key=lambda row: (row.service_contract_id, row.valid_from))

    def get_service_contract_tariff(self, tariff_id: str) -> ServiceContractTariff:
        return self._tariffs.get(tariff_id)

    def _tariff_date_taken(self, data: ServiceContractTariffCreate, exclude_id: str | None = None) -> bool:
        from ..services.portfolio_scope import BOUNDED

        query = select(ServiceContractTariffORM.id).where(
            ServiceContractTariffORM.service_contract_id == data.service_contract_id,
            ServiceContractTariffORM.valid_from == data.valid_from)
        if exclude_id:
            query = query.where(ServiceContractTariffORM.id != exclude_id)
        # the contract was checked whole: its tariffs are all visible, no further boundary needed
        return self.db.scalar(query.limit(1).execution_options(**{BOUNDED: True})) is not None

    def create_service_contract_tariff(self, data: ServiceContractTariffCreate) -> ServiceContractTariff:
        if self._tariff_date_taken(data):
            raise ValidationError("Für dieses Datum gibt es schon einen Tarif")
        tariff_id = _id()
        self._stage(ServiceContractTariffORM(id=tariff_id, **data.model_dump()),
                    refusal="Für dieses Datum gibt es schon einen Tarif")
        self._commit_or_explain("Für dieses Datum gibt es schon einen Tarif")
        return self._tariffs.get(tariff_id)

    def update_service_contract_tariff(self, tariff_id: str, data: ServiceContractTariffCreate) -> ServiceContractTariff:
        if self._tariff_date_taken(data, exclude_id=tariff_id):
            raise ValidationError("Für dieses Datum gibt es schon einen Tarif")
        orm = self._tariffs.get_orm(tariff_id)
        for key, value in data.model_dump().items():
            setattr(orm, key, value)
        self._commit_or_explain("Für dieses Datum gibt es schon einen Tarif")
        return self._tariffs.get(tariff_id)

    def delete_service_contract_tariff(self, tariff_id: str) -> None:
        self._tariffs.delete(tariff_id)
        self.db.commit()

    # --- bills --------------------------------------------------------------------------------

    def list_service_contract_invoices(self, service_contract_id: str | None = None,
                                       invoice_id: str | None = None) -> list[ServiceContractInvoice]:
        return self._invoices.filter_by(service_contract_id=service_contract_id, invoice_id=invoice_id)

    def get_service_contract_invoice(self, link_id: str) -> ServiceContractInvoice:
        return self._invoices.get(link_id)

    def create_service_contract_invoice(self, data: ServiceContractInvoiceCreate,
                                        invoice: Any = None) -> ServiceContractInvoice:
        if invoice is not None:
            if invoice.property_id and self.db.get(PropertyORM, invoice.property_id) is None:
                raise ValidationError("Immobilie existiert nicht")
            invoice_id = _id()
            self._stage(InvoiceORM(id=invoice_id, **invoice.model_dump()))
            data = data.model_copy(update={"invoice_id": invoice_id})
        link_id = _id()
        self._stage(ServiceContractInvoiceORM(id=link_id, **data.model_dump()),
                    refusal="Diese Rechnung ist bereits einem Objektvertrag zugeordnet")
        self._commit_or_explain("Diese Rechnung ist bereits einem Objektvertrag zugeordnet")
        return self._invoices.get(link_id)

    def update_service_contract_invoice(self, link_id: str,
                                        data: ServiceContractInvoiceCreate) -> ServiceContractInvoice:
        orm = self._invoices.get_orm(link_id)
        for key, value in data.model_dump().items():
            setattr(orm, key, value)
        self._commit_or_explain("Diese Rechnung ist bereits einem Objektvertrag zugeordnet")
        return self._invoices.get(link_id)

    def delete_service_contract_invoice(self, link_id: str) -> None:
        # payments that settled this bill keep their amount (ON DELETE SET NULL)
        self._invoices.delete(link_id)
        self.db.commit()

    # --- payments -----------------------------------------------------------------------------

    def list_service_contract_payments(self, service_contract_id: str | None = None,
                                       booking_id: str | None = None) -> list[ServiceContractPayment]:
        return self._payments.filter_by(service_contract_id=service_contract_id, booking_id=booking_id)

    def get_service_contract_payment(self, payment_id: str) -> ServiceContractPayment:
        return self._payments.get(payment_id)

    def create_service_contract_payment(self, data: ServiceContractPaymentCreate) -> ServiceContractPayment:
        payment_id = _id()
        self._stage(ServiceContractPaymentORM(id=payment_id, **data.model_dump()),
                    refusal="Diese Buchung ist dem Vertrag bereits zugeordnet")
        self._commit_or_explain("Diese Buchung ist dem Vertrag bereits zugeordnet")
        return self._payments.get(payment_id)

    def delete_service_contract_payment(self, payment_id: str) -> None:
        self._payments.delete(payment_id)
        self.db.commit()

    # --- documents ----------------------------------------------------------------------------

    def list_service_contract_documents(self, service_contract_id: str | None = None,
                                        document_id: str | None = None) -> list[ServiceContractDocument]:
        return self._documents.filter_by(service_contract_id=service_contract_id, document_id=document_id)

    def get_service_contract_document(self, link_id: str) -> ServiceContractDocument:
        return self._documents.get(link_id)

    def create_service_contract_document(self, data: ServiceContractDocumentCreate) -> ServiceContractDocument:
        link_id = _id()
        self._stage(ServiceContractDocumentORM(id=link_id, **data.model_dump()),
                    refusal="Das Dokument ist dem Vertrag bereits zugeordnet")
        self._commit_or_explain("Das Dokument ist dem Vertrag bereits zugeordnet")
        return self._documents.get(link_id)

    def delete_service_contract_document(self, link_id: str) -> None:
        self._documents.delete(link_id)
        self.db.commit()

    # --- utility billing ----------------------------------------------------------------------

    def create_cost_items_together(self, items: list[Any]) -> list[CostItem]:
        ids = []
        for data in items:
            if self.db.get(BillingPeriodORM, data.billing_period_id) is None:
                raise ValidationError("Abrechnungsperiode existiert nicht")
            if self.db.get(AllocationKeyORM, data.allocation_key_id) is None:
                raise ValidationError("Verteilerschlüssel existiert nicht")
            ids.append(_id())
        self._stage(*(CostItemORM(id=item_id, **data.model_dump()) for item_id, data in zip(ids, items)),
                    refusal="Diese Rechnung ist in der Abrechnungsperiode bereits enthalten")
        self._commit_or_explain("Diese Rechnung ist in der Abrechnungsperiode bereits enthalten")
        return [self._cost_items.get(item_id) for item_id in ids]


class ServiceContractStoreMethods:
    """SQLAlchemyStore delegations (the store's public API, same as the memory store's)."""

    service_contracts_repo: ServiceContractRepository

    def list_service_contracts(self):
        return self.service_contracts_repo.list_service_contracts()

    def list_service_contracts_after(self, after, limit):
        return self.service_contracts_repo.list_service_contracts_after(after, limit)

    def get_service_contract(self, contract_id):
        return self.service_contracts_repo.get_service_contract(contract_id)

    def create_service_contract(self, data, locations, tariff=None):
        return self.service_contracts_repo.create_service_contract(data, locations, tariff)

    def update_service_contract(self, contract_id, data):
        return self.service_contracts_repo.update_service_contract(contract_id, data)

    def delete_service_contract(self, contract_id):
        self.service_contracts_repo.delete_service_contract(contract_id)

    def list_service_contract_locations(self, service_contract_id=None, service_contract_ids=None):
        return self.service_contracts_repo.list_service_contract_locations(service_contract_id, service_contract_ids)

    def get_service_contract_location(self, location_id):
        return self.service_contracts_repo.get_service_contract_location(location_id)

    def create_service_contract_location(self, data):
        return self.service_contracts_repo.create_service_contract_location(data)

    def update_service_contract_location(self, location_id, data):
        return self.service_contracts_repo.update_service_contract_location(location_id, data)

    def delete_service_contract_location(self, location_id):
        self.service_contracts_repo.delete_service_contract_location(location_id)

    def list_service_contract_tariffs(self, service_contract_id=None, service_contract_ids=None):
        return self.service_contracts_repo.list_service_contract_tariffs(service_contract_id, service_contract_ids)

    def get_service_contract_tariff(self, tariff_id):
        return self.service_contracts_repo.get_service_contract_tariff(tariff_id)

    def create_service_contract_tariff(self, data):
        return self.service_contracts_repo.create_service_contract_tariff(data)

    def update_service_contract_tariff(self, tariff_id, data):
        return self.service_contracts_repo.update_service_contract_tariff(tariff_id, data)

    def delete_service_contract_tariff(self, tariff_id):
        self.service_contracts_repo.delete_service_contract_tariff(tariff_id)

    def list_service_contract_invoices(self, service_contract_id=None, invoice_id=None):
        return self.service_contracts_repo.list_service_contract_invoices(service_contract_id, invoice_id)

    def get_service_contract_invoice(self, link_id):
        return self.service_contracts_repo.get_service_contract_invoice(link_id)

    def create_service_contract_invoice(self, data, invoice=None):
        return self.service_contracts_repo.create_service_contract_invoice(data, invoice)

    def update_service_contract_invoice(self, link_id, data):
        return self.service_contracts_repo.update_service_contract_invoice(link_id, data)

    def delete_service_contract_invoice(self, link_id):
        self.service_contracts_repo.delete_service_contract_invoice(link_id)

    def list_service_contract_payments(self, service_contract_id=None, booking_id=None):
        return self.service_contracts_repo.list_service_contract_payments(service_contract_id, booking_id)

    def get_service_contract_payment(self, payment_id):
        return self.service_contracts_repo.get_service_contract_payment(payment_id)

    def create_service_contract_payment(self, data):
        return self.service_contracts_repo.create_service_contract_payment(data)

    def delete_service_contract_payment(self, payment_id):
        self.service_contracts_repo.delete_service_contract_payment(payment_id)

    def list_service_contract_documents(self, service_contract_id=None, document_id=None):
        return self.service_contracts_repo.list_service_contract_documents(service_contract_id, document_id)

    def get_service_contract_document(self, link_id):
        return self.service_contracts_repo.get_service_contract_document(link_id)

    def create_service_contract_document(self, data):
        return self.service_contracts_repo.create_service_contract_document(data)

    def delete_service_contract_document(self, link_id):
        self.service_contracts_repo.delete_service_contract_document(link_id)

    def create_cost_items_together(self, items):
        return self.service_contracts_repo.create_cost_items_together(items)
