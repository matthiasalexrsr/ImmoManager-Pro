"""Tests for Phase 6 advanced features: CSV export, DATEV, bank import, recurring tasks."""

import pytest
from datetime import date

from backend.dependencies import store
from backend.models import (
    AccountCreate,
    BookingCreate,
    CategoryCreate,
    ContractCreate,
    MaintenanceCaseCreate,
    PortfolioCreate,
    PropertyCreate,
    TaskCreate,
    TenantCreate,
    UnitCreate,
)
from backend.routers.reports import (
    _csv_response,
    datev_export,
    get_cashflow_report,
    get_finance_report,
    get_maintenance_costs_report,
    get_occupancy_report,
    get_receivables_aging,
    get_summary,
    import_bookings,
)
from backend.routers.tasks import (
    _next_due_date,
    _parse_rrule,
    generate_recurring_tasks,
)

from fastapi.responses import StreamingResponse


def _clear_store():
    for collection in (
        store.portfolios, store.properties, store.units, store.tenants,
        store.contracts, store.accounts, store.bookings, store.receivables,
        store.invoices, store.maintenance_cases, store.categories,
        store.documents, store.tasks, store.calendar_events,
        store.listings, store.listing_photos, store.leads,
        store.viewing_appointments, store.billing_periods,
        store.allocation_keys, store.cost_items, store.utility_statements,
        store.deposits, store.notifications, store.notification_templates,
    ):
        collection.clear()


@pytest.fixture(autouse=True)
def _clear():
    _clear_store()
    yield
    _clear_store()


@pytest.fixture
def _setup_data():
    """Create common test data."""
    pf = store.create_portfolio(PortfolioCreate(name="Test"))
    prop = store.create_property(PropertyCreate(
        portfolio_id=pf.id, name="Haus", property_type="residential"
    ))
    unit = store.create_unit(UnitCreate(
        property_id=prop.id, label="W1", unit_type="apartment", status="rented"
    ))
    tenant = store.create_tenant(TenantCreate(full_name="Max"))
    contract = store.create_contract(ContractCreate(
        property_id=prop.id, unit_id=unit.id, tenant_id=tenant.id,
        contract_number="V-001", start_date=date(2024, 1, 1),
    ))
    account = store.create_account(AccountCreate(
        portfolio_id=pf.id, name="Mietkonto", account_type="checking"
    ))
    category = store.create_category(CategoryCreate(
        portfolio_id=pf.id, name="Nebenkosten", category_type="expense"
    ))
    return pf, prop, unit, tenant, contract, account, category


# === CSV Export Tests ===

class TestCSVExport:
    def test_summary_csv(self, _setup_data):
        result = get_summary(format="csv")
        assert isinstance(result, StreamingResponse)
        assert "zusammenfassung.csv" in result.headers["content-disposition"]

    def test_summary_json(self, _setup_data):
        result = get_summary(format=None)
        assert isinstance(result, dict)
        assert "totals" in result

    def test_finance_csv(self, _setup_data):
        pf, prop, unit, tenant, contract, account, category = _setup_data
        store.create_booking(BookingCreate(
            account_id=account.id, booking_date=date(2024, 1, 1),
            amount=800.0, category_id=category.id
        ))
        result = get_finance_report(format="csv")
        assert isinstance(result, StreamingResponse)

    def test_occupancy_csv(self, _setup_data):
        result = get_occupancy_report(format="csv")
        assert isinstance(result, StreamingResponse)
        assert "belegungsquote.csv" in result.headers["content-disposition"]

    def test_receivables_aging_csv(self, _setup_data):
        result = get_receivables_aging(format="csv")
        assert isinstance(result, StreamingResponse)

    def test_cashflow_csv(self, _setup_data):
        result = get_cashflow_report(format="csv")
        assert isinstance(result, StreamingResponse)
        assert "cashflow.csv" in result.headers["content-disposition"]

    def test_maintenance_costs_csv(self, _setup_data):
        pf, prop, *_ = _setup_data
        store.create_maintenance_case(MaintenanceCaseCreate(
            property_id=prop.id, title="Fix", category="Elektrik", estimated_cost=500.0
        ))
        result = get_maintenance_costs_report(format="csv")
        assert isinstance(result, StreamingResponse)

    def test_csv_response_empty(self):
        result = _csv_response([], "test.csv")
        assert isinstance(result, StreamingResponse)


# === DATEV Export Tests ===

class TestDATEVExport:
    def test_datev_export_basic(self, _setup_data):
        pf, prop, unit, tenant, contract, account, category = _setup_data
        store.create_booking(BookingCreate(
            account_id=account.id, booking_date=date(2024, 3, 15),
            amount=800.0, payment_text="Miete März",
            category_id=category.id
        ))
        store.create_booking(BookingCreate(
            account_id=account.id, booking_date=date(2024, 3, 20),
            amount=-150.0, payment_text="Reparatur"
        ))
        result = datev_export(start_date=None, end_date=None)
        assert isinstance(result, StreamingResponse)
        assert "EXTF_Buchungsstapel.csv" in result.headers["content-disposition"]

    def test_datev_export_date_filter(self, _setup_data):
        pf, prop, unit, tenant, contract, account, category = _setup_data
        store.create_booking(BookingCreate(
            account_id=account.id, booking_date=date(2024, 1, 15), amount=100.0
        ))
        store.create_booking(BookingCreate(
            account_id=account.id, booking_date=date(2024, 6, 15), amount=200.0
        ))
        result = datev_export(
            start_date=date(2024, 6, 1),
            end_date=date(2024, 6, 30),
        )
        assert isinstance(result, StreamingResponse)

    def test_datev_export_empty(self):
        result = datev_export(start_date=None, end_date=None)
        assert isinstance(result, StreamingResponse)


# === Bank Import Tests ===

class TestBankImport:
    def test_import_bookings(self, _setup_data):
        pf, prop, unit, tenant, contract, account, category = _setup_data
        csv_data = "date;amount;text\n2024-01-15;-500.00;Handwerker\n2024-01-20;800.00;Miete"
        result = import_bookings(account_id=account.id, csv_content=csv_data)
        assert result["imported"] == 2
        assert result["errors"] == 0
        assert len(store.list_bookings()) == 2

    def test_import_with_errors(self, _setup_data):
        pf, prop, unit, tenant, contract, account, category = _setup_data
        csv_data = "date;amount;text\ninvalid;abc;Bad row\n2024-01-20;800.00;Good row"
        result = import_bookings(account_id=account.id, csv_content=csv_data)
        assert result["imported"] == 1
        assert result["errors"] == 1

    def test_import_german_decimals(self, _setup_data):
        pf, prop, unit, tenant, contract, account, category = _setup_data
        csv_data = "date;amount;text\n2024-03-01;1500,50;Miete"
        result = import_bookings(account_id=account.id, csv_content=csv_data)
        assert result["imported"] == 1
        booking = store.list_bookings()[0]
        assert booking.amount == 1500.50


# === Recurring Tasks Tests ===

class TestRecurringTasks:
    def test_parse_rrule(self):
        rule = _parse_rrule("FREQ=MONTHLY;INTERVAL=1")
        assert rule["FREQ"] == "MONTHLY"
        assert rule["INTERVAL"] == "1"

    def test_next_due_date_daily(self):
        d = _next_due_date(date(2024, 1, 15), {"FREQ": "DAILY", "INTERVAL": "3"})
        assert d == date(2024, 1, 18)

    def test_next_due_date_weekly(self):
        d = _next_due_date(date(2024, 1, 15), {"FREQ": "WEEKLY", "INTERVAL": "2"})
        assert d == date(2024, 1, 29)

    def test_next_due_date_monthly(self):
        d = _next_due_date(date(2024, 1, 15), {"FREQ": "MONTHLY", "INTERVAL": "1"})
        assert d == date(2024, 2, 15)

    def test_next_due_date_yearly(self):
        d = _next_due_date(date(2024, 3, 15), {"FREQ": "YEARLY", "INTERVAL": "1"})
        assert d == date(2025, 3, 15)

    def test_generate_recurring_task(self):
        store.create_task(TaskCreate(
            title="Rauchmelder prüfen",
            due_date=date(2024, 1, 1),
            recurrence_rule="FREQ=MONTHLY;INTERVAL=1",
        ))
        created = generate_recurring_tasks(as_of=date(2024, 2, 15))
        assert len(created) == 1
        assert created[0].title == "Rauchmelder prüfen"
        assert created[0].due_date == date(2024, 2, 1)

    def test_no_duplicate_recurring(self):
        store.create_task(TaskCreate(
            title="Test", due_date=date(2024, 1, 1),
            recurrence_rule="FREQ=MONTHLY;INTERVAL=1",
        ))
        # Generate first instance
        created = generate_recurring_tasks(as_of=date(2024, 2, 15))
        assert len(created) == 1
        # Should not generate another while first is open
        created2 = generate_recurring_tasks(as_of=date(2024, 3, 15))
        assert len(created2) == 0

    def test_generate_after_completion(self):
        store.create_task(TaskCreate(
            title="Test", due_date=date(2024, 1, 1),
            recurrence_rule="FREQ=MONTHLY;INTERVAL=1",
        ))
        # Generate and complete first instance
        created = generate_recurring_tasks(as_of=date(2024, 2, 15))
        store._patch_entity(store.tasks, created[0].id, type("P", (), {"model_dump": lambda self, **kw: {"status": "completed"}})(), "Aufgabe nicht gefunden")
        # Now it should generate the next one
        created2 = generate_recurring_tasks(as_of=date(2024, 3, 15))
        assert len(created2) == 1

    def test_count_limit(self):
        store.create_task(TaskCreate(
            title="Test", due_date=date(2024, 1, 1),
            recurrence_rule="FREQ=MONTHLY;INTERVAL=1;COUNT=1",
        ))
        created = generate_recurring_tasks(as_of=date(2024, 2, 15))
        assert len(created) == 1
        # Complete the child
        from backend.models import TaskPatch
        store._patch_entity(store.tasks, created[0].id, TaskPatch(status="completed"), "Aufgabe nicht gefunden")
        # COUNT=1 means only 1 child, so no more
        created2 = generate_recurring_tasks(as_of=date(2024, 3, 15))
        assert len(created2) == 0

    def test_until_limit(self):
        store.create_task(TaskCreate(
            title="Test", due_date=date(2024, 6, 1),
            recurrence_rule="FREQ=MONTHLY;INTERVAL=1;UNTIL=2024-06-15",
        ))
        # Next due = 2024-07-01 which is > UNTIL 2024-06-15
        created = generate_recurring_tasks(as_of=date(2024, 7, 15))
        assert len(created) == 0
