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
    AccountPatch,
    AllocationKeyCreate,
    AllocationKeyPatch,
    BillingPeriodCreate,
    BillingPeriodPatch,
    BookingCreate,
    BookingPatch,
    CalendarEventCreate,
    CalendarEventPatch,
    CategoryCreate,
    CategoryPatch,
    ContractCreate,
    ContractPatch,
    CostItemCreate,
    CostItemPatch,
    DepositCreate,
    DepositPatch,
    DocumentCreate,
    DocumentPatch,
    InvoiceCreate,
    InvoicePatch,
    LeadCreate,
    LeadPatch,
    ListingCreate,
    ListingPatch,
    ListingPhotoCreate,
    ListingPhotoPatch,
    MaintenanceCaseCreate,
    MaintenanceCasePatch,
    MeterCreate,
    NotificationCreate,
    NotificationPatch,
    NotificationTemplateCreate,
    NotificationTemplatePatch,
    PortfolioCreate,
    PortfolioPatch,
    PropertyCreate,
    PropertyPatch,
    ReceivableCreate,
    ReceivablePatch,
    StandaloneMeterReadingCreate,
    TaskCreate,
    TaskPatch,
    TenantCreate,
    TenantPatch,
    UnitCreate,
    UnitPatch,
    UtilityStatementPatch,
    ViewingAppointmentCreate,
    ViewingAppointmentPatch,
)
from backend.routers import (
    accounts,
    billing,
    bookings,
    calendar,
    categories,
    contracts,
    deposits,
    documents,
    invoices,
    leads,
    listings,
    maintenance,
    notifications,
    portfolios,
    properties,
    receivables,
    tasks,
    tenants,
    units,
    viewings,
)

# Default pagination values (Query defaults aren't resolved outside FastAPI).
# We define wrapper helpers for each list function so that tests stay concise.
S, L = 0, 100


def _list_portfolios(**kw):
    return portfolios.list_portfolios(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        status_filter=kw.get("status_filter"),
    )


def _list_properties(**kw):
    return properties.list_properties(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        portfolio_id=kw.get("portfolio_id"),
        status_filter=kw.get("status_filter"),
    )


def _list_units(**kw):
    return units.list_units(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        property_id=kw.get("property_id"),
        status_filter=kw.get("status_filter"),
    )


def _list_tenants(**kw):
    return tenants.list_tenants(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
    )


def _list_contracts(**kw):
    return contracts.list_contracts(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        property_id=kw.get("property_id"),
        tenant_id=kw.get("tenant_id"),
        status_filter=kw.get("status_filter"),
    )


def _list_accounts(**kw):
    return accounts.list_accounts(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        portfolio_id=kw.get("portfolio_id"),
        account_type=kw.get("account_type"),
    )


def _list_bookings(**kw):
    return bookings.list_bookings(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        account_id=kw.get("account_id"),
        tenant_id=kw.get("tenant_id"),
        status_filter=kw.get("status_filter"),
    )


def _list_categories(**kw):
    return categories.list_categories(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        portfolio_id=kw.get("portfolio_id"),
        category_type=kw.get("category_type"),
    )


def _list_receivables(**kw):
    return receivables.list_receivables(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        contract_id=kw.get("contract_id"),
        status_filter=kw.get("status_filter"),
    )


def _list_invoices(**kw):
    return invoices.list_invoices(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        supplier=kw.get("supplier"),
        status_filter=kw.get("status_filter"),
    )


def _list_maintenance(**kw):
    return maintenance.list_maintenance_cases(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        property_id=kw.get("property_id"),
        status_filter=kw.get("status_filter"),
    )


def _list_documents(**kw):
    return documents.list_documents(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        property_id=kw.get("property_id"),
        contract_id=kw.get("contract_id"),
    )


def _list_tasks(**kw):
    return tasks.list_tasks(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        status_filter=kw.get("status_filter"),
        assignee=kw.get("assignee"),
    )


def _list_calendar(**kw):
    return calendar.list_calendar_events(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        property_id=kw.get("property_id"),
        event_type=kw.get("event_type"),
    )


def _list_listings(**kw):
    return listings.list_listings(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        unit_id=kw.get("unit_id"),
        status_filter=kw.get("status_filter"),
    )


def _list_listing_photos(**kw):
    return listings.list_listing_photos(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        listing_id=kw.get("listing_id"),
    )


def _list_leads(**kw):
    return leads.list_leads(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        status_filter=kw.get("status_filter"),
        unit_id=kw.get("unit_id"),
        listing_id=kw.get("listing_id"),
        source=kw.get("source"),
    )


def _list_viewings(**kw):
    return viewings.list_viewings(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        status_filter=kw.get("status_filter"),
        lead_id=kw.get("lead_id"),
        unit_id=kw.get("unit_id"),
    )


def _list_billing_periods(**kw):
    return billing.list_billing_periods(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        property_id=kw.get("property_id"),
        status_filter=kw.get("status_filter"),
    )


def _list_allocation_keys(**kw):
    return billing.list_allocation_keys(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        property_id=kw.get("property_id"),
        key_type=kw.get("key_type"),
    )


def _list_cost_items(**kw):
    return billing.list_cost_items(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        billing_period_id=kw.get("billing_period_id"),
        allocation_key_id=kw.get("allocation_key_id"),
    )


def _list_utility_statements(**kw):
    return billing.list_utility_statements(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        billing_period_id=kw.get("billing_period_id"),
        contract_id=kw.get("contract_id"),
        status_filter=kw.get("status_filter"),
    )


def _list_deposits(**kw):
    return deposits.list_deposits(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        contract_id=kw.get("contract_id"),
        status_filter=kw.get("status_filter"),
    )


def _list_notifications(**kw):
    return notifications.list_notifications(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        status_filter=kw.get("status_filter"),
        notification_type=kw.get("notification_type"),
        severity=kw.get("severity"),
    )


def _list_notification_templates(**kw):
    return notifications.list_notification_templates(
        skip=kw.get("skip", S), limit=kw.get("limit", L),
        notification_type=kw.get("notification_type"),
    )


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
        store.leads,
        store.viewing_appointments,
        store.billing_periods,
        store.allocation_keys,
        store.cost_items,
        store.utility_statements,
        store.deposits,
        store.notifications,
        store.notification_templates,
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


# ---------------------------------------------------------------------------
# PATCH endpoint tests
# ---------------------------------------------------------------------------

class TestPatchEndpoints:
    def setup_method(self) -> None:
        _clear_store()

    def test_patch_portfolio(self) -> None:
        p = portfolios.create_portfolio(PortfolioCreate(name="Old", status="active"))
        patched = portfolios.patch_portfolio(p.id, PortfolioPatch(name="New"))
        assert patched.name == "New"
        assert patched.status == "active"  # unchanged

    def test_patch_portfolio_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            portfolios.patch_portfolio("nonexistent", PortfolioPatch(name="X"))
        assert exc_info.value.status_code == 404

    def test_patch_tenant(self) -> None:
        t = tenants.create_tenant(TenantCreate(full_name="Old", email="a@b.c"))
        patched = tenants.patch_tenant(t.id, TenantPatch(full_name="New"))
        assert patched.full_name == "New"
        assert patched.email == "a@b.c"  # unchanged

    def test_patch_property(self) -> None:
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        p = properties.create_property(
            PropertyCreate(portfolio_id=portfolio.id, name="Old", property_type="MFH")
        )
        patched = properties.patch_property(p.id, PropertyPatch(name="New"))
        assert patched.name == "New"
        assert patched.property_type == "MFH"  # unchanged

    def test_patch_unit(self) -> None:
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        prop = store.create_property(
            PropertyCreate(portfolio_id=portfolio.id, name="H", property_type="MFH")
        )
        u = units.create_unit(
            UnitCreate(property_id=prop.id, label="EG", unit_type="Wohnung", cold_rent=500.0)
        )
        patched = units.patch_unit(u.id, UnitPatch(cold_rent=600.0))
        assert patched.cold_rent == 600.0
        assert patched.label == "EG"  # unchanged

    def test_patch_contract(self) -> None:
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        prop = store.create_property(
            PropertyCreate(portfolio_id=portfolio.id, name="H", property_type="MFH")
        )
        unit = store.create_unit(
            UnitCreate(property_id=prop.id, label="1", unit_type="Wohnung")
        )
        tenant = store.create_tenant(TenantCreate(full_name="M"))
        c = contracts.create_contract(
            ContractCreate(
                contract_number="C-1", property_id=prop.id,
                unit_id=unit.id, tenant_id=tenant.id,
                start_date=datetime.date(2025, 1, 1),
            )
        )
        patched = contracts.patch_contract(c.id, ContractPatch(status="terminated"))
        assert patched.status == "terminated"
        assert patched.contract_number == "C-1"  # unchanged

    def test_patch_account(self) -> None:
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        a = accounts.create_account(
            AccountCreate(portfolio_id=portfolio.id, name="Old", account_type="Bankkonto")
        )
        patched = accounts.patch_account(a.id, AccountPatch(name="New"))
        assert patched.name == "New"
        assert patched.account_type == "Bankkonto"

    def test_patch_booking(self) -> None:
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        account = store.create_account(
            AccountCreate(portfolio_id=portfolio.id, name="K", account_type="Bankkonto")
        )
        b = bookings.create_booking(
            BookingCreate(account_id=account.id, booking_date=datetime.date(2025, 1, 1), amount=100.0)
        )
        patched = bookings.patch_booking(b.id, BookingPatch(amount=200.0))
        assert patched.amount == 200.0
        assert patched.status == "open"

    def test_patch_category(self) -> None:
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        c = categories.create_category(
            CategoryCreate(portfolio_id=portfolio.id, name="Old", category_type="income")
        )
        patched = categories.patch_category(c.id, CategoryPatch(name="New"))
        assert patched.name == "New"
        assert patched.category_type == "income"

    def test_patch_invoice(self) -> None:
        inv = invoices.create_invoice(
            InvoiceCreate(supplier="Old", invoice_date=datetime.date(2025, 1, 1), net_amount=100.0, gross_amount=119.0)
        )
        patched = invoices.patch_invoice(inv.id, InvoicePatch(status="paid"))
        assert patched.status == "paid"
        assert patched.supplier == "Old"

    def test_patch_task(self) -> None:
        t = tasks.create_task(TaskCreate(title="Old", status="open"))
        patched = tasks.patch_task(t.id, TaskPatch(status="done"))
        assert patched.status == "done"
        assert patched.title == "Old"

    def test_patch_calendar_event(self) -> None:
        e = calendar.create_calendar_event(
            CalendarEventCreate(title="Old", event_type="Besichtigung", event_date=datetime.date(2025, 3, 15))
        )
        patched = calendar.patch_calendar_event(e.id, CalendarEventPatch(title="New"))
        assert patched.title == "New"
        assert patched.event_type == "Besichtigung"

    def test_patch_document(self) -> None:
        d = documents.create_document(DocumentCreate(title="Old", file_url="u"))
        patched = documents.patch_document(d.id, DocumentPatch(title="New"))
        assert patched.title == "New"
        assert patched.file_url == "u"

    def test_patch_maintenance_case(self) -> None:
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        prop = store.create_property(
            PropertyCreate(portfolio_id=portfolio.id, name="H", property_type="MFH")
        )
        m = maintenance.create_maintenance_case(
            MaintenanceCaseCreate(property_id=prop.id, title="Old", status="open")
        )
        patched = maintenance.patch_maintenance_case(m.id, MaintenanceCasePatch(status="done"))
        assert patched.status == "done"
        assert patched.title == "Old"

    def test_patch_listing(self) -> None:
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        prop = store.create_property(
            PropertyCreate(portfolio_id=portfolio.id, name="H", property_type="MFH")
        )
        unit = store.create_unit(
            UnitCreate(property_id=prop.id, label="1", unit_type="Wohnung")
        )
        lst = listings.create_listing(ListingCreate(unit_id=unit.id, title="Old", status="draft"))
        patched = listings.patch_listing(lst.id, ListingPatch(status="active"))
        assert patched.status == "active"
        assert patched.title == "Old"

    def test_patch_listing_photo(self) -> None:
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        prop = store.create_property(
            PropertyCreate(portfolio_id=portfolio.id, name="H", property_type="MFH")
        )
        unit = store.create_unit(
            UnitCreate(property_id=prop.id, label="1", unit_type="Wohnung")
        )
        lst = store.create_listing(ListingCreate(unit_id=unit.id, title="I"))
        photo = listings.create_listing_photo(
            ListingPhotoCreate(listing_id=lst.id, file_url="old.jpg")
        )
        patched = listings.patch_listing_photo(photo.id, ListingPhotoPatch(is_primary=True))
        assert patched.is_primary is True
        assert patched.file_url == "old.jpg"

    def test_patch_preserves_created_at(self) -> None:
        p = portfolios.create_portfolio(PortfolioCreate(name="T"))
        patched = portfolios.patch_portfolio(p.id, PortfolioPatch(name="T2"))
        assert patched.created_at == p.created_at
        assert patched.updated_at >= p.updated_at

    def test_patch_receivable(self) -> None:
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        prop = store.create_property(
            PropertyCreate(portfolio_id=portfolio.id, name="H", property_type="MFH")
        )
        unit = store.create_unit(
            UnitCreate(property_id=prop.id, label="1", unit_type="Wohnung")
        )
        tenant = store.create_tenant(TenantCreate(full_name="M"))
        contract = store.create_contract(
            ContractCreate(
                contract_number="C-1", property_id=prop.id,
                unit_id=unit.id, tenant_id=tenant.id,
                start_date=datetime.date(2025, 1, 1),
            )
        )
        r = receivables.create_receivable(
            ReceivableCreate(contract_id=contract.id, due_date=datetime.date(2025, 2, 1), amount_due=500.0)
        )
        patched = receivables.patch_receivable(r.id, ReceivablePatch(status="paid"))
        assert patched.status == "paid"
        assert patched.amount_due == 500.0


# ---------------------------------------------------------------------------
# Leads (Interessenten)
# ---------------------------------------------------------------------------

class TestLeads:
    def setup_method(self) -> None:
        _clear_store()

    def test_create_lead(self) -> None:
        lead = leads.create_lead(LeadCreate(full_name="Max Mustermann"))
        assert lead.full_name == "Max Mustermann"
        assert lead.id
        assert lead.status == "new"
        assert lead.created_at is not None

    def test_list_leads_empty(self) -> None:
        assert _list_leads() == []

    def test_list_leads_returns_created(self) -> None:
        leads.create_lead(LeadCreate(full_name="A"))
        leads.create_lead(LeadCreate(full_name="B"))
        assert len(_list_leads()) == 2

    def test_get_lead(self) -> None:
        created = leads.create_lead(LeadCreate(full_name="Test"))
        fetched = leads.get_lead(created.id)
        assert fetched.id == created.id
        assert fetched.full_name == "Test"

    def test_get_lead_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            leads.get_lead("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_lead(self) -> None:
        created = leads.create_lead(LeadCreate(full_name="Old"))
        updated = leads.update_lead(
            created.id, LeadCreate(full_name="New", status="contacted")
        )
        assert updated.full_name == "New"
        assert updated.status == "contacted"
        assert updated.created_at == created.created_at

    def test_update_lead_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            leads.update_lead("nonexistent", LeadCreate(full_name="X"))
        assert exc_info.value.status_code == 404

    def test_delete_lead(self) -> None:
        created = leads.create_lead(LeadCreate(full_name="Del"))
        leads.delete_lead(created.id)
        assert _list_leads() == []

    def test_delete_lead_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            leads.delete_lead("nonexistent")
        assert exc_info.value.status_code == 404

    def test_create_lead_with_listing(self) -> None:
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        prop = store.create_property(
            PropertyCreate(portfolio_id=portfolio.id, name="H", property_type="MFH")
        )
        unit = store.create_unit(
            UnitCreate(property_id=prop.id, label="1", unit_type="Wohnung")
        )
        listing = store.create_listing(ListingCreate(unit_id=unit.id, title="I"))
        lead = leads.create_lead(
            LeadCreate(full_name="M", listing_id=listing.id, unit_id=unit.id)
        )
        assert lead.listing_id == listing.id
        assert lead.unit_id == unit.id

    def test_create_lead_bad_listing_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            leads.create_lead(LeadCreate(full_name="M", listing_id="bad"))
        assert exc_info.value.status_code == 400

    def test_create_lead_bad_unit_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            leads.create_lead(LeadCreate(full_name="M", unit_id="bad"))
        assert exc_info.value.status_code == 400

    def test_filter_by_status(self) -> None:
        leads.create_lead(LeadCreate(full_name="A", status="new"))
        leads.create_lead(LeadCreate(full_name="B", status="contacted"))
        assert len(_list_leads(status_filter="new")) == 1
        assert len(_list_leads(status_filter="contacted")) == 1

    def test_filter_by_source(self) -> None:
        leads.create_lead(LeadCreate(full_name="A", source="immoscout"))
        leads.create_lead(LeadCreate(full_name="B", source="referral"))
        assert len(_list_leads(source="immoscout")) == 1

    def test_pagination(self) -> None:
        for i in range(5):
            leads.create_lead(LeadCreate(full_name=f"L{i}"))
        assert len(_list_leads(skip=0, limit=2)) == 2
        assert len(_list_leads(skip=3, limit=10)) == 2

    def test_patch_lead(self) -> None:
        lead = leads.create_lead(LeadCreate(full_name="Old", status="new"))
        patched = leads.patch_lead(lead.id, LeadPatch(status="contacted"))
        assert patched.status == "contacted"
        assert patched.full_name == "Old"
        assert patched.created_at == lead.created_at

    def test_patch_lead_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            leads.patch_lead("nonexistent", LeadPatch(status="contacted"))
        assert exc_info.value.status_code == 404

    def test_delete_lead_cascades_viewings(self) -> None:
        portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        prop = store.create_property(
            PropertyCreate(portfolio_id=portfolio.id, name="H", property_type="MFH")
        )
        unit = store.create_unit(
            UnitCreate(property_id=prop.id, label="1", unit_type="Wohnung")
        )
        lead = store.create_lead(LeadCreate(full_name="M"))
        store.create_viewing_appointment(
            ViewingAppointmentCreate(
                lead_id=lead.id, unit_id=unit.id,
                scheduled_at=datetime.datetime(2025, 6, 1, 10, 0),
            )
        )
        assert len(list(store.viewing_appointments.values())) == 1
        leads.delete_lead(lead.id)
        assert len(list(store.viewing_appointments.values())) == 0


# ---------------------------------------------------------------------------
# Viewing Appointments (Besichtigungen)
# ---------------------------------------------------------------------------

class TestViewings:
    def setup_method(self) -> None:
        _clear_store()
        # Create prerequisite entities
        self.portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        self.prop = store.create_property(
            PropertyCreate(portfolio_id=self.portfolio.id, name="H", property_type="MFH")
        )
        self.unit = store.create_unit(
            UnitCreate(property_id=self.prop.id, label="1", unit_type="Wohnung")
        )
        self.lead = store.create_lead(LeadCreate(full_name="Max"))
        self.dt = datetime.datetime(2025, 6, 15, 14, 0)

    def _make(self, **overrides):
        data = dict(lead_id=self.lead.id, unit_id=self.unit.id, scheduled_at=self.dt)
        data.update(overrides)
        return ViewingAppointmentCreate(**data)

    def test_create_viewing(self) -> None:
        v = viewings.create_viewing(self._make())
        assert v.lead_id == self.lead.id
        assert v.unit_id == self.unit.id
        assert v.status == "scheduled"
        assert v.id
        assert v.created_at is not None

    def test_list_viewings_empty(self) -> None:
        assert _list_viewings() == []

    def test_list_viewings_returns_created(self) -> None:
        viewings.create_viewing(self._make())
        viewings.create_viewing(self._make(scheduled_at=datetime.datetime(2025, 7, 1, 10, 0)))
        assert len(_list_viewings()) == 2

    def test_get_viewing(self) -> None:
        created = viewings.create_viewing(self._make())
        fetched = viewings.get_viewing(created.id)
        assert fetched.id == created.id

    def test_get_viewing_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            viewings.get_viewing("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_viewing(self) -> None:
        created = viewings.create_viewing(self._make())
        updated = viewings.update_viewing(
            created.id, self._make(status="completed", agent="Agent Smith")
        )
        assert updated.status == "completed"
        assert updated.agent == "Agent Smith"
        assert updated.created_at == created.created_at

    def test_update_viewing_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            viewings.update_viewing("nonexistent", self._make())
        assert exc_info.value.status_code == 404

    def test_update_viewing_bad_lead_400(self) -> None:
        created = viewings.create_viewing(self._make())
        with pytest.raises(HTTPException) as exc_info:
            viewings.update_viewing(created.id, self._make(lead_id="bad"))
        assert exc_info.value.status_code == 400

    def test_update_viewing_bad_unit_400(self) -> None:
        created = viewings.create_viewing(self._make())
        with pytest.raises(HTTPException) as exc_info:
            viewings.update_viewing(created.id, self._make(unit_id="bad"))
        assert exc_info.value.status_code == 400

    def test_delete_viewing(self) -> None:
        created = viewings.create_viewing(self._make())
        viewings.delete_viewing(created.id)
        assert _list_viewings() == []

    def test_delete_viewing_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            viewings.delete_viewing("nonexistent")
        assert exc_info.value.status_code == 404

    def test_create_viewing_bad_lead_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            viewings.create_viewing(
                ViewingAppointmentCreate(
                    lead_id="bad", unit_id=self.unit.id, scheduled_at=self.dt
                )
            )
        assert exc_info.value.status_code == 400

    def test_create_viewing_bad_unit_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            viewings.create_viewing(
                ViewingAppointmentCreate(
                    lead_id=self.lead.id, unit_id="bad", scheduled_at=self.dt
                )
            )
        assert exc_info.value.status_code == 400

    def test_filter_by_status(self) -> None:
        viewings.create_viewing(self._make())
        v2 = viewings.create_viewing(self._make(scheduled_at=datetime.datetime(2025, 7, 1, 10, 0)))
        viewings.update_viewing(
            v2.id, self._make(
                status="completed",
                scheduled_at=datetime.datetime(2025, 7, 1, 10, 0),
            ),
        )
        assert len(_list_viewings(status_filter="scheduled")) == 1
        assert len(_list_viewings(status_filter="completed")) == 1

    def test_filter_by_lead(self) -> None:
        lead2 = store.create_lead(LeadCreate(full_name="Other"))
        viewings.create_viewing(self._make())
        viewings.create_viewing(self._make(lead_id=lead2.id, scheduled_at=datetime.datetime(2025, 8, 1, 10, 0)))
        assert len(_list_viewings(lead_id=self.lead.id)) == 1
        assert len(_list_viewings(lead_id=lead2.id)) == 1

    def test_filter_by_unit(self) -> None:
        unit2 = store.create_unit(
            UnitCreate(property_id=self.prop.id, label="2", unit_type="Wohnung")
        )
        viewings.create_viewing(self._make())
        viewings.create_viewing(self._make(unit_id=unit2.id, scheduled_at=datetime.datetime(2025, 8, 1, 10, 0)))
        assert len(_list_viewings(unit_id=self.unit.id)) == 1
        assert len(_list_viewings(unit_id=unit2.id)) == 1

    def test_pagination(self) -> None:
        for i in range(5):
            viewings.create_viewing(
                self._make(scheduled_at=datetime.datetime(2025, 6, 15 + i, 10, 0))
            )
        assert len(_list_viewings(skip=0, limit=2)) == 2
        assert len(_list_viewings(skip=3, limit=10)) == 2

    def test_patch_viewing(self) -> None:
        v = viewings.create_viewing(self._make())
        patched = viewings.patch_viewing(v.id, ViewingAppointmentPatch(status="cancelled"))
        assert patched.status == "cancelled"
        assert patched.lead_id == self.lead.id
        assert patched.created_at == v.created_at

    def test_patch_viewing_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            viewings.patch_viewing("nonexistent", ViewingAppointmentPatch(status="cancelled"))
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Billing Periods (Abrechnungsperioden)
# ---------------------------------------------------------------------------

class TestBillingPeriods:
    def setup_method(self) -> None:
        _clear_store()
        self.portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        self.prop = store.create_property(
            PropertyCreate(portfolio_id=self.portfolio.id, name="H", property_type="MFH")
        )

    def test_create_billing_period(self) -> None:
        bp = billing.create_billing_period(
            BillingPeriodCreate(
                property_id=self.prop.id, label="BK 2024",
                start_date=datetime.date(2024, 1, 1), end_date=datetime.date(2024, 12, 31),
            )
        )
        assert bp.label == "BK 2024"
        assert bp.status == "draft"
        assert bp.id

    def test_list_billing_periods_empty(self) -> None:
        assert _list_billing_periods() == []

    def test_list_billing_periods_with_filter(self) -> None:
        billing.create_billing_period(
            BillingPeriodCreate(
                property_id=self.prop.id, label="BK 2024",
                start_date=datetime.date(2024, 1, 1), end_date=datetime.date(2024, 12, 31),
            )
        )
        assert len(_list_billing_periods(property_id=self.prop.id)) == 1
        assert len(_list_billing_periods(property_id="other")) == 0

    def test_get_billing_period(self) -> None:
        bp = billing.create_billing_period(
            BillingPeriodCreate(
                property_id=self.prop.id, label="BK 2024",
                start_date=datetime.date(2024, 1, 1), end_date=datetime.date(2024, 12, 31),
            )
        )
        fetched = billing.get_billing_period(bp.id)
        assert fetched.id == bp.id

    def test_get_billing_period_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            billing.get_billing_period("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_billing_period(self) -> None:
        bp = billing.create_billing_period(
            BillingPeriodCreate(
                property_id=self.prop.id, label="BK 2024",
                start_date=datetime.date(2024, 1, 1), end_date=datetime.date(2024, 12, 31),
            )
        )
        updated = billing.update_billing_period(
            bp.id,
            BillingPeriodCreate(
                property_id=self.prop.id, label="BK 2024 Final",
                start_date=datetime.date(2024, 1, 1), end_date=datetime.date(2024, 12, 31),
                status="finalized",
            ),
        )
        assert updated.label == "BK 2024 Final"
        assert updated.status == "finalized"

    def test_create_bad_dates_400(self) -> None:
        with pytest.raises((HTTPException, Exception)):
            billing.create_billing_period(
                BillingPeriodCreate(
                    property_id=self.prop.id, label="Bad",
                    start_date=datetime.date(2024, 12, 31), end_date=datetime.date(2024, 1, 1),
                )
            )

    def test_create_bad_property_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            billing.create_billing_period(
                BillingPeriodCreate(
                    property_id="bad", label="X",
                    start_date=datetime.date(2024, 1, 1), end_date=datetime.date(2024, 12, 31),
                )
            )
        assert exc_info.value.status_code == 400

    def test_delete_billing_period(self) -> None:
        bp = billing.create_billing_period(
            BillingPeriodCreate(
                property_id=self.prop.id, label="BK 2024",
                start_date=datetime.date(2024, 1, 1), end_date=datetime.date(2024, 12, 31),
            )
        )
        billing.delete_billing_period(bp.id)
        assert _list_billing_periods() == []

    def test_delete_billing_period_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            billing.delete_billing_period("nonexistent")
        assert exc_info.value.status_code == 404

    def test_patch_billing_period(self) -> None:
        bp = billing.create_billing_period(
            BillingPeriodCreate(
                property_id=self.prop.id, label="BK 2024",
                start_date=datetime.date(2024, 1, 1), end_date=datetime.date(2024, 12, 31),
            )
        )
        patched = billing.patch_billing_period(bp.id, BillingPeriodPatch(status="finalized"))
        assert patched.status == "finalized"
        assert patched.label == "BK 2024"


# ---------------------------------------------------------------------------
# Allocation Keys (Verteilerschlüssel)
# ---------------------------------------------------------------------------

class TestAllocationKeys:
    def setup_method(self) -> None:
        _clear_store()
        self.portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        self.prop = store.create_property(
            PropertyCreate(portfolio_id=self.portfolio.id, name="H", property_type="MFH")
        )

    def test_create_allocation_key(self) -> None:
        ak = billing.create_allocation_key(
            AllocationKeyCreate(property_id=self.prop.id, name="Wohnfläche", key_type="area_sqm")
        )
        assert ak.name == "Wohnfläche"
        assert ak.key_type == "area_sqm"

    def test_list_allocation_keys_empty(self) -> None:
        assert _list_allocation_keys() == []

    def test_list_allocation_keys_with_filter(self) -> None:
        billing.create_allocation_key(
            AllocationKeyCreate(property_id=self.prop.id, name="Fläche", key_type="area_sqm")
        )
        billing.create_allocation_key(
            AllocationKeyCreate(property_id=self.prop.id, name="Einheiten", key_type="unit_count")
        )
        assert len(_list_allocation_keys(key_type="area_sqm")) == 1

    def test_get_allocation_key_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            billing.get_allocation_key("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_allocation_key(self) -> None:
        ak = billing.create_allocation_key(
            AllocationKeyCreate(property_id=self.prop.id, name="Old", key_type="area_sqm")
        )
        updated = billing.update_allocation_key(
            ak.id,
            AllocationKeyCreate(property_id=self.prop.id, name="New", key_type="unit_count"),
        )
        assert updated.name == "New"
        assert updated.key_type == "unit_count"

    def test_delete_allocation_key(self) -> None:
        ak = billing.create_allocation_key(
            AllocationKeyCreate(property_id=self.prop.id, name="Del", key_type="area_sqm")
        )
        billing.delete_allocation_key(ak.id)
        assert _list_allocation_keys() == []

    def test_delete_allocation_key_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            billing.delete_allocation_key("nonexistent")
        assert exc_info.value.status_code == 404

    def test_patch_allocation_key(self) -> None:
        ak = billing.create_allocation_key(
            AllocationKeyCreate(property_id=self.prop.id, name="Old", key_type="area_sqm")
        )
        patched = billing.patch_allocation_key(ak.id, AllocationKeyPatch(name="Updated"))
        assert patched.name == "Updated"
        assert patched.key_type == "area_sqm"


# ---------------------------------------------------------------------------
# Cost Items (Kostenpositionen)
# ---------------------------------------------------------------------------

class TestCostItems:
    def setup_method(self) -> None:
        _clear_store()
        self.portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        self.prop = store.create_property(
            PropertyCreate(portfolio_id=self.portfolio.id, name="H", property_type="MFH")
        )
        self.bp = store.create_billing_period(
            BillingPeriodCreate(
                property_id=self.prop.id, label="BK 2024",
                start_date=datetime.date(2024, 1, 1), end_date=datetime.date(2024, 12, 31),
            )
        )
        self.ak = store.create_allocation_key(
            AllocationKeyCreate(property_id=self.prop.id, name="Fläche", key_type="area_sqm")
        )

    def test_create_cost_item(self) -> None:
        ci = billing.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id, description="Wasser",
                amount=1000.0, allocation_key_id=self.ak.id,
            )
        )
        assert ci.description == "Wasser"
        assert ci.amount == 1000.0

    def test_list_cost_items_empty(self) -> None:
        assert _list_cost_items() == []

    def test_list_cost_items_with_filter(self) -> None:
        billing.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id, description="Wasser",
                amount=1000.0, allocation_key_id=self.ak.id,
            )
        )
        assert len(_list_cost_items(billing_period_id=self.bp.id)) == 1
        assert len(_list_cost_items(billing_period_id="other")) == 0

    def test_get_cost_item_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            billing.get_cost_item("nonexistent")
        assert exc_info.value.status_code == 404

    def test_create_cost_item_bad_period_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            billing.create_cost_item(
                CostItemCreate(
                    billing_period_id="bad", description="X",
                    amount=100.0, allocation_key_id=self.ak.id,
                )
            )
        assert exc_info.value.status_code == 400

    def test_create_cost_item_bad_key_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            billing.create_cost_item(
                CostItemCreate(
                    billing_period_id=self.bp.id, description="X",
                    amount=100.0, allocation_key_id="bad",
                )
            )
        assert exc_info.value.status_code == 400

    def test_delete_cost_item(self) -> None:
        ci = billing.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id, description="X",
                amount=100.0, allocation_key_id=self.ak.id,
            )
        )
        billing.delete_cost_item(ci.id)
        assert _list_cost_items() == []

    def test_patch_cost_item(self) -> None:
        ci = billing.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id, description="Old",
                amount=100.0, allocation_key_id=self.ak.id,
            )
        )
        patched = billing.patch_cost_item(ci.id, CostItemPatch(description="Updated"))
        assert patched.description == "Updated"
        assert patched.amount == 100.0


# ---------------------------------------------------------------------------
# Generate Utility Statements (Betriebskostenabrechnung generieren)
# ---------------------------------------------------------------------------

class TestGenerateUtilityStatements:
    def setup_method(self) -> None:
        _clear_store()
        self.portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        self.prop = store.create_property(
            PropertyCreate(portfolio_id=self.portfolio.id, name="H", property_type="MFH")
        )
        self.unit1 = store.create_unit(
            UnitCreate(
                property_id=self.prop.id, label="EG links", unit_type="Wohnung",
                area_sqm=60.0, service_charge_advance=150.0, heating_advance=50.0,
            )
        )
        self.unit2 = store.create_unit(
            UnitCreate(
                property_id=self.prop.id, label="EG rechts", unit_type="Wohnung",
                area_sqm=40.0, service_charge_advance=100.0, heating_advance=30.0,
            )
        )
        self.tenant1 = store.create_tenant(TenantCreate(full_name="Müller"))
        self.tenant2 = store.create_tenant(TenantCreate(full_name="Schmidt"))
        self.contract1 = store.create_contract(
            ContractCreate(
                contract_number="V-1", property_id=self.prop.id,
                unit_id=self.unit1.id, tenant_id=self.tenant1.id,
                start_date=datetime.date(2024, 1, 1),
            )
        )
        self.contract2 = store.create_contract(
            ContractCreate(
                contract_number="V-2", property_id=self.prop.id,
                unit_id=self.unit2.id, tenant_id=self.tenant2.id,
                start_date=datetime.date(2024, 1, 1),
            )
        )
        self.bp = store.create_billing_period(
            BillingPeriodCreate(
                property_id=self.prop.id, label="BK 2024",
                start_date=datetime.date(2024, 1, 1), end_date=datetime.date(2024, 12, 31),
            )
        )
        self.ak_area = store.create_allocation_key(
            AllocationKeyCreate(property_id=self.prop.id, name="Fläche", key_type="area_sqm")
        )

    def test_generate_distributes_by_area(self) -> None:
        store.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id, description="Wasser",
                amount=1000.0, allocation_key_id=self.ak_area.id,
            )
        )
        stmts = billing.generate_utility_statements(self.bp.id)
        assert len(stmts) == 2
        by_unit = {s.unit_id: s for s in stmts}
        # 60/(60+40) * 1000 = 600, 40/(60+40) * 1000 = 400
        assert by_unit[self.unit1.id].total_cost == 600.0
        assert by_unit[self.unit2.id].total_cost == 400.0

    def test_generate_calculates_advances(self) -> None:
        store.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id, description="Wasser",
                amount=1000.0, allocation_key_id=self.ak_area.id,
            )
        )
        stmts = billing.generate_utility_statements(self.bp.id)
        by_unit = {s.unit_id: s for s in stmts}
        # Unit1: (150+50) * 12 = 2400 advance
        # Unit2: (100+30) * 12 = 1560 advance
        assert by_unit[self.unit1.id].advance_paid == 2400.0
        assert by_unit[self.unit2.id].advance_paid == 1560.0

    def test_generate_balance_refund(self) -> None:
        store.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id, description="Wasser",
                amount=1000.0, allocation_key_id=self.ak_area.id,
            )
        )
        stmts = billing.generate_utility_statements(self.bp.id)
        by_unit = {s.unit_id: s for s in stmts}
        # Unit1: 600 cost - 2400 advance = -1800 (refund)
        assert by_unit[self.unit1.id].balance == -1800.0

    def test_generate_creates_utility_statements_in_store(self) -> None:
        store.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id, description="Wasser",
                amount=1000.0, allocation_key_id=self.ak_area.id,
            )
        )
        billing.generate_utility_statements(self.bp.id)
        assert len(_list_utility_statements(billing_period_id=self.bp.id)) == 2

    def test_generate_regeneration_replaces_old(self) -> None:
        store.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id, description="Wasser",
                amount=1000.0, allocation_key_id=self.ak_area.id,
            )
        )
        billing.generate_utility_statements(self.bp.id)
        assert len(_list_utility_statements()) == 2
        # Regenerate
        billing.generate_utility_statements(self.bp.id)
        assert len(_list_utility_statements()) == 2  # Still 2, not 4

    def test_generate_excludes_inactive_contracts(self) -> None:
        terminated = store.create_contract(
            ContractCreate(
                contract_number="V-3", property_id=self.prop.id,
                unit_id=self.unit1.id, tenant_id=self.tenant1.id,
                start_date=datetime.date(2024, 1, 1), status="terminated",
            )
        )
        draft = store.create_contract(
            ContractCreate(
                contract_number="V-4", property_id=self.prop.id,
                unit_id=self.unit2.id, tenant_id=self.tenant2.id,
                start_date=datetime.date(2024, 1, 1), status="draft",
            )
        )
        store.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id, description="Wasser",
                amount=1000.0, allocation_key_id=self.ak_area.id,
            )
        )
        stmts = billing.generate_utility_statements(self.bp.id)
        statement_contract_ids = {s.contract_id for s in stmts}
        assert terminated.id not in statement_contract_ids
        assert draft.id not in statement_contract_ids
        assert statement_contract_ids == {self.contract1.id, self.contract2.id}

    def test_generate_no_contracts_400(self) -> None:
        # Remove all contracts
        for cid in list(store.contracts.keys()):
            store.contracts.pop(cid)
        store.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id, description="X",
                amount=100.0, allocation_key_id=self.ak_area.id,
            )
        )
        with pytest.raises(HTTPException) as exc_info:
            billing.generate_utility_statements(self.bp.id)
        assert exc_info.value.status_code == 400

    def test_generate_no_cost_items_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            billing.generate_utility_statements(self.bp.id)
        assert exc_info.value.status_code == 400

    def test_generate_period_not_found_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            billing.generate_utility_statements("nonexistent")
        assert exc_info.value.status_code == 404

    def test_generate_unit_count_key(self) -> None:
        ak_count = store.create_allocation_key(
            AllocationKeyCreate(property_id=self.prop.id, name="Einheiten", key_type="unit_count")
        )
        store.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id, description="Müll",
                amount=600.0, allocation_key_id=ak_count.id,
            )
        )
        stmts = billing.generate_utility_statements(self.bp.id)
        by_unit = {s.unit_id: s for s in stmts}
        # Equal distribution: 600/2 = 300 each
        assert by_unit[self.unit1.id].total_cost == 300.0
        assert by_unit[self.unit2.id].total_cost == 300.0

    def test_generate_person_count_key_uses_rooms(self) -> None:
        ak_person = store.create_allocation_key(
            AllocationKeyCreate(property_id=self.prop.id, name="Personen", key_type="person_count")
        )
        store.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id,
                description="Hausstrom",
                amount=300.0,
                allocation_key_id=ak_person.id,
            )
        )

        # rooms as proxy: 60%/40% split (3.0 vs 2.0)
        store.update_unit(
            self.unit1.id,
            UnitCreate(
                property_id=self.prop.id,
                label="EG links",
                unit_type="Wohnung",
                area_sqm=60.0,
                rooms=3.0,
                service_charge_advance=150.0,
                heating_advance=50.0,
            ),
        )
        store.update_unit(
            self.unit2.id,
            UnitCreate(
                property_id=self.prop.id,
                label="EG rechts",
                unit_type="Wohnung",
                area_sqm=40.0,
                rooms=2.0,
                service_charge_advance=100.0,
                heating_advance=30.0,
            ),
        )

        stmts = billing.generate_utility_statements(self.bp.id)
        by_unit = {s.unit_id: s for s in stmts}
        assert by_unit[self.unit1.id].total_cost == 180.0
        assert by_unit[self.unit2.id].total_cost == 120.0

    def test_generate_consumption_key_uses_meter_readings(self) -> None:
        ak_consumption = store.create_allocation_key(
            AllocationKeyCreate(property_id=self.prop.id, name="Verbrauch", key_type="consumption")
        )
        store.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id,
                description="Heizenergie",
                amount=600.0,
                allocation_key_id=ak_consumption.id,
            )
        )

        m1 = store.create_meter(MeterCreate(unit_id=self.unit1.id, meter_type="heating", serial_number="M1"))
        m2 = store.create_meter(MeterCreate(unit_id=self.unit2.id, meter_type="heating", serial_number="M2"))

        store.create_standalone_meter_reading(
            StandaloneMeterReadingCreate(meter_id=m1.id, reading_date=datetime.date(2024, 1, 1), value=100.0)
        )
        store.create_standalone_meter_reading(
            StandaloneMeterReadingCreate(meter_id=m1.id, reading_date=datetime.date(2024, 12, 31), value=250.0)
        )
        store.create_standalone_meter_reading(
            StandaloneMeterReadingCreate(meter_id=m2.id, reading_date=datetime.date(2024, 1, 1), value=100.0)
        )
        store.create_standalone_meter_reading(
            StandaloneMeterReadingCreate(meter_id=m2.id, reading_date=datetime.date(2024, 12, 31), value=150.0)
        )

        stmts = billing.generate_utility_statements(self.bp.id)
        by_unit = {s.unit_id: s for s in stmts}
        # consumption: unit1=150, unit2=50 -> 75% / 25%
        assert by_unit[self.unit1.id].total_cost == 450.0
        assert by_unit[self.unit2.id].total_cost == 150.0

    def test_utility_statement_patch(self) -> None:
        store.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id, description="Wasser",
                amount=1000.0, allocation_key_id=self.ak_area.id,
            )
        )
        stmts = billing.generate_utility_statements(self.bp.id)
        patched = billing.patch_utility_statement(
            stmts[0].id, UtilityStatementPatch(status="finalized")
        )
        assert patched.status == "finalized"

    def test_delete_utility_statement(self) -> None:
        store.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id, description="Wasser",
                amount=1000.0, allocation_key_id=self.ak_area.id,
            )
        )
        stmts = billing.generate_utility_statements(self.bp.id)
        billing.delete_utility_statement(stmts[0].id)
        assert len(_list_utility_statements()) == 1

    def test_delete_billing_period_cascades(self) -> None:
        store.create_cost_item(
            CostItemCreate(
                billing_period_id=self.bp.id, description="Wasser",
                amount=1000.0, allocation_key_id=self.ak_area.id,
            )
        )
        billing.generate_utility_statements(self.bp.id)
        assert len(_list_cost_items()) == 1
        assert len(_list_utility_statements()) == 2
        billing.delete_billing_period(self.bp.id)
        assert len(_list_cost_items()) == 0
        assert len(_list_utility_statements()) == 0


# ---------------------------------------------------------------------------
# Deposits (Kautionen)
# ---------------------------------------------------------------------------

class TestDeposits:
    def setup_method(self) -> None:
        _clear_store()
        self.portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        self.prop = store.create_property(
            PropertyCreate(portfolio_id=self.portfolio.id, name="H", property_type="MFH")
        )
        self.unit = store.create_unit(
            UnitCreate(property_id=self.prop.id, label="1", unit_type="Wohnung")
        )
        self.tenant = store.create_tenant(TenantCreate(full_name="Müller"))
        self.contract = store.create_contract(
            ContractCreate(
                contract_number="V-1", property_id=self.prop.id,
                unit_id=self.unit.id, tenant_id=self.tenant.id,
                start_date=datetime.date(2024, 1, 1),
            )
        )

    def test_create_deposit(self) -> None:
        d = deposits.create_deposit(
            DepositCreate(contract_id=self.contract.id, amount=2000.0)
        )
        assert d.amount == 2000.0
        assert d.status == "held"
        assert d.id

    def test_list_deposits_empty(self) -> None:
        assert _list_deposits() == []

    def test_list_deposits_returns_created(self) -> None:
        deposits.create_deposit(DepositCreate(contract_id=self.contract.id, amount=1000.0))
        deposits.create_deposit(DepositCreate(contract_id=self.contract.id, amount=2000.0))
        assert len(_list_deposits()) == 2

    def test_get_deposit(self) -> None:
        d = deposits.create_deposit(
            DepositCreate(contract_id=self.contract.id, amount=1500.0)
        )
        fetched = deposits.get_deposit(d.id)
        assert fetched.id == d.id

    def test_get_deposit_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            deposits.get_deposit("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_deposit(self) -> None:
        d = deposits.create_deposit(
            DepositCreate(contract_id=self.contract.id, amount=1500.0)
        )
        updated = deposits.update_deposit(
            d.id,
            DepositCreate(
                contract_id=self.contract.id, amount=1500.0,
                status="returned", return_date=datetime.date(2025, 6, 1),
            ),
        )
        assert updated.status == "returned"
        assert updated.return_date == datetime.date(2025, 6, 1)
        assert updated.created_at == d.created_at

    def test_update_deposit_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            deposits.update_deposit(
                "nonexistent",
                DepositCreate(contract_id=self.contract.id, amount=1000.0),
            )
        assert exc_info.value.status_code == 404

    def test_create_deposit_bad_contract_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            deposits.create_deposit(DepositCreate(contract_id="bad", amount=1000.0))
        assert exc_info.value.status_code == 400

    def test_delete_deposit(self) -> None:
        d = deposits.create_deposit(
            DepositCreate(contract_id=self.contract.id, amount=1500.0)
        )
        deposits.delete_deposit(d.id)
        assert _list_deposits() == []

    def test_delete_deposit_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            deposits.delete_deposit("nonexistent")
        assert exc_info.value.status_code == 404

    def test_filter_by_contract(self) -> None:
        unit2 = store.create_unit(
            UnitCreate(property_id=self.prop.id, label="2", unit_type="Wohnung")
        )
        tenant2 = store.create_tenant(TenantCreate(full_name="Schmidt"))
        contract2 = store.create_contract(
            ContractCreate(
                contract_number="V-2", property_id=self.prop.id,
                unit_id=unit2.id, tenant_id=tenant2.id,
                start_date=datetime.date(2024, 1, 1),
            )
        )
        deposits.create_deposit(DepositCreate(contract_id=self.contract.id, amount=1000.0))
        deposits.create_deposit(DepositCreate(contract_id=contract2.id, amount=2000.0))
        assert len(_list_deposits(contract_id=self.contract.id)) == 1
        assert len(_list_deposits(contract_id=contract2.id)) == 1

    def test_filter_by_status(self) -> None:
        deposits.create_deposit(DepositCreate(contract_id=self.contract.id, amount=1000.0, status="held"))
        deposits.create_deposit(DepositCreate(contract_id=self.contract.id, amount=500.0, status="returned"))
        assert len(_list_deposits(status_filter="held")) == 1
        assert len(_list_deposits(status_filter="returned")) == 1

    def test_patch_deposit(self) -> None:
        d = deposits.create_deposit(
            DepositCreate(contract_id=self.contract.id, amount=2000.0)
        )
        patched = deposits.patch_deposit(
            d.id, DepositPatch(status="partially_returned", deductions=200.0, deduction_reason="Schäden")
        )
        assert patched.status == "partially_returned"
        assert patched.deductions == 200.0
        assert patched.deduction_reason == "Schäden"
        assert patched.amount == 2000.0
        assert patched.created_at == d.created_at

    def test_patch_deposit_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            deposits.patch_deposit("nonexistent", DepositPatch(status="returned"))
        assert exc_info.value.status_code == 404

    def test_deposit_with_deductions(self) -> None:
        d = deposits.create_deposit(
            DepositCreate(
                contract_id=self.contract.id, amount=3000.0,
                held_date=datetime.date(2024, 1, 1),
            )
        )
        updated = deposits.update_deposit(
            d.id,
            DepositCreate(
                contract_id=self.contract.id, amount=3000.0,
                status="partially_returned",
                held_date=datetime.date(2024, 1, 1),
                return_date=datetime.date(2025, 3, 1),
                deductions=500.0,
                deduction_reason="Renovierungskosten",
            ),
        )
        assert updated.deductions == 500.0
        assert updated.deduction_reason == "Renovierungskosten"
        assert updated.status == "partially_returned"


# ---------------------------------------------------------------------------
# Notifications (Benachrichtigungen)
# ---------------------------------------------------------------------------

class TestNotifications:
    def setup_method(self) -> None:
        _clear_store()

    def _make(self, **overrides):
        data = dict(
            notification_type="general", title="Test", content="Test content"
        )
        data.update(overrides)
        return NotificationCreate(**data)

    def test_create_notification(self) -> None:
        n = notifications.create_notification(self._make())
        assert n.title == "Test"
        assert n.status == "unread"
        assert n.id

    def test_list_notifications_empty(self) -> None:
        assert _list_notifications() == []

    def test_list_notifications_returns_created(self) -> None:
        notifications.create_notification(self._make(title="A"))
        notifications.create_notification(self._make(title="B"))
        assert len(_list_notifications()) == 2

    def test_get_notification(self) -> None:
        n = notifications.create_notification(self._make())
        fetched = notifications.get_notification(n.id)
        assert fetched.id == n.id

    def test_get_notification_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            notifications.get_notification("nonexistent")
        assert exc_info.value.status_code == 404

    def test_mark_read(self) -> None:
        n = notifications.create_notification(self._make())
        assert n.status == "unread"
        assert n.read_at is None
        read = notifications.mark_notification_read(n.id)
        assert read.status == "read"
        assert read.read_at is not None

    def test_mark_read_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            notifications.mark_notification_read("nonexistent")
        assert exc_info.value.status_code == 404

    def test_delete_notification(self) -> None:
        n = notifications.create_notification(self._make())
        notifications.delete_notification(n.id)
        assert _list_notifications() == []

    def test_delete_notification_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            notifications.delete_notification("nonexistent")
        assert exc_info.value.status_code == 404

    def test_filter_by_status(self) -> None:
        n = notifications.create_notification(self._make(title="A"))
        notifications.create_notification(self._make(title="B"))
        notifications.mark_notification_read(n.id)
        assert len(_list_notifications(status_filter="unread")) == 1
        assert len(_list_notifications(status_filter="read")) == 1

    def test_filter_by_type(self) -> None:
        notifications.create_notification(self._make(notification_type="overdue_payment"))
        notifications.create_notification(self._make(notification_type="task_due"))
        assert len(_list_notifications(notification_type="overdue_payment")) == 1

    def test_filter_by_severity(self) -> None:
        notifications.create_notification(self._make(severity="warning"))
        notifications.create_notification(self._make(severity="info"))
        assert len(_list_notifications(severity="warning")) == 1

    def test_patch_notification(self) -> None:
        n = notifications.create_notification(self._make())
        patched = notifications.patch_notification(n.id, NotificationPatch(status="archived"))
        assert patched.status == "archived"
        assert patched.title == "Test"

    def test_patch_notification_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            notifications.patch_notification("nonexistent", NotificationPatch(status="archived"))
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Notification Templates (Benachrichtigungsvorlagen)
# ---------------------------------------------------------------------------

class TestNotificationTemplates:
    def setup_method(self) -> None:
        _clear_store()

    def _make(self, **overrides):
        data = dict(
            name="Overdue", notification_type="overdue_payment",
            title_template="Überfällig: {tenant}", content_template="Zahlung {amount} EUR überfällig.",
        )
        data.update(overrides)
        return NotificationTemplateCreate(**data)

    def test_create_template(self) -> None:
        t = notifications.create_notification_template(self._make())
        assert t.name == "Overdue"
        assert t.id

    def test_list_templates_empty(self) -> None:
        assert _list_notification_templates() == []

    def test_list_templates_with_filter(self) -> None:
        notifications.create_notification_template(self._make())
        notifications.create_notification_template(
            self._make(name="Task", notification_type="task_due", title_template="T", content_template="C")
        )
        assert len(_list_notification_templates(notification_type="overdue_payment")) == 1

    def test_get_template(self) -> None:
        t = notifications.create_notification_template(self._make())
        fetched = notifications.get_notification_template(t.id)
        assert fetched.id == t.id

    def test_get_template_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            notifications.get_notification_template("nonexistent")
        assert exc_info.value.status_code == 404

    def test_update_template(self) -> None:
        t = notifications.create_notification_template(self._make())
        updated = notifications.update_notification_template(
            t.id, self._make(name="Updated")
        )
        assert updated.name == "Updated"
        assert updated.created_at == t.created_at

    def test_update_template_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            notifications.update_notification_template("nonexistent", self._make())
        assert exc_info.value.status_code == 404

    def test_delete_template(self) -> None:
        t = notifications.create_notification_template(self._make())
        notifications.delete_notification_template(t.id)
        assert _list_notification_templates() == []

    def test_delete_template_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            notifications.delete_notification_template("nonexistent")
        assert exc_info.value.status_code == 404

    def test_patch_template(self) -> None:
        t = notifications.create_notification_template(self._make())
        patched = notifications.patch_notification_template(
            t.id, NotificationTemplatePatch(name="Patched")
        )
        assert patched.name == "Patched"
        assert patched.notification_type == "overdue_payment"


# ---------------------------------------------------------------------------
# Notification Generation (Event Triggers)
# ---------------------------------------------------------------------------

class TestNotificationGeneration:
    def setup_method(self) -> None:
        _clear_store()
        self.portfolio = store.create_portfolio(PortfolioCreate(name="P"))
        self.prop = store.create_property(
            PropertyCreate(portfolio_id=self.portfolio.id, name="H", property_type="MFH")
        )
        self.unit = store.create_unit(
            UnitCreate(property_id=self.prop.id, label="1", unit_type="Wohnung")
        )
        self.tenant = store.create_tenant(TenantCreate(full_name="Müller"))
        self.contract = store.create_contract(
            ContractCreate(
                contract_number="V-1", property_id=self.prop.id,
                unit_id=self.unit.id, tenant_id=self.tenant.id,
                start_date=datetime.date(2024, 1, 1),
            )
        )

    def test_generate_overdue_payments(self) -> None:
        store.create_receivable(
            ReceivableCreate(
                contract_id=self.contract.id,
                due_date=datetime.date(2025, 1, 1),
                amount_due=500.0,
            )
        )
        result = notifications.generate_overdue_payment_notifications(
            as_of=datetime.date(2025, 2, 1)
        )
        assert len(result) == 1
        assert result[0].notification_type == "overdue_payment"
        assert "Müller" in result[0].title
        assert result[0].severity == "warning"

    def test_generate_overdue_payments_none_overdue(self) -> None:
        store.create_receivable(
            ReceivableCreate(
                contract_id=self.contract.id,
                due_date=datetime.date(2025, 3, 1),
                amount_due=500.0,
            )
        )
        result = notifications.generate_overdue_payment_notifications(
            as_of=datetime.date(2025, 2, 1)
        )
        assert len(result) == 0

    def test_generate_expiring_contracts(self) -> None:
        # Update contract to have an end_date
        store.update_contract(
            self.contract.id,
            ContractCreate(
                contract_number="V-1", property_id=self.prop.id,
                unit_id=self.unit.id, tenant_id=self.tenant.id,
                start_date=datetime.date(2024, 1, 1),
                end_date=datetime.date(2025, 6, 30),
            ),
        )
        result = notifications.generate_expiring_contract_notifications(
            days_ahead=90, as_of=datetime.date(2025, 5, 1)
        )
        assert len(result) == 1
        assert result[0].notification_type == "contract_expiry"
        assert "V-1" in result[0].title

    def test_generate_expiring_contracts_none_expiring(self) -> None:
        result = notifications.generate_expiring_contract_notifications(
            days_ahead=90, as_of=datetime.date(2025, 1, 1)
        )
        # Contract has no end_date, so no expiring contracts
        assert len(result) == 0

    def test_generate_due_tasks(self) -> None:
        store.create_task(
            TaskCreate(
                title="Fix sink", due_date=datetime.date(2025, 1, 15),
                property_id=self.prop.id,
            )
        )
        result = notifications.generate_due_task_notifications(
            as_of=datetime.date(2025, 2, 1)
        )
        assert len(result) == 1
        assert result[0].notification_type == "task_due"
        assert "Fix sink" in result[0].title
        assert result[0].severity == "warning"  # overdue

    def test_generate_due_tasks_today(self) -> None:
        store.create_task(
            TaskCreate(
                title="Today task", due_date=datetime.date(2025, 2, 1),
            )
        )
        result = notifications.generate_due_task_notifications(
            as_of=datetime.date(2025, 2, 1)
        )
        assert len(result) == 1
        assert result[0].severity == "info"  # due today, not overdue

    def test_generate_due_tasks_none_due(self) -> None:
        store.create_task(
            TaskCreate(
                title="Future task", due_date=datetime.date(2025, 6, 1),
            )
        )
        result = notifications.generate_due_task_notifications(
            as_of=datetime.date(2025, 2, 1)
        )
        assert len(result) == 0

    def test_generated_notifications_stored(self) -> None:
        store.create_receivable(
            ReceivableCreate(
                contract_id=self.contract.id,
                due_date=datetime.date(2025, 1, 1),
                amount_due=500.0,
            )
        )
        notifications.generate_overdue_payment_notifications(
            as_of=datetime.date(2025, 2, 1)
        )
        assert len(_list_notifications()) == 1
