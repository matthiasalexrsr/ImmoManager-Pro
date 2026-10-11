"""Property service and energy contracts (Objektverträge): master data, locations, tariffs,
deadlines, expectation vs bills vs payments, transfer of recoverable costs, documents.

All endpoints are synchronous (worker threads); the portfolio boundary applies to every
record (services/portfolio_scope.py): a contract is visible through any visible
location and changeable only with every location visible.
"""

from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models_service_contracts import (
    CancellationRequest,
    CostTransferRequest,
    DocumentLinkRequest,
    InvoiceLinkRequest,
    LocationInput,
    PaymentLinkRequest,
    ServiceContractCreate,
    ServiceContractCreateRequest,
    ServiceContractDocument,
    ServiceContractLocation,
    ServiceContractPayment,
    ServiceContractTariff,
    TariffInput,
)
from ..services import service_contracts as service
from ..services.service_contracts import location_view
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/service-contracts", tags=["Objektverträge"])

T = TypeVar("T")


def _call(action: Callable[[], T]) -> T:
    try:
        return action()
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc).strip("'\"")) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _as_of(value: date | None) -> date:
    return value if isinstance(value, date) else service.today()


def _year_window(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    year = service.today().year
    start = date_from if isinstance(date_from, date) else date(year, 1, 1)
    end = date_to if isinstance(date_to, date) else date(start.year, 12, 31)
    return start, end


# --- contracts -----------------------------------------------------------------------------------

@router.get("")
def list_service_contracts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    property_id: str | None = Query(None),
    unit_id: str | None = Query(None),
    meter_id: str | None = Query(None),
    contract_type: str | None = Query(None),
    provider_contact_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    q: str | None = Query(None, max_length=200),
    as_of: date | None = Query(None),
) -> list[dict]:
    rows = service.list_view(store, as_of=_as_of(as_of), property_id=property_id, unit_id=unit_id, meter_id=meter_id,
                             contract_type=contract_type, provider_contact_id=provider_contact_id,
                             status=status_filter, q=q)
    return rows[skip: skip + limit]


@router.get("/deadlines")
def list_deadlines(days: int = Query(90, ge=1, le=730), as_of: date | None = Query(None)) -> list[dict]:
    """Notice deadlines, price guarantee ends and contract ends of the visible contracts."""
    return service.deadline_overview(store, _as_of(as_of), days)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_service_contract(payload: ServiceContractCreateRequest) -> dict:
    contract = _call(lambda: service.create_contract(store, payload))
    return service.detail_view(store, contract.id, service.today())


@router.get("/{contract_id}")
def get_service_contract(contract_id: str, as_of: date | None = Query(None)) -> dict:
    return _call(lambda: service.detail_view(store, contract_id, _as_of(as_of)))


@router.put("/{contract_id}")
def update_service_contract(contract_id: str, payload: ServiceContractCreate) -> dict:
    _call(lambda: service.update_contract(store, contract_id, payload))
    return service.detail_view(store, contract_id, service.today())


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service_contract(contract_id: str) -> None:
    _call(lambda: service.delete_contract(store, contract_id))


@router.post("/{contract_id}/cancel")
def cancel_service_contract(contract_id: str, payload: CancellationRequest,
                            extraordinary: bool = Query(False)) -> dict:
    """Record a cancellation; without a date it takes effect at the earliest end the notice reaches."""
    _call(lambda: service.cancel_contract(store, contract_id, payload, extraordinary=extraordinary is True))
    return service.detail_view(store, contract_id, service.today())


@router.delete("/{contract_id}/cancel")
def withdraw_cancellation(contract_id: str) -> dict:
    _call(lambda: service.withdraw_cancellation(store, contract_id))
    return service.detail_view(store, contract_id, service.today())


@router.get("/{contract_id}/terms")
def get_terms(contract_id: str, as_of: date | None = Query(None)) -> dict:
    def build() -> dict:
        contract = store.get_service_contract(contract_id)
        return service.terms_view(contract, store.list_service_contract_tariffs(contract_id), _as_of(as_of))
    return _call(build)


# --- locations -----------------------------------------------------------------------------------

@router.get("/{contract_id}/locations")
def list_locations(contract_id: str) -> list[dict]:
    def build() -> list[dict]:
        store.get_service_contract(contract_id)
        labels = service.Labels(store)
        return [location_view(row, labels) for row in store.list_service_contract_locations(contract_id)]
    return _call(build)


@router.post("/{contract_id}/locations", response_model=ServiceContractLocation,
             status_code=status.HTTP_201_CREATED)
def add_location(contract_id: str, payload: LocationInput) -> Any:
    return _call(lambda: service.add_location(store, contract_id, payload))


@router.put("/{contract_id}/locations/{location_id}", response_model=ServiceContractLocation)
def update_location(contract_id: str, location_id: str, payload: LocationInput) -> Any:
    return _call(lambda: service.update_location(store, contract_id, location_id, payload))


@router.delete("/{contract_id}/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_location(contract_id: str, location_id: str) -> None:
    _call(lambda: service.remove_location(store, contract_id, location_id))


# --- tariffs -------------------------------------------------------------------------------------

@router.get("/{contract_id}/tariffs")
def list_tariffs(contract_id: str) -> list[dict]:
    def build() -> list[dict]:
        store.get_service_contract(contract_id)
        return [service.tariff_view(t) for t in store.list_service_contract_tariffs(contract_id)]
    return _call(build)


@router.get("/{contract_id}/tariffs/at")
def tariff_at(contract_id: str, day: date = Query(..., alias="date")) -> dict:
    """The tariff in force on a day (404 before the first one)."""
    def build() -> dict:
        store.get_service_contract(contract_id)
        found = service.tariff_at(store.list_service_contract_tariffs(contract_id), day)
        if found is None:
            raise NotFoundError("An diesem Tag gilt noch kein Tarif")
        return service.tariff_view(found)
    return _call(build)


@router.post("/{contract_id}/tariffs", response_model=ServiceContractTariff, status_code=status.HTTP_201_CREATED)
def add_tariff(contract_id: str, payload: TariffInput) -> Any:
    return _call(lambda: service.add_tariff(store, contract_id, payload))


@router.put("/{contract_id}/tariffs/{tariff_id}", response_model=ServiceContractTariff)
def update_tariff(contract_id: str, tariff_id: str, payload: TariffInput) -> Any:
    return _call(lambda: service.update_tariff(store, contract_id, tariff_id, payload))


@router.delete("/{contract_id}/tariffs/{tariff_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_tariff(contract_id: str, tariff_id: str) -> None:
    _call(lambda: service.remove_tariff(store, contract_id, tariff_id))


# --- expectation, bills, payments ----------------------------------------------------------------

@router.get("/{contract_id}/instalments")
def list_instalments(contract_id: str, date_from: date | None = Query(None),
                     date_to: date | None = Query(None)) -> dict:
    """Instalments (Abschläge, Raten) the tariffs plan in the window (default: this calendar year)."""
    start, end = _year_window(date_from, date_to)
    return _call(lambda: service.instalments_view(store, contract_id, start, end))


@router.get("/{contract_id}/invoices")
def list_bills(contract_id: str) -> list[dict]:
    return _call(lambda: service.bills_view(store, contract_id))


@router.post("/{contract_id}/invoices", status_code=status.HTTP_201_CREATED)
def add_bill(contract_id: str, payload: InvoiceLinkRequest) -> dict:
    link = _call(lambda: service.add_bill(store, contract_id, payload))
    return next(row for row in service.bills_view(store, contract_id) if row["id"] == link.id)


@router.put("/{contract_id}/invoices/{link_id}")
def update_bill(contract_id: str, link_id: str, payload: InvoiceLinkRequest) -> dict:
    _call(lambda: service.update_bill(store, contract_id, link_id, payload))
    return next(row for row in service.bills_view(store, contract_id) if row["id"] == link_id)


@router.delete("/{contract_id}/invoices/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_bill(contract_id: str, link_id: str) -> None:
    _call(lambda: service.remove_bill(store, contract_id, link_id))


@router.get("/{contract_id}/payments")
def list_payments(contract_id: str) -> list[dict]:
    return _call(lambda: service.payments_view(store, contract_id))


@router.get("/{contract_id}/payment-candidates")
def payment_candidates(contract_id: str, date_from: date | None = Query(None), date_to: date | None = Query(None),
                       skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)) -> dict:
    """Bookings that may pay this contract, best matches first (window default: the last 120 days)."""
    from datetime import timedelta

    end = date_to if isinstance(date_to, date) else service.today()
    start = date_from if isinstance(date_from, date) else end - timedelta(days=120)
    return _call(lambda: service.payment_candidates(store, contract_id, start, end, skip, limit))


@router.post("/{contract_id}/payments", response_model=ServiceContractPayment, status_code=status.HTTP_201_CREATED)
def add_payment(contract_id: str, payload: PaymentLinkRequest) -> Any:
    return _call(lambda: service.add_payment(store, contract_id, payload))


@router.delete("/{contract_id}/payments/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_payment(contract_id: str, payment_id: str) -> None:
    _call(lambda: service.remove_payment(store, contract_id, payment_id))


@router.get("/{contract_id}/reconciliation")
def reconciliation(contract_id: str, date_from: date | None = Query(None),
                   date_to: date | None = Query(None)) -> dict:
    """Expectation vs bills vs payments of a window (default: this calendar year), each counted once."""
    start, end = _year_window(date_from, date_to)
    return _call(lambda: service.reconciliation_view(store, contract_id, start, end))


# --- utility billing -----------------------------------------------------------------------------

@router.get("/{contract_id}/cost-transfers")
def list_cost_transfers(contract_id: str) -> list[dict]:
    def build() -> list[dict]:
        store.get_service_contract(contract_id)
        return service.transfers_view(store, contract_id)
    return _call(build)


@router.post("/{contract_id}/cost-transfers", status_code=status.HTTP_201_CREATED)
def transfer_costs(contract_id: str, payload: CostTransferRequest) -> dict:
    """Recoverable bills enter a billing period of a location's property as cost items, once each."""
    return _call(lambda: service.transfer_costs(store, contract_id, payload))


# --- documents -----------------------------------------------------------------------------------

@router.get("/{contract_id}/documents")
def list_documents(contract_id: str) -> list[dict]:
    return _call(lambda: service.documents_view(store, contract_id))


@router.post("/{contract_id}/documents", response_model=ServiceContractDocument,
             status_code=status.HTTP_201_CREATED)
def add_document(contract_id: str, payload: DocumentLinkRequest) -> Any:
    return _call(lambda: service.add_document(store, contract_id, payload.document_id))


@router.delete("/{contract_id}/documents/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_document(contract_id: str, link_id: str) -> None:
    _call(lambda: service.remove_document(store, contract_id, link_id))
