"""Tests for Phase 6 advanced features: CSV export, DATEV, bank import, recurring tasks."""

from datetime import date

import pytest
from fastapi.responses import Response

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


def _clear_store():
    store.clear_all()


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
        property_id=prop.id, label="W1", unit_type="apartment", status="occupied"
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
        assert isinstance(result, Response)
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
        assert isinstance(result, Response)

    def test_occupancy_csv(self, _setup_data):
        result = get_occupancy_report(format="csv")
        assert isinstance(result, Response)
        assert "belegungsquote.csv" in result.headers["content-disposition"]

    def test_receivables_aging_csv(self, _setup_data):
        result = get_receivables_aging(format="csv")
        assert isinstance(result, Response)

    def test_cashflow_csv(self, _setup_data):
        result = get_cashflow_report(format="csv")
        assert isinstance(result, Response)
        assert "cashflow.csv" in result.headers["content-disposition"]

    def test_maintenance_costs_csv(self, _setup_data):
        pf, prop, *_ = _setup_data
        store.create_maintenance_case(MaintenanceCaseCreate(
            property_id=prop.id, title="Fix", category="Elektrik", estimated_cost=500.0
        ))
        result = get_maintenance_costs_report(format="csv")
        assert isinstance(result, Response)

    def test_csv_response_empty(self):
        result = _csv_response([], "test.csv")
        assert isinstance(result, Response)


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
        assert isinstance(result, Response)
        assert "Buchungen_neutral.csv" in result.headers["content-disposition"]
        assert "EXTF" not in result.headers["content-disposition"]

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
        assert isinstance(result, Response)

    def test_datev_export_empty(self):
        result = datev_export(start_date=None, end_date=None)
        assert isinstance(result, Response)


# === Bank Import Tests ===

class TestBankImport:
    @pytest.fixture(autouse=True)
    def isolated_legacy_adapter(self, monkeypatch):
        # Exercise the compatibility adapter in an isolated installation. The
        # native bank package has separate memory/SQL concurrency matrices.
        from backend import auth
        from backend.routers import reports
        from backend.services.bank_imports import BankImports
        from backend.storage import InMemoryStore
        self.store = InMemoryStore()
        monkeypatch.setattr(reports, 'store', self.store)
        monkeypatch.setattr(auth, '_user_store', auth.InMemoryUserStore())
        self.actor = auth.register_user('legacy-bank', 'bank@example.test', 'Bank', 'Secret123', 'eigentuemer')
        portfolio = self.store.create_portfolio(PortfolioCreate(name='Bankbestand'))
        self.account = self.store.create_account(AccountCreate(portfolio_id=portfolio.id, name='Konto', account_type='bank'))
        self.bank = BankImports(self.store)

    def confirm(self, preview):
        from uuid import uuid4

        from backend.services.bank_imports import ConfirmImport
        return self.bank.confirm(preview['id'], ConfirmImport(idempotency_key=str(uuid4()), confirm=True,
            base_revision=preview['revision'], preview_sha256=preview['preview_sha256']), self.actor.id)

    def test_import_bookings(self):
        csv_data = "date;amount;text\n2024-01-15;-500.00;Handwerker\n2024-01-20;800.00;Miete"
        result = import_bookings(account_id=self.account.id, csv_content=csv_data, user=self.actor)
        assert result["imported"] == 0 and result['requires_confirmation']
        assert result["errors"] == 0
        assert self.store.list_bookings() == []
        self.confirm(result['preview'])
        assert sorted(row.amount for row in self.store.list_bookings()) == [-500, 800]
        assert self.bank.original(result['preview']['id'], self.actor.id) == csv_data.encode()

    def test_import_with_errors(self):
        from fastapi import HTTPException
        csv_data = "date;amount;text\ninvalid;abc;Bad row\n2024-01-20;800.00;Good row"
        result = import_bookings(account_id=self.account.id, csv_content=csv_data, user=self.actor)
        assert result["imported"] == 0
        assert result["errors"] == 1
        with pytest.raises(HTTPException) as refused:
            self.confirm(result['preview'])
        assert refused.value.status_code == 409
        assert self.store.list_bookings() == []

    def test_import_german_decimals(self):
        import base64
        from uuid import uuid4

        from backend.services.bank_imports import StageImport
        csv_data = "date;amount;text\n2024-03-01;1500,50;Miete"
        result = import_bookings(account_id=self.account.id, csv_content=csv_data, user=self.actor)
        assert result['errors'] == 1 and self.store.list_bookings() == []
        # Locale guessing must never silently change a bank amount. Confirm
        # the explicit German format and retain the original source bytes.
        preview = self.bank.stage(StageImport(idempotency_key=str(uuid4()), account_id=self.account.id,
            filename='Deutsch.csv', source_base64=base64.b64encode(csv_data.encode()).decode(), format='csv',
            options={'decimal': ','}), self.actor.id)
        self.confirm(preview)
        booking = self.store.list_bookings()[0]
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
        store._patch_entity(
            "task", created[0].id,
            type("P", (), {"model_dump": lambda self, **kw: {"status": "completed"}})(),
        )
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
        store._patch_entity("task", created[0].id, TaskPatch(status="completed"))
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
