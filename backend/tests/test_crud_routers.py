"""Comprehensive CRUD router tests for all entity endpoints.

Tests call router functions directly (no HTTP client) following existing conventions.
Each test group covers: list, create, get, update, delete, and 404 error paths.

Note: Query() defaults are not resolved when calling functions directly, so
skip/limit and filter params must always be passed explicitly.
"""

import datetime

import pytest
from fastapi import HTTPException

from backend.dependencies import store
from backend.models import (
    AccountCreate,
    BookingCreate,
    CalendarEventCreate,
    CategoryCreate,
    ContractCreate,
    DocumentCreate,
    InvoiceCreate,
    ListingCreate,
    ListingPhotoCreate,
    MaintenanceCaseCreate,
    PortfolioCreate,
    PropertyCreate,
    ReceivableCreate,
    TaskCreate,
    TenantCreate,
    UnitCreate,
)
from backend.routers import (
    accounts,
    bookings,
    calendar,
    categories,
    contracts,
    documents,
    invoices,
    listings,
    maintenance,
    portfolios,
    properties,
    receivables,
    tasks,
    tenants,
    units,
)

# Default pagination values (Query defaults aren't resolved outside FastAPI).
# We define wrapper helpers for each list function so that tests stay concise.
S, L = 0, 100


def _list_portfolios(**kw):
    return portfolios.list_portfolios(skip=kw.get("skip", S), limit=kw.get("limit", L), status_filter=kw.get("status_filter"))


def _list_properties(**kw):
    return properties.list_properties(skip=kw.get("skip", S), limit=kw.get("limit", L), portfolio_id=kw.get("portfolio_id"), status_filter=kw.get("status_filter"))


def _list_units(**kw):
    return units.list_units(skip=kw.get("skip", S), limit=kw.get("limit", L), property_id=kw.get("property_id"), status_filter=kw.get("status_filter"))


def _list_tenants(**kw):
    return tenants.list_tenants(skip=kw.get("skip", S), limit=kw.get("limit", L))


def _list_contracts(**kw):
    return contracts.list_contracts(skip=kw.get("skip", S), limit=kw.get("limit", L), property_id=kw.get("property_id"), tenant_id=kw.get("tenant_id"), status_filter=kw.get("status_filter"))


def _list_accounts(**kw):
    return accounts.list_accounts(skip=kw.get("skip", S), limit=kw.get("limit", L), portfolio_id=kw.get("portfolio_id"), account_type=kw.get("account_type"))


def _list_bookings(**kw):
    return bookings.list_bookings(skip=kw.get("skip", S), limit=kw.get("limit", L), account_id=kw.get("account_id"), tenant_id=kw.get("tenant_id"), status_filter=kw.get("status_filter"))


def _list_categories(**kw):
    return categories.list_categories(skip=kw.get("skip", S), limit=kw.get("limit", L), portfolio_id=kw.get("portfolio_id"), category_type=kw.get("category_type"))


def _list_receivables(**kw):
    return receivables.list_receivables(skip=kw.get("skip", S), limit=kw.get("limit", L), contract_id=kw.get("contract_id"), status_filter=kw.get("status_filter"))


def _list_invoices(**kw):
    return invoices.list_invoices(skip=kw.get("skip", S), limit=kw.get("limit", L), supplier=kw.get("supplier"), status_filter=kw.get("status_filter"))


def _list_maintenance(**kw):
    return maintenance.list_maintenance_cases(skip=kw.get("skip", S), limit=kw.get("limit", L), property_id=kw.get("property_id"), status_filter=kw.get("status_filter"))


def _list_documents(**kw):
    return documents.list_documents(skip=kw.get("skip", S), limit=kw.get("limit", L), property_id=kw.get("property_id"), contract_id=kw.get("contract_id"))


def _list_tasks(**kw):
    return tasks.list_tasks(skip=kw.get("skip", S), limit=kw.get("limit", L), status_filter=kw.get("status_filter"), assignee=kw.get("assignee"))


def _list_calendar(**kw):
    return calendar.list_calendar_events(skip=kw.get("skip", S), limit=kw.get("limit", L), property_id=kw.get("property_id"), event_type=kw.get("event_type"))


def _list_listings(**kw):
    return listings.list_listings(skip=kw.get("skip", S), limit=kw.get("limit", L), unit_id=kw.get("unit_id"), status_filter=kw.get("status_filter"))


def _list_listing_photos(**kw):
    return listings.list_listing_photos(skip=kw.get("skip", S), limit=kw.get("limit", L), listing_id=kw.get("listing_id"))


def _clear_store() -> None:
    for collection in (
        store.portfolios,
        store.properties,
        store.units,
        store.tenants,
        store.contracts,
        store.accounts,
        store.bookings,
        store.receivables,
        store.invoices,
        store.maintenance_cases,
        store.categories,
        store.documents,
        store.tasks,
        store.calendar_events,
        store.listings,
        store.listing_photos,
    ):
        collection.clear()


# ---------------------------------------------------------------------------
# Portfolios
# ---------------------------------------------------------------------------

class TestPortfolios:
    def setup_method(self) -> None:
        _clear_store()

    def test_create_portfolio(self) -> None:
        p = portfolios.create_portfolio(PortfolioCreate(name="Test"))
        assert p.name == "Test"
        assert p.id
        assert p.created_at is not None

    def test_list_portfolios_empty(self) -> None:
        assert _list_portfolios() == []

    def test_list_portfolios_returns_created(self) -> None:
        portfolios.create_portfolio(PortfolioCreate(name="A"))
        portfolios.create_portfolio(PortfolioCreate(name="B"))
        assert len(_list_portfolios()) == 2

    def test_list_portfolios_pagination(self) -> None:
        for i in range(5):
            portfolios.create_portfolio(PortfolioCreate(name=f"P{i}"))
        assert len(_list_portfolios(skip=0, limit=2)) == 2
        assert len(_list_portfolios(skip=3, limit=10)) == 2
        assert len(_list_portfolios(skip=10, limit=10)) == 0

    def test_list_portfolios_status_filter(self) -> None:
        portfolios.create_portfolio(PortfolioCreate(name="A", status="active"))
        portfolios.create_portfolio(PortfolioCreate(name="B", status="archived"))
        assert len(_list_portfolios(status_filter="active")) == 1

    def test_get_portfolio(self) -> None:
        p = portfolios.create_portfolio(PortfolioCreate(name="Test"))
        fetched = portfolios.get_portfolio(p.id)
        assert fetched.id == p.id
        assert fetched.name == "Test"

    def test_get_portfolio_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            portfolios.get_portfolio("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_portfolio(self) -> None:
        p = portfolios.create_portfolio(PortfolioCreate(name="Old"))
        updated = portfolios.update_portfolio(p.id, PortfolioCreate(name="New"))
        assert updated.name == "New"
        assert updated.id == p.id

    def test_update_portfolio_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            portfolios.update_portfolio("nonexistent", PortfolioCreate(name="X"))
        assert exc_info.value.status_code == 404

    def test_delete_portfolio(self) -> None:
        p = portfolios.create_portfolio(PortfolioCreate(name="Del"))
        portfolios.delete_portfolio(p.id)
        assert _list_portfolios() == []

    def test_delete_portfolio_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            portfolios.delete_portfolio("nonexistent")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class TestProperties:
    def setup_method(self) -> None:
        _clear_store()
        self.portfolio = store.create_portfolio(PortfolioCreate(name="P"))

    def test_create_property(self) -> None:
        p = properties.create_property(
            PropertyCreate(portfolio_id=self.portfolio.id, name="Haus", property_type="MFH")
        )
        assert p.name == "Haus"
        assert p.portfolio_id == self.portfolio.id

    def test_list_properties_empty(self) -> None:
        assert _list_properties() == []

    def test_list_properties_with_portfolio_filter(self) -> None:
        properties.create_property(
            PropertyCreate(portfolio_id=self.portfolio.id, name="A", property_type="MFH")
        )
        p2 = store.create_portfolio(PortfolioCreate(name="P2"))
        properties.create_property(
            PropertyCreate(portfolio_id=p2.id, name="B", property_type="EFH")
        )
        filtered = _list_properties(portfolio_id=self.portfolio.id)
        assert len(filtered) == 1
        assert filtered[0].name == "A"

    def test_list_properties_pagination(self) -> None:
        for i in range(3):
            properties.create_property(
                PropertyCreate(portfolio_id=self.portfolio.id, name=f"H{i}", property_type="MFH")
            )
        assert len(_list_properties(skip=1, limit=1)) == 1

    def test_get_property(self) -> None:
        p = properties.create_property(
            PropertyCreate(portfolio_id=self.portfolio.id, name="Haus", property_type="MFH")
        )
        fetched = properties.get_property(p.id)
        assert fetched.id == p.id

    def test_get_property_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            properties.get_property("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_property(self) -> None:
        p = properties.create_property(
            PropertyCreate(portfolio_id=self.portfolio.id, name="Old", property_type="MFH")
        )
        updated = properties.update_property(
            p.id, PropertyCreate(portfolio_id=self.portfolio.id, name="New", property_type="EFH")
        )
        assert updated.name == "New"
        assert updated.property_type == "EFH"

    def test_update_property_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            properties.update_property(
                "nonexistent",
                PropertyCreate(portfolio_id=self.portfolio.id, name="X", property_type="MFH"),
            )
        assert exc_info.value.status_code == 404

    def test_delete_property(self) -> None:
        p = properties.create_property(
            PropertyCreate(portfolio_id=self.portfolio.id, name="Del", property_type="MFH")
        )
        properties.delete_property(p.id)
        assert _list_properties() == []

    def test_delete_property_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            properties.delete_property("nonexistent")
        assert exc_info.value.status_code == 404

    def test_create_property_invalid_portfolio(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            properties.create_property(
                PropertyCreate(portfolio_id="bad", name="X", property_type="MFH")
            )
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

class TestUnits:
    def setup_method(self) -> None:
        _clear_store()
        self.portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        self.prop = store.create_property(
            PropertyCreate(portfolio_id=self.portfolio.id, name="Haus", property_type="MFH")
        )

    def test_create_unit(self) -> None:
        u = units.create_unit(
            UnitCreate(property_id=self.prop.id, label="EG", unit_type="Wohnung")
        )
        assert u.label == "EG"
        assert u.property_id == self.prop.id

    def test_list_units_with_filter(self) -> None:
        units.create_unit(
            UnitCreate(property_id=self.prop.id, label="1", unit_type="Wohnung", status="rented")
        )
        units.create_unit(
            UnitCreate(property_id=self.prop.id, label="2", unit_type="Wohnung", status="vacant")
        )
        assert len(_list_units(status_filter="rented")) == 1
        assert len(_list_units(property_id=self.prop.id)) == 2

    def test_list_units_pagination(self) -> None:
        for i in range(4):
            units.create_unit(
                UnitCreate(property_id=self.prop.id, label=f"U{i}", unit_type="Wohnung")
            )
        assert len(_list_units(skip=2, limit=2)) == 2

    def test_get_unit(self) -> None:
        u = units.create_unit(
            UnitCreate(property_id=self.prop.id, label="EG", unit_type="Wohnung")
        )
        assert units.get_unit(u.id).id == u.id

    def test_get_unit_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            units.get_unit("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_unit(self) -> None:
        u = units.create_unit(
            UnitCreate(property_id=self.prop.id, label="EG", unit_type="Wohnung")
        )
        updated = units.update_unit(
            u.id, UnitCreate(property_id=self.prop.id, label="OG", unit_type="Büro")
        )
        assert updated.label == "OG"

    def test_update_unit_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            units.update_unit(
                "nonexistent",
                UnitCreate(property_id=self.prop.id, label="X", unit_type="Wohnung"),
            )
        assert exc_info.value.status_code == 404

    def test_delete_unit(self) -> None:
        u = units.create_unit(
            UnitCreate(property_id=self.prop.id, label="EG", unit_type="Wohnung")
        )
        units.delete_unit(u.id)
        assert _list_units() == []

    def test_delete_unit_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            units.delete_unit("nonexistent")
        assert exc_info.value.status_code == 404

    def test_create_unit_invalid_property(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            units.create_unit(UnitCreate(property_id="bad", label="X", unit_type="W"))
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------

class TestTenants:
    def setup_method(self) -> None:
        _clear_store()

    def test_create_tenant(self) -> None:
        t = tenants.create_tenant(TenantCreate(full_name="Max Muster"))
        assert t.full_name == "Max Muster"
        assert t.id

    def test_list_tenants_empty(self) -> None:
        assert _list_tenants() == []

    def test_list_tenants_pagination(self) -> None:
        for i in range(3):
            tenants.create_tenant(TenantCreate(full_name=f"T{i}"))
        assert len(_list_tenants(skip=1, limit=1)) == 1

    def test_get_tenant(self) -> None:
        t = tenants.create_tenant(TenantCreate(full_name="Max"))
        assert tenants.get_tenant(t.id).full_name == "Max"

    def test_get_tenant_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            tenants.get_tenant("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_tenant(self) -> None:
        t = tenants.create_tenant(TenantCreate(full_name="Old"))
        updated = tenants.update_tenant(t.id, TenantCreate(full_name="New"))
        assert updated.full_name == "New"

    def test_update_tenant_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            tenants.update_tenant("nonexistent", TenantCreate(full_name="X"))
        assert exc_info.value.status_code == 404

    def test_delete_tenant(self) -> None:
        t = tenants.create_tenant(TenantCreate(full_name="Del"))
        tenants.delete_tenant(t.id)
        assert _list_tenants() == []

    def test_delete_tenant_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            tenants.delete_tenant("nonexistent")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Contracts (CRUD only, domain endpoints tested in test_domain_endpoints.py)
# ---------------------------------------------------------------------------

class TestContracts:
    def setup_method(self) -> None:
        _clear_store()
        self.portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        self.prop = store.create_property(
            PropertyCreate(portfolio_id=self.portfolio.id, name="H", property_type="MFH")
        )
        self.unit = store.create_unit(
            UnitCreate(property_id=self.prop.id, label="1", unit_type="Wohnung")
        )
        self.tenant = store.create_tenant(TenantCreate(full_name="Mieter"))

    def _make_payload(self, number: str = "C-1") -> ContractCreate:
        return ContractCreate(
            contract_number=number,
            property_id=self.prop.id,
            unit_id=self.unit.id,
            tenant_id=self.tenant.id,
            start_date=datetime.date(2025, 1, 1),
        )

    def test_create_contract(self) -> None:
        c = contracts.create_contract(self._make_payload())
        assert c.contract_number == "C-1"

    def test_list_contracts_empty(self) -> None:
        assert _list_contracts() == []

    def test_list_contracts_with_filter(self) -> None:
        contracts.create_contract(self._make_payload("C-1"))
        t2 = store.create_tenant(TenantCreate(full_name="Andere"))
        contracts.create_contract(
            ContractCreate(
                contract_number="C-2",
                property_id=self.prop.id,
                unit_id=self.unit.id,
                tenant_id=t2.id,
                start_date=datetime.date(2025, 2, 1),
            )
        )
        assert len(_list_contracts(tenant_id=self.tenant.id)) == 1
        assert len(_list_contracts(property_id=self.prop.id)) == 2

    def test_list_contracts_pagination(self) -> None:
        contracts.create_contract(self._make_payload("C-1"))
        contracts.create_contract(self._make_payload("C-2"))
        assert len(_list_contracts(skip=0, limit=1)) == 1

    def test_get_contract(self) -> None:
        c = contracts.create_contract(self._make_payload())
        assert contracts.get_contract(c.id).id == c.id

    def test_get_contract_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            contracts.get_contract("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_contract(self) -> None:
        c = contracts.create_contract(self._make_payload())
        updated = contracts.update_contract(c.id, self._make_payload("C-UPDATED"))
        assert updated.contract_number == "C-UPDATED"

    def test_update_contract_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            contracts.update_contract("nonexistent", self._make_payload())
        assert exc_info.value.status_code == 404

    def test_delete_contract(self) -> None:
        c = contracts.create_contract(self._make_payload())
        contracts.delete_contract(c.id)
        assert _list_contracts() == []

    def test_delete_contract_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            contracts.delete_contract("nonexistent")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class TestAccounts:
    def setup_method(self) -> None:
        _clear_store()
        self.portfolio = store.create_portfolio(PortfolioCreate(name="P"))

    def _make_payload(self, name: str = "Konto") -> AccountCreate:
        return AccountCreate(
            portfolio_id=self.portfolio.id, name=name, account_type="Bankkonto"
        )

    def test_create_account(self) -> None:
        a = accounts.create_account(self._make_payload())
        assert a.name == "Konto"

    def test_list_accounts_empty(self) -> None:
        assert _list_accounts() == []

    def test_list_accounts_with_filter(self) -> None:
        accounts.create_account(self._make_payload("A"))
        accounts.create_account(
            AccountCreate(
                portfolio_id=self.portfolio.id, name="B", account_type="Sparkonto"
            )
        )
        assert len(_list_accounts(account_type="Bankkonto")) == 1
        assert len(_list_accounts(portfolio_id=self.portfolio.id)) == 2

    def test_list_accounts_pagination(self) -> None:
        for i in range(3):
            accounts.create_account(self._make_payload(f"K{i}"))
        assert len(_list_accounts(skip=1, limit=1)) == 1

    def test_get_account(self) -> None:
        a = accounts.create_account(self._make_payload())
        assert accounts.get_account(a.id).id == a.id

    def test_get_account_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            accounts.get_account("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_account(self) -> None:
        a = accounts.create_account(self._make_payload())
        updated = accounts.update_account(a.id, self._make_payload("Updated"))
        assert updated.name == "Updated"

    def test_update_account_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            accounts.update_account("nonexistent", self._make_payload())
        assert exc_info.value.status_code == 404

    def test_delete_account(self) -> None:
        a = accounts.create_account(self._make_payload())
        accounts.delete_account(a.id)
        assert _list_accounts() == []

    def test_delete_account_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            accounts.delete_account("nonexistent")
        assert exc_info.value.status_code == 404

    def test_create_account_invalid_portfolio(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            accounts.create_account(
                AccountCreate(portfolio_id="bad", name="X", account_type="Bankkonto")
            )
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------

class TestBookings:
    def setup_method(self) -> None:
        _clear_store()
        self.portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        self.account = store.create_account(
            AccountCreate(
                portfolio_id=self.portfolio.id, name="Konto", account_type="Bankkonto"
            )
        )

    def _make_payload(self, amount: float = 100.0) -> BookingCreate:
        return BookingCreate(
            account_id=self.account.id,
            booking_date=datetime.date(2025, 1, 1),
            amount=amount,
        )

    def test_create_booking(self) -> None:
        b = bookings.create_booking(self._make_payload())
        assert b.amount == 100.0

    def test_list_bookings_empty(self) -> None:
        assert _list_bookings() == []

    def test_list_bookings_with_filter(self) -> None:
        bookings.create_booking(self._make_payload(100.0))
        bookings.create_booking(self._make_payload(-50.0))
        assert len(_list_bookings(account_id=self.account.id)) == 2

    def test_list_bookings_pagination(self) -> None:
        for _ in range(3):
            bookings.create_booking(self._make_payload())
        assert len(_list_bookings(skip=0, limit=2)) == 2

    def test_get_booking(self) -> None:
        b = bookings.create_booking(self._make_payload())
        assert bookings.get_booking(b.id).id == b.id

    def test_get_booking_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            bookings.get_booking("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_booking(self) -> None:
        b = bookings.create_booking(self._make_payload(100.0))
        updated = bookings.update_booking(b.id, self._make_payload(200.0))
        assert updated.amount == 200.0

    def test_update_booking_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            bookings.update_booking("nonexistent", self._make_payload())
        assert exc_info.value.status_code == 404

    def test_delete_booking(self) -> None:
        b = bookings.create_booking(self._make_payload())
        bookings.delete_booking(b.id)
        assert _list_bookings() == []

    def test_delete_booking_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            bookings.delete_booking("nonexistent")
        assert exc_info.value.status_code == 404

    def test_create_booking_invalid_account(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            bookings.create_booking(
                BookingCreate(
                    account_id="bad",
                    booking_date=datetime.date(2025, 1, 1),
                    amount=10.0,
                )
            )
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

class TestCategories:
    def setup_method(self) -> None:
        _clear_store()
        self.portfolio = store.create_portfolio(PortfolioCreate(name="P"))

    def _make_payload(self, name: str = "Miete") -> CategoryCreate:
        return CategoryCreate(
            portfolio_id=self.portfolio.id, name=name, category_type="income"
        )

    def test_create_category(self) -> None:
        c = categories.create_category(self._make_payload())
        assert c.name == "Miete"

    def test_list_categories_empty(self) -> None:
        assert _list_categories() == []

    def test_list_categories_with_filter(self) -> None:
        categories.create_category(self._make_payload("Miete"))
        categories.create_category(
            CategoryCreate(
                portfolio_id=self.portfolio.id, name="Reparatur", category_type="expense"
            )
        )
        assert len(_list_categories(category_type="income")) == 1
        assert len(_list_categories(portfolio_id=self.portfolio.id)) == 2

    def test_list_categories_pagination(self) -> None:
        for i in range(3):
            categories.create_category(self._make_payload(f"Cat{i}"))
        assert len(_list_categories(skip=1, limit=1)) == 1

    def test_get_category(self) -> None:
        c = categories.create_category(self._make_payload())
        assert categories.get_category(c.id).id == c.id

    def test_get_category_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            categories.get_category("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_category(self) -> None:
        c = categories.create_category(self._make_payload())
        updated = categories.update_category(c.id, self._make_payload("Nebenkosten"))
        assert updated.name == "Nebenkosten"

    def test_update_category_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            categories.update_category("nonexistent", self._make_payload())
        assert exc_info.value.status_code == 404

    def test_delete_category(self) -> None:
        c = categories.create_category(self._make_payload())
        categories.delete_category(c.id)
        assert _list_categories() == []

    def test_delete_category_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            categories.delete_category("nonexistent")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Receivables
# ---------------------------------------------------------------------------

class TestReceivables:
    def setup_method(self) -> None:
        _clear_store()
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        prop = store.create_property(
            PropertyCreate(portfolio_id=portfolio.id, name="H", property_type="MFH")
        )
        unit = store.create_unit(
            UnitCreate(property_id=prop.id, label="1", unit_type="Wohnung")
        )
        tenant = store.create_tenant(TenantCreate(full_name="M"))
        self.contract = store.create_contract(
            ContractCreate(
                contract_number="C-1",
                property_id=prop.id,
                unit_id=unit.id,
                tenant_id=tenant.id,
                start_date=datetime.date(2025, 1, 1),
            )
        )

    def _make_payload(self, amount: float = 500.0) -> ReceivableCreate:
        return ReceivableCreate(
            contract_id=self.contract.id,
            due_date=datetime.date(2025, 2, 1),
            amount_due=amount,
            status="open",
        )

    def test_create_receivable(self) -> None:
        r = receivables.create_receivable(self._make_payload())
        assert r.amount_due == 500.0

    def test_list_receivables_empty(self) -> None:
        assert _list_receivables() == []

    def test_list_receivables_with_filter(self) -> None:
        receivables.create_receivable(self._make_payload(100.0))
        receivables.create_receivable(
            ReceivableCreate(
                contract_id=self.contract.id,
                due_date=datetime.date(2025, 3, 1),
                amount_due=200.0,
                status="overdue",
            )
        )
        assert len(_list_receivables(status_filter="open")) == 1
        assert len(_list_receivables(contract_id=self.contract.id)) == 2

    def test_list_receivables_pagination(self) -> None:
        for _ in range(3):
            receivables.create_receivable(self._make_payload())
        assert len(_list_receivables(skip=1, limit=1)) == 1

    def test_get_receivable(self) -> None:
        r = receivables.create_receivable(self._make_payload())
        assert receivables.get_receivable(r.id).id == r.id

    def test_get_receivable_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            receivables.get_receivable("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_receivable(self) -> None:
        r = receivables.create_receivable(self._make_payload())
        updated = receivables.update_receivable(r.id, self._make_payload(750.0))
        assert updated.amount_due == 750.0

    def test_update_receivable_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            receivables.update_receivable("nonexistent", self._make_payload())
        assert exc_info.value.status_code == 404

    def test_delete_receivable(self) -> None:
        r = receivables.create_receivable(self._make_payload())
        receivables.delete_receivable(r.id)
        assert _list_receivables() == []

    def test_delete_receivable_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            receivables.delete_receivable("nonexistent")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Invoices (CRUD only, match endpoint tested in test_domain_endpoints.py)
# ---------------------------------------------------------------------------

class TestInvoices:
    def setup_method(self) -> None:
        _clear_store()

    def _make_payload(self, supplier: str = "Handwerker") -> InvoiceCreate:
        return InvoiceCreate(
            supplier=supplier,
            invoice_date=datetime.date(2025, 1, 15),
            net_amount=100.0,
            gross_amount=119.0,
        )

    def test_create_invoice(self) -> None:
        inv = invoices.create_invoice(self._make_payload())
        assert inv.supplier == "Handwerker"

    def test_list_invoices_empty(self) -> None:
        assert _list_invoices() == []

    def test_list_invoices_with_filter(self) -> None:
        invoices.create_invoice(self._make_payload("A"))
        invoices.create_invoice(self._make_payload("B"))
        assert len(_list_invoices(supplier="A")) == 1
        assert len(_list_invoices()) == 2

    def test_list_invoices_pagination(self) -> None:
        for i in range(3):
            invoices.create_invoice(self._make_payload(f"S{i}"))
        assert len(_list_invoices(skip=0, limit=2)) == 2

    def test_get_invoice(self) -> None:
        inv = invoices.create_invoice(self._make_payload())
        assert invoices.get_invoice(inv.id).id == inv.id

    def test_get_invoice_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            invoices.get_invoice("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_invoice(self) -> None:
        inv = invoices.create_invoice(self._make_payload())
        updated = invoices.update_invoice(inv.id, self._make_payload("Neuer Lieferant"))
        assert updated.supplier == "Neuer Lieferant"

    def test_update_invoice_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            invoices.update_invoice("nonexistent", self._make_payload())
        assert exc_info.value.status_code == 404

    def test_delete_invoice(self) -> None:
        inv = invoices.create_invoice(self._make_payload())
        invoices.delete_invoice(inv.id)
        assert _list_invoices() == []

    def test_delete_invoice_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            invoices.delete_invoice("nonexistent")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------

class TestMaintenance:
    def setup_method(self) -> None:
        _clear_store()
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        self.prop = store.create_property(
            PropertyCreate(portfolio_id=portfolio.id, name="H", property_type="MFH")
        )

    def _make_payload(self, title: str = "Reparatur") -> MaintenanceCaseCreate:
        return MaintenanceCaseCreate(
            property_id=self.prop.id, title=title, status="open"
        )

    def test_create_maintenance_case(self) -> None:
        m = maintenance.create_maintenance_case(self._make_payload())
        assert m.title == "Reparatur"

    def test_list_maintenance_cases_empty(self) -> None:
        assert _list_maintenance() == []

    def test_list_maintenance_cases_with_filter(self) -> None:
        maintenance.create_maintenance_case(self._make_payload("A"))
        maintenance.create_maintenance_case(
            MaintenanceCaseCreate(
                property_id=self.prop.id, title="B", status="done"
            )
        )
        assert len(_list_maintenance(status_filter="open")) == 1
        assert len(_list_maintenance(property_id=self.prop.id)) == 2

    def test_list_maintenance_cases_pagination(self) -> None:
        for i in range(3):
            maintenance.create_maintenance_case(self._make_payload(f"M{i}"))
        assert len(_list_maintenance(skip=1, limit=1)) == 1

    def test_get_maintenance_case(self) -> None:
        m = maintenance.create_maintenance_case(self._make_payload())
        assert maintenance.get_maintenance_case(m.id).id == m.id

    def test_get_maintenance_case_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            maintenance.get_maintenance_case("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_maintenance_case(self) -> None:
        m = maintenance.create_maintenance_case(self._make_payload())
        updated = maintenance.update_maintenance_case(
            m.id, self._make_payload("Elektrik")
        )
        assert updated.title == "Elektrik"

    def test_update_maintenance_case_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            maintenance.update_maintenance_case("nonexistent", self._make_payload())
        assert exc_info.value.status_code == 404

    def test_delete_maintenance_case(self) -> None:
        m = maintenance.create_maintenance_case(self._make_payload())
        maintenance.delete_maintenance_case(m.id)
        assert _list_maintenance() == []

    def test_delete_maintenance_case_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            maintenance.delete_maintenance_case("nonexistent")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class TestDocuments:
    def setup_method(self) -> None:
        _clear_store()

    def _make_payload(self, title: str = "Vertrag") -> DocumentCreate:
        return DocumentCreate(title=title, file_url="https://example.com/doc.pdf")

    def test_create_document(self) -> None:
        d = documents.create_document(self._make_payload())
        assert d.title == "Vertrag"

    def test_list_documents_empty(self) -> None:
        assert _list_documents() == []

    def test_list_documents_with_filter(self) -> None:
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        prop = store.create_property(
            PropertyCreate(portfolio_id=portfolio.id, name="H", property_type="MFH")
        )
        documents.create_document(
            DocumentCreate(title="A", file_url="u", property_id=prop.id)
        )
        documents.create_document(DocumentCreate(title="B", file_url="u"))
        assert len(_list_documents(property_id=prop.id)) == 1

    def test_list_documents_pagination(self) -> None:
        for i in range(3):
            documents.create_document(self._make_payload(f"D{i}"))
        assert len(_list_documents(skip=1, limit=1)) == 1

    def test_get_document(self) -> None:
        d = documents.create_document(self._make_payload())
        assert documents.get_document(d.id).id == d.id

    def test_get_document_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            documents.get_document("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_document(self) -> None:
        d = documents.create_document(self._make_payload())
        updated = documents.update_document(d.id, self._make_payload("Rechnung"))
        assert updated.title == "Rechnung"

    def test_update_document_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            documents.update_document("nonexistent", self._make_payload())
        assert exc_info.value.status_code == 404

    def test_delete_document(self) -> None:
        d = documents.create_document(self._make_payload())
        documents.delete_document(d.id)
        assert _list_documents() == []

    def test_delete_document_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            documents.delete_document("nonexistent")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

class TestTasks:
    def setup_method(self) -> None:
        _clear_store()

    def _make_payload(self, title: str = "Aufgabe") -> TaskCreate:
        return TaskCreate(title=title)

    def test_create_task(self) -> None:
        t = tasks.create_task(self._make_payload())
        assert t.title == "Aufgabe"

    def test_list_tasks_empty(self) -> None:
        assert _list_tasks() == []

    def test_list_tasks_with_filter(self) -> None:
        tasks.create_task(TaskCreate(title="A", status="open", assignee="Hans"))
        tasks.create_task(TaskCreate(title="B", status="done", assignee="Maria"))
        assert len(_list_tasks(status_filter="open")) == 1
        assert len(_list_tasks(assignee="Maria")) == 1

    def test_list_tasks_pagination(self) -> None:
        for i in range(3):
            tasks.create_task(self._make_payload(f"T{i}"))
        assert len(_list_tasks(skip=2, limit=5)) == 1

    def test_get_task(self) -> None:
        t = tasks.create_task(self._make_payload())
        assert tasks.get_task(t.id).id == t.id

    def test_get_task_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            tasks.get_task("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_task(self) -> None:
        t = tasks.create_task(self._make_payload())
        updated = tasks.update_task(t.id, self._make_payload("Aktualisiert"))
        assert updated.title == "Aktualisiert"

    def test_update_task_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            tasks.update_task("nonexistent", self._make_payload())
        assert exc_info.value.status_code == 404

    def test_delete_task(self) -> None:
        t = tasks.create_task(self._make_payload())
        tasks.delete_task(t.id)
        assert _list_tasks() == []

    def test_delete_task_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            tasks.delete_task("nonexistent")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Calendar Events
# ---------------------------------------------------------------------------

class TestCalendarEvents:
    def setup_method(self) -> None:
        _clear_store()

    def _make_payload(self, title: str = "Termin") -> CalendarEventCreate:
        return CalendarEventCreate(
            title=title,
            event_type="Besichtigung",
            event_date=datetime.date(2025, 3, 15),
        )

    def test_create_calendar_event(self) -> None:
        e = calendar.create_calendar_event(self._make_payload())
        assert e.title == "Termin"

    def test_list_calendar_events_empty(self) -> None:
        assert _list_calendar() == []

    def test_list_calendar_events_with_filter(self) -> None:
        calendar.create_calendar_event(self._make_payload("A"))
        calendar.create_calendar_event(
            CalendarEventCreate(
                title="B", event_type="Wartung", event_date=datetime.date(2025, 4, 1)
            )
        )
        assert len(_list_calendar(event_type="Besichtigung")) == 1

    def test_list_calendar_events_pagination(self) -> None:
        for i in range(3):
            calendar.create_calendar_event(self._make_payload(f"E{i}"))
        assert len(_list_calendar(skip=0, limit=2)) == 2

    def test_get_calendar_event(self) -> None:
        e = calendar.create_calendar_event(self._make_payload())
        assert calendar.get_calendar_event(e.id).id == e.id

    def test_get_calendar_event_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            calendar.get_calendar_event("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_calendar_event(self) -> None:
        e = calendar.create_calendar_event(self._make_payload())
        updated = calendar.update_calendar_event(e.id, self._make_payload("Neuer Termin"))
        assert updated.title == "Neuer Termin"

    def test_update_calendar_event_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            calendar.update_calendar_event("nonexistent", self._make_payload())
        assert exc_info.value.status_code == 404

    def test_delete_calendar_event(self) -> None:
        e = calendar.create_calendar_event(self._make_payload())
        calendar.delete_calendar_event(e.id)
        assert _list_calendar() == []

    def test_delete_calendar_event_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            calendar.delete_calendar_event("nonexistent")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------

class TestListings:
    def setup_method(self) -> None:
        _clear_store()
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        prop = store.create_property(
            PropertyCreate(portfolio_id=portfolio.id, name="H", property_type="MFH")
        )
        self.unit = store.create_unit(
            UnitCreate(property_id=prop.id, label="1", unit_type="Wohnung")
        )

    def _make_payload(self, title: str = "Inserat") -> ListingCreate:
        return ListingCreate(unit_id=self.unit.id, title=title)

    def test_create_listing(self) -> None:
        lst = listings.create_listing(self._make_payload())
        assert lst.title == "Inserat"

    def test_list_listings_empty(self) -> None:
        assert _list_listings() == []

    def test_list_listings_with_filter(self) -> None:
        listings.create_listing(self._make_payload("A"))
        listings.create_listing(
            ListingCreate(unit_id=self.unit.id, title="B", status="active")
        )
        assert len(_list_listings(unit_id=self.unit.id)) == 2
        assert len(_list_listings(status_filter="draft")) == 1

    def test_list_listings_pagination(self) -> None:
        for i in range(3):
            listings.create_listing(self._make_payload(f"L{i}"))
        assert len(_list_listings(skip=1, limit=1)) == 1

    def test_get_listing(self) -> None:
        lst = listings.create_listing(self._make_payload())
        assert listings.get_listing(lst.id).id == lst.id

    def test_get_listing_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            listings.get_listing("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_listing(self) -> None:
        lst = listings.create_listing(self._make_payload())
        updated = listings.update_listing(lst.id, self._make_payload("Aktualisiert"))
        assert updated.title == "Aktualisiert"

    def test_update_listing_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            listings.update_listing("nonexistent", self._make_payload())
        assert exc_info.value.status_code == 404

    def test_delete_listing(self) -> None:
        lst = listings.create_listing(self._make_payload())
        listings.delete_listing(lst.id)
        assert _list_listings() == []

    def test_delete_listing_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            listings.delete_listing("nonexistent")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Listing Photos
# ---------------------------------------------------------------------------

class TestListingPhotos:
    def setup_method(self) -> None:
        _clear_store()
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        prop = store.create_property(
            PropertyCreate(portfolio_id=portfolio.id, name="H", property_type="MFH")
        )
        unit = store.create_unit(
            UnitCreate(property_id=prop.id, label="1", unit_type="Wohnung")
        )
        self.listing = store.create_listing(
            ListingCreate(unit_id=unit.id, title="Inserat")
        )

    def _make_payload(self, url: str = "https://example.com/photo.jpg") -> ListingPhotoCreate:
        return ListingPhotoCreate(listing_id=self.listing.id, file_url=url)

    def test_create_listing_photo(self) -> None:
        p = listings.create_listing_photo(self._make_payload())
        assert p.file_url == "https://example.com/photo.jpg"

    def test_list_listing_photos_empty(self) -> None:
        assert _list_listing_photos() == []

    def test_list_listing_photos_with_filter(self) -> None:
        listings.create_listing_photo(self._make_payload("u1"))
        listings.create_listing_photo(self._make_payload("u2"))
        assert len(_list_listing_photos(listing_id=self.listing.id)) == 2

    def test_list_listing_photos_pagination(self) -> None:
        for i in range(3):
            listings.create_listing_photo(self._make_payload(f"u{i}"))
        assert len(_list_listing_photos(skip=0, limit=2)) == 2

    def test_get_listing_photo(self) -> None:
        p = listings.create_listing_photo(self._make_payload())
        assert listings.get_listing_photo(p.id).id == p.id

    def test_get_listing_photo_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            listings.get_listing_photo("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_listing_photo(self) -> None:
        p = listings.create_listing_photo(self._make_payload())
        updated = listings.update_listing_photo(
            p.id, self._make_payload("https://example.com/new.jpg")
        )
        assert updated.file_url == "https://example.com/new.jpg"

    def test_update_listing_photo_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            listings.update_listing_photo("nonexistent", self._make_payload())
        assert exc_info.value.status_code == 404

    def test_delete_listing_photo(self) -> None:
        p = listings.create_listing_photo(self._make_payload())
        listings.delete_listing_photo(p.id)
        assert _list_listing_photos() == []

    def test_delete_listing_photo_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            listings.delete_listing_photo("nonexistent")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Timestamp tests (created_at / updated_at)
# ---------------------------------------------------------------------------

class TestTimestamps:
    def setup_method(self) -> None:
        _clear_store()

    def test_portfolio_timestamps(self) -> None:
        p = portfolios.create_portfolio(PortfolioCreate(name="T"))
        assert p.created_at is not None
        assert p.updated_at is not None
        old_updated = p.updated_at
        updated = portfolios.update_portfolio(p.id, PortfolioCreate(name="T2"))
        assert updated.created_at == p.created_at
        assert updated.updated_at >= old_updated

    def test_tenant_timestamps(self) -> None:
        t = tenants.create_tenant(TenantCreate(full_name="A"))
        assert t.created_at is not None
        updated = tenants.update_tenant(t.id, TenantCreate(full_name="B"))
        assert updated.created_at == t.created_at

    def test_task_timestamps(self) -> None:
        t = tasks.create_task(TaskCreate(title="A"))
        assert t.created_at is not None
        updated = tasks.update_task(t.id, TaskCreate(title="B"))
        assert updated.created_at == t.created_at
