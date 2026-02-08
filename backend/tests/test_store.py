import datetime

import pytest

from backend.models import (
    AccountCreate,
    BookingCreate,
    CategoryCreate,
    ContractCreate,
    MaintenanceCaseCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)
from backend.storage import InMemoryStore, NotFoundError, ValidationError


def test_create_property_requires_portfolio() -> None:
    store = InMemoryStore()

    with pytest.raises(ValidationError):
        store.create_property(
            PropertyCreate(
                portfolio_id="missing",
                name="Objekt A",
                property_type="Mehrfamilienhaus",
            )
        )


def test_create_unit_requires_property() -> None:
    store = InMemoryStore()
    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))

    with pytest.raises(ValidationError):
        store.create_unit(
            UnitCreate(
                property_id=portfolio.id,
                label="1.OG",
                unit_type="Wohnung",
            )
        )


def test_create_contract_validates_relationships() -> None:
    store = InMemoryStore()
    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))
    property_item = store.create_property(
        PropertyCreate(
            portfolio_id=portfolio.id,
            name="Objekt",
            property_type="Wohnung",
        )
    )
    unit = store.create_unit(
        UnitCreate(
            property_id=property_item.id,
            label="3.2",
            unit_type="Wohnung",
        )
    )
    tenant = store.create_tenant(TenantCreate(full_name="Max Mustermann"))

    contract = store.create_contract(
        ContractCreate(
            contract_number="C-100",
            property_id=property_item.id,
            unit_id=unit.id,
            tenant_id=tenant.id,
            start_date=datetime.date(2024, 1, 1),
        )
    )

    assert contract.contract_number == "C-100"

    with pytest.raises(ValidationError):
        store.create_contract(
            ContractCreate(
                contract_number="C-100",
                property_id=property_item.id,
                unit_id=unit.id,
                tenant_id=tenant.id,
                start_date=datetime.date(2024, 2, 1),
            )
        )


def test_account_and_booking_flow() -> None:
    store = InMemoryStore()
    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))
    account = store.create_account(
        AccountCreate(
            portfolio_id=portfolio.id,
            name="Hauptkonto",
            account_type="Bankkonto",
        )
    )
    category = store.create_category(
        CategoryCreate(
            portfolio_id=portfolio.id,
            name="Mieteinnahmen",
            category_type="income",
        )
    )

    booking = store.create_booking(
        BookingCreate(
            account_id=account.id,
            category_id=category.id,
            booking_date=datetime.date(2024, 4, 1),
            amount=1200.0,
        )
    )

    assert booking.amount == 1200.0


def test_maintenance_requires_property() -> None:
    store = InMemoryStore()

    with pytest.raises(ValidationError):
        store.create_maintenance_case(
            MaintenanceCaseCreate(
                property_id="missing",
                title="Heizung prüfen",
            )
        )

    with pytest.raises(NotFoundError):
        store.get_maintenance_case("missing")


def test_delete_property_cascades_units_and_contracts() -> None:
    store = InMemoryStore()
    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))
    property_item = store.create_property(
        PropertyCreate(
            portfolio_id=portfolio.id,
            name="Objekt",
            property_type="Wohnung",
        )
    )
    unit = store.create_unit(
        UnitCreate(
            property_id=property_item.id,
            label="2.1",
            unit_type="Wohnung",
        )
    )
    tenant = store.create_tenant(TenantCreate(full_name="Lisa Beispiel"))
    contract = store.create_contract(
        ContractCreate(
            contract_number="C-200",
            property_id=property_item.id,
            unit_id=unit.id,
            tenant_id=tenant.id,
            start_date=datetime.date(2024, 5, 1),
        )
    )

    store.delete_property(property_item.id)

    with pytest.raises(NotFoundError):
        store.get_property(property_item.id)
    with pytest.raises(NotFoundError):
        store.get_unit(unit.id)
    with pytest.raises(NotFoundError):
        store.get_contract(contract.id)
