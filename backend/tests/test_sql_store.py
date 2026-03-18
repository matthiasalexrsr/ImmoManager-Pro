"""Tests for SQLAlchemyStore - verifies database persistence layer.

Uses an in-memory SQLite database per test for isolation.
"""

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.db.orm_models import Base
from backend.models import (
    AccountCreate,
    AllocationKeyCreate,
    BillingPeriodCreate,
    BookingCreate,
    CalendarEventCreate,
    CategoryCreate,
    ContractCreate,
    CostItemCreate,
    DepositCreate,
    DocumentCreate,
    HandoverProtocolCreate,
    InvoiceCreate,
    LeadCreate,
    ListingCreate,
    ListingPhotoCreate,
    MaintenanceCaseCreate,
    MeterReadingCreate,
    NotificationCreate,
    NotificationTemplateCreate,
    PortfolioCreate,
    PortfolioPatch,
    PropertyCreate,
    ReceivableCreate,
    TaskCreate,
    TenantCreate,
    UnitCreate,
    UtilityStatementCreate,
    ViewingAppointmentCreate,
)
from backend.repositories.sql_store import SQLAlchemyStore
from backend.storage import NotFoundError, ValidationError


@pytest.fixture
def store():
    """Create a fresh SQLAlchemyStore with an in-memory SQLite DB for each test."""
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = Session()
    s = SQLAlchemyStore(db)
    yield s
    db.close()
    engine.dispose()


@pytest.fixture
def portfolio(store):
    return store.create_portfolio(PortfolioCreate(name="Test Portfolio"))


@pytest.fixture
def property_(store, portfolio):
    return store.create_property(PropertyCreate(
        portfolio_id=portfolio.id, name="Haus A", property_type="residential"
    ))


@pytest.fixture
def unit(store, property_):
    return store.create_unit(UnitCreate(
        property_id=property_.id, label="Wohnung 1", unit_type="apartment",
        area_sqm=75.0, cold_rent=800.0, service_charge_advance=200.0, heating_advance=100.0
    ))


@pytest.fixture
def tenant(store):
    return store.create_tenant(TenantCreate(full_name="Max Müller", email="max@example.com"))


@pytest.fixture
def contract(store, property_, unit, tenant):
    return store.create_contract(ContractCreate(
        property_id=property_.id, unit_id=unit.id, tenant_id=tenant.id,
        contract_number="V-001", start_date=date(2024, 1, 1)
    ))


@pytest.fixture
def account(store, portfolio):
    return store.create_account(AccountCreate(
        portfolio_id=portfolio.id, name="Mietkonto", account_type="checking"
    ))


@pytest.fixture
def category(store, portfolio):
    return store.create_category(CategoryCreate(
        portfolio_id=portfolio.id, name="Nebenkosten", category_type="expense"
    ))


# === Portfolio Tests ===

class TestPortfolios:
    def test_create_and_get(self, store):
        p = store.create_portfolio(PortfolioCreate(name="Test"))
        assert p.id
        assert p.name == "Test"
        assert p.currency == "EUR"
        fetched = store.get_portfolio(p.id)
        assert fetched.name == "Test"

    def test_list(self, store):
        store.create_portfolio(PortfolioCreate(name="A"))
        store.create_portfolio(PortfolioCreate(name="B"))
        assert len(store.list_portfolios()) == 2

    def test_update(self, store, portfolio):
        updated = store.update_portfolio(portfolio.id, PortfolioCreate(name="Updated"))
        assert updated.name == "Updated"

    def test_delete(self, store, portfolio):
        store.delete_portfolio(portfolio.id)
        assert len(store.list_portfolios()) == 0

    def test_get_not_found(self, store):
        with pytest.raises(NotFoundError):
            store.get_portfolio("nonexistent")

    def test_patch(self, store, portfolio):
        patched = store._patch_entity("portfolio", portfolio.id, PortfolioPatch(name="Patched"))
        assert patched.name == "Patched"
        assert patched.currency == "EUR"  # unchanged


# === Property Tests ===

class TestProperties:
    def test_create_requires_portfolio(self, store):
        with pytest.raises(ValidationError, match="Portfolio"):
            store.create_property(PropertyCreate(
                portfolio_id="nonexistent", name="X", property_type="residential"
            ))

    def test_crud(self, store, portfolio):
        p = store.create_property(PropertyCreate(
            portfolio_id=portfolio.id, name="Haus", property_type="residential"
        ))
        assert p.name == "Haus"
        assert len(store.list_properties()) == 1
        store.delete_property(p.id)
        assert len(store.list_properties()) == 0


# === Unit Tests ===

class TestUnits:
    def test_create_requires_property(self, store):
        with pytest.raises(ValidationError, match="Immobilie"):
            store.create_unit(UnitCreate(
                property_id="nonexistent", label="X", unit_type="apartment"
            ))

    def test_crud(self, store, property_):
        u = store.create_unit(UnitCreate(
            property_id=property_.id, label="W1", unit_type="apartment"
        ))
        assert u.label == "W1"
        fetched = store.get_unit(u.id)
        assert fetched.label == "W1"
        store.delete_unit(u.id)
        assert len(store.list_units()) == 0


# === Tenant Tests ===

class TestTenants:
    def test_crud(self, store):
        t = store.create_tenant(TenantCreate(full_name="Hans"))
        assert t.full_name == "Hans"
        updated = store.update_tenant(t.id, TenantCreate(full_name="Hans M."))
        assert updated.full_name == "Hans M."
        store.delete_tenant(t.id)
        assert len(store.list_tenants()) == 0


# === Contract Tests ===

class TestContracts:
    def test_create_validates_references(self, store, property_, unit, tenant):
        # Valid
        c = store.create_contract(ContractCreate(
            property_id=property_.id, unit_id=unit.id, tenant_id=tenant.id,
            contract_number="V-001", start_date=date(2024, 1, 1)
        ))
        assert c.contract_number == "V-001"

    def test_duplicate_contract_number(self, store, property_, unit, tenant):
        store.create_contract(ContractCreate(
            property_id=property_.id, unit_id=unit.id, tenant_id=tenant.id,
            contract_number="V-001", start_date=date(2024, 1, 1)
        ))
        with pytest.raises(ValidationError, match="Vertragsnummer"):
            store.create_contract(ContractCreate(
                property_id=property_.id, unit_id=unit.id, tenant_id=tenant.id,
                contract_number="V-001", start_date=date(2024, 6, 1)
            ))

    def test_unit_must_belong_to_property(self, store, portfolio, property_, unit, tenant):
        prop2 = store.create_property(PropertyCreate(
            portfolio_id=portfolio.id, name="Haus B", property_type="commercial"
        ))
        with pytest.raises(ValidationError, match="Einheit gehört nicht"):
            store.create_contract(ContractCreate(
                property_id=prop2.id, unit_id=unit.id, tenant_id=tenant.id,
                contract_number="V-002", start_date=date(2024, 1, 1)
            ))


# === Booking Tests ===

class TestBookings:
    def test_create_validates_account(self, store):
        with pytest.raises(ValidationError, match="Konto"):
            store.create_booking(BookingCreate(
                account_id="nonexistent", booking_date=date(2024, 1, 1), amount=100.0
            ))

    def test_crud(self, store, account):
        b = store.create_booking(BookingCreate(
            account_id=account.id, booking_date=date(2024, 1, 1), amount=500.0
        ))
        assert b.amount == 500.0
        store.delete_booking(b.id)
        assert len(store.list_bookings()) == 0


# === Receivable Tests ===

class TestReceivables:
    def test_crud(self, store, contract):
        r = store.create_receivable(ReceivableCreate(
            contract_id=contract.id, due_date=date(2024, 2, 1), amount_due=800.0
        ))
        assert r.amount_due == 800.0
        store.delete_receivable(r.id)
        assert len(store.list_receivables()) == 0


# === Invoice Tests ===

class TestInvoices:
    def test_crud(self, store, property_):
        inv = store.create_invoice(InvoiceCreate(
            property_id=property_.id, supplier="Handwerker GmbH",
            invoice_date=date(2024, 3, 1), net_amount=1000.0, gross_amount=1190.0
        ))
        assert inv.supplier == "Handwerker GmbH"
        store.delete_invoice(inv.id)
        assert len(store.list_invoices()) == 0


# === Maintenance Tests ===

class TestMaintenance:
    def test_crud(self, store, property_):
        mc = store.create_maintenance_case(MaintenanceCaseCreate(
            property_id=property_.id, title="Rohrbruch"
        ))
        assert mc.title == "Rohrbruch"
        store.delete_maintenance_case(mc.id)
        assert len(store.list_maintenance_cases()) == 0


# === Document Tests ===

class TestDocuments:
    def test_crud(self, store, property_):
        d = store.create_document(DocumentCreate(
            property_id=property_.id, title="Mietvertrag", file_url="/docs/v1.pdf"
        ))
        assert d.title == "Mietvertrag"
        store.delete_document(d.id)
        assert len(store.list_documents()) == 0


# === Task Tests ===

class TestTasks:
    def test_crud(self, store, property_):
        t = store.create_task(TaskCreate(
            title="Rauchmelder prüfen", property_id=property_.id
        ))
        assert t.title == "Rauchmelder prüfen"
        store.delete_task(t.id)
        assert len(store.list_tasks()) == 0


# === Calendar Tests ===

class TestCalendarEvents:
    def test_crud(self, store, property_):
        e = store.create_calendar_event(CalendarEventCreate(
            title="Eigentümerversammlung", event_type="meeting",
            event_date=date(2024, 6, 15), property_id=property_.id
        ))
        assert e.title == "Eigentümerversammlung"
        store.delete_calendar_event(e.id)
        assert len(store.list_calendar_events()) == 0


# === Listing Tests ===

class TestListings:
    def test_crud(self, store, unit):
        listing = store.create_listing(ListingCreate(
            unit_id=unit.id, title="Schöne Wohnung"
        ))
        assert listing.title == "Schöne Wohnung"
        store.delete_listing(listing.id)
        assert len(store.list_listings()) == 0

    def test_photo_crud(self, store, unit):
        listing = store.create_listing(ListingCreate(unit_id=unit.id, title="Test"))
        photo = store.create_listing_photo(ListingPhotoCreate(
            listing_id=listing.id, file_url="/photos/1.jpg"
        ))
        assert photo.file_url == "/photos/1.jpg"
        store.delete_listing_photo(photo.id)
        assert len(store.list_listing_photos()) == 0


# === Lead Tests ===

class TestLeads:
    def test_crud(self, store, unit):
        listing = store.create_listing(ListingCreate(unit_id=unit.id, title="Test"))
        lead = store.create_lead(LeadCreate(
            full_name="Anna S.", listing_id=listing.id, unit_id=unit.id
        ))
        assert lead.full_name == "Anna S."
        store.delete_lead(lead.id)
        assert len(store.list_leads()) == 0

    def test_validates_listing(self, store):
        with pytest.raises(ValidationError, match="Inserat"):
            store.create_lead(LeadCreate(
                full_name="X", listing_id="nonexistent"
            ))


# === Viewing Tests ===

class TestViewings:
    def test_crud(self, store, unit):
        listing = store.create_listing(ListingCreate(unit_id=unit.id, title="Test"))
        lead = store.create_lead(LeadCreate(full_name="Test", listing_id=listing.id))
        va = store.create_viewing_appointment(ViewingAppointmentCreate(
            lead_id=lead.id, unit_id=unit.id,
            scheduled_at=datetime(2024, 6, 15, 10, 0)
        ))
        assert va.status == "scheduled"
        store.delete_viewing_appointment(va.id)
        assert len(store.list_viewing_appointments()) == 0


# === Billing Tests ===

class TestBilling:
    def test_billing_period_crud(self, store, property_):
        bp = store.create_billing_period(BillingPeriodCreate(
            property_id=property_.id, label="2024",
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
        ))
        assert bp.label == "2024"
        store.delete_billing_period(bp.id)
        assert len(store.list_billing_periods()) == 0

    def test_billing_period_date_validation(self, store, property_):
        with pytest.raises(Exception, match="Enddatum"):
            store.create_billing_period(BillingPeriodCreate(
                property_id=property_.id, label="Bad",
                start_date=date(2024, 12, 31), end_date=date(2024, 1, 1)
            ))

    def test_allocation_key_crud(self, store, property_):
        ak = store.create_allocation_key(AllocationKeyCreate(
            property_id=property_.id, name="Fläche", key_type="area_sqm"
        ))
        assert ak.name == "Fläche"
        store.delete_allocation_key(ak.id)
        assert len(store.list_allocation_keys()) == 0

    def test_cost_item_crud(self, store, property_):
        bp = store.create_billing_period(BillingPeriodCreate(
            property_id=property_.id, label="2024",
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
        ))
        ak = store.create_allocation_key(AllocationKeyCreate(
            property_id=property_.id, name="Fläche", key_type="area_sqm"
        ))
        ci = store.create_cost_item(CostItemCreate(
            billing_period_id=bp.id, allocation_key_id=ak.id,
            description="Wasser", amount=1200.0
        ))
        assert ci.description == "Wasser"
        store.delete_cost_item(ci.id)
        assert len(store.list_cost_items()) == 0

    def test_utility_statement_crud(self, store, property_, unit, contract):
        bp = store.create_billing_period(BillingPeriodCreate(
            property_id=property_.id, label="2024",
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
        ))
        us = store.create_utility_statement(UtilityStatementCreate(
            billing_period_id=bp.id, contract_id=contract.id, unit_id=unit.id,
            total_cost=3600.0, advance_paid=2400.0, balance=-1200.0
        ))
        assert us.total_cost == 3600.0
        store.delete_utility_statement(us.id)
        assert len(store.list_utility_statements()) == 0


# === Deposit Tests ===

class TestDeposits:
    def test_crud(self, store, contract):
        dep = store.create_deposit(DepositCreate(
            contract_id=contract.id, amount=2400.0
        ))
        assert dep.amount == 2400.0
        assert dep.status == "held"
        store.delete_deposit(dep.id)
        assert len(store.list_deposits()) == 0

    def test_validates_contract(self, store):
        with pytest.raises(ValidationError, match="Vertrag"):
            store.create_deposit(DepositCreate(
                contract_id="nonexistent", amount=1000.0
            ))


# === Notification Tests ===

class TestNotifications:
    def test_crud(self, store):
        n = store.create_notification(NotificationCreate(
            notification_type="overdue_payment",
            title="Zahlung überfällig",
            content="Miete Wohnung 1 ist überfällig"
        ))
        assert n.status == "unread"
        store.delete_notification(n.id)
        assert len(store.list_notifications()) == 0

    def test_mark_read(self, store):
        n = store.create_notification(NotificationCreate(
            notification_type="test", title="Test", content="test"
        ))
        read_n = store.mark_notification_read(n.id)
        assert read_n.status == "read"
        assert read_n.read_at is not None

    def test_template_crud(self, store):
        t = store.create_notification_template(NotificationTemplateCreate(
            name="Mahnung", notification_type="overdue_payment",
            title_template="Zahlung überfällig: {contract}",
            content_template="Die Miete für {unit} ist seit {days} Tagen überfällig."
        ))
        assert t.name == "Mahnung"
        store.delete_notification_template(t.id)
        assert len(store.list_notification_templates()) == 0


# === Meter Reading and Change History Tests ===

class TestMeterReadingsAndChangeHistory:
    def test_update_meter_reading(self, store, contract, unit):
        protocol = store.create_handover_protocol(HandoverProtocolCreate(
            contract_id=contract.id,
            unit_id=unit.id,
            protocol_type="move_in",
            protocol_date=date(2024, 1, 10),
        ))
        reading = store.create_meter_reading(MeterReadingCreate(
            handover_id=protocol.id,
            meter_type="water",
            meter_number="W-100",
            reading_value=123.4,
            unit="m3",
        ))

        updated = store.update_meter_reading(reading.id, MeterReadingCreate(
            handover_id=protocol.id,
            meter_type="water",
            meter_number="W-100",
            reading_value=130.0,
            unit="m3",
        ))

        assert updated.reading_value == 130.0

    def test_add_and_filter_change_history(self, store):
        entry = store.add_change_history(
            entity_type="contract",
            entity_id="contract-1",
            field_name="status",
            old_value="active",
            new_value="terminated",
            changed_by="user-1",
            reason="Kündigung",
        )

        assert entry.id
        assert entry.reason == "Kündigung"

        all_entries = store.list_change_history()
        assert len(all_entries) == 1

        filtered = store.get_entity_history("contract", "contract-1")
        assert len(filtered) == 1
        assert filtered[0].field_name == "status"



# === Cascade Tests ===

class TestCascades:
    def test_delete_portfolio_cascades_to_properties(self, store, portfolio, property_):
        store.delete_portfolio(portfolio.id)
        assert len(store.list_properties()) == 0

    def test_delete_property_cascades_to_units(self, store, property_, unit):
        store.delete_property(property_.id)
        assert len(store.list_units()) == 0

    def test_delete_listing_cascades_to_photos(self, store, unit):
        listing = store.create_listing(ListingCreate(unit_id=unit.id, title="X"))
        store.create_listing_photo(ListingPhotoCreate(
            listing_id=listing.id, file_url="/p.jpg"
        ))
        store.delete_listing(listing.id)
        assert len(store.list_listing_photos()) == 0

    def test_delete_lead_cascades_to_viewings(self, store, unit):
        listing = store.create_listing(ListingCreate(unit_id=unit.id, title="X"))
        lead = store.create_lead(LeadCreate(full_name="Test", listing_id=listing.id))
        store.create_viewing_appointment(ViewingAppointmentCreate(
            lead_id=lead.id, unit_id=unit.id,
            scheduled_at=datetime(2024, 6, 15, 10, 0)
        ))
        store.delete_lead(lead.id)
        assert len(store.list_viewing_appointments()) == 0

    def test_delete_billing_period_cascades(self, store, property_, unit, contract):
        bp = store.create_billing_period(BillingPeriodCreate(
            property_id=property_.id, label="2024",
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
        ))
        ak = store.create_allocation_key(AllocationKeyCreate(
            property_id=property_.id, name="Fläche", key_type="area_sqm"
        ))
        store.create_cost_item(CostItemCreate(
            billing_period_id=bp.id, allocation_key_id=ak.id,
            description="Wasser", amount=1000.0
        ))
        store.create_utility_statement(UtilityStatementCreate(
            billing_period_id=bp.id, contract_id=contract.id, unit_id=unit.id,
            total_cost=1000.0, advance_paid=800.0, balance=-200.0
        ))
        store.delete_billing_period(bp.id)
        assert len(store.list_cost_items()) == 0
        assert len(store.list_utility_statements()) == 0
