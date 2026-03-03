import datetime

from backend.dependencies import store
from backend.models import (
    AccountCreate,
    BookingCreate,
    CategoryCreate,
    ContractCreate,
    InvoiceCreate,
    MaintenanceCaseCreate,
    PortfolioCreate,
    PropertyCreate,
    ReceivableCreate,
    TenantCreate,
    UnitCreate,
)
from backend.routers import reports


def test_reports_summary_counts() -> None:
    store.portfolios.clear()
    store.properties.clear()
    store.units.clear()
    store.contracts.clear()
    store.bookings.clear()
    store.receivables.clear()
    store.invoices.clear()
    store.maintenance_cases.clear()
    store.accounts.clear()
    store.tenants.clear()

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
            label="1.1",
            unit_type="Wohnung",
        )
    )
    tenant = store.create_tenant(TenantCreate(full_name="Test Tenant"))
    store.create_contract(
        ContractCreate(
            contract_number="C-300",
            property_id=property_item.id,
            unit_id=unit.id,
            tenant_id=tenant.id,
            start_date=datetime.date(2024, 1, 1),
        )
    )
    account = store.create_account(
        AccountCreate(
            portfolio_id=portfolio.id,
            name="Konto",
            account_type="Bankkonto",
        )
    )
    store.create_booking(
        BookingCreate(
            account_id=account.id,
            booking_date=datetime.date(2024, 4, 1),
            amount=1000.0,
        )
    )
    store.create_receivable(
        ReceivableCreate(
            contract_id=next(iter(store.contracts)),
            due_date=datetime.date(2024, 5, 1),
            amount_due=500.0,
            status="open",
        )
    )
    store.create_invoice(
        InvoiceCreate(
            supplier="Dienstleister",
            invoice_date=datetime.date(2024, 4, 15),
            net_amount=200.0,
            gross_amount=238.0,
        )
    )
    store.create_maintenance_case(
        MaintenanceCaseCreate(
            property_id=property_item.id,
            title="Reparatur",
            status="open",
        )
    )

    summary = reports.get_summary()

    assert summary["totals"]["properties"] == 1
    assert summary["totals"]["units"] == 1
    assert summary["totals"]["contracts"] == 1
    assert summary["finance"]["bookingsTotal"] == 1000.0
    assert summary["finance"]["invoicesTotal"] == 238.0
    assert summary["finance"]["openReceivables"] == 500.0
    assert summary["maintenance"]["openCases"] == 1


def test_reports_finance_groups_by_category() -> None:
    store.portfolios.clear()
    store.properties.clear()
    store.units.clear()
    store.contracts.clear()
    store.bookings.clear()
    store.receivables.clear()
    store.invoices.clear()
    store.maintenance_cases.clear()
    store.accounts.clear()
    store.tenants.clear()
    store.categories.clear()

    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))
    account = store.create_account(
        AccountCreate(
            portfolio_id=portfolio.id,
            name="Konto",
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
    store.create_booking(
        BookingCreate(
            account_id=account.id,
            category_id=category.id,
            booking_date=datetime.date(2024, 2, 1),
            amount=1500.0,
        )
    )
    store.create_booking(
        BookingCreate(
            account_id=account.id,
            booking_date=datetime.date(2024, 2, 5),
            amount=200.0,
        )
    )

    report = reports.get_finance_report()

    assert report["bookingsTotal"] == 1700.0
    assert report["uncategorizedTotal"] == 200.0
    assert report["totalsByCategory"][0]["total"] == 1500.0


def test_reports_occupancy() -> None:
    store.portfolios.clear()
    store.properties.clear()
    store.units.clear()
    store.contracts.clear()
    store.bookings.clear()
    store.receivables.clear()
    store.invoices.clear()
    store.maintenance_cases.clear()
    store.accounts.clear()
    store.tenants.clear()
    store.categories.clear()

    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))
    property_item = store.create_property(
        PropertyCreate(
            portfolio_id=portfolio.id,
            name="Objekt",
            property_type="Wohnung",
        )
    )
    store.create_unit(
        UnitCreate(
            property_id=property_item.id,
            label="1.1",
            unit_type="Wohnung",
            status="rented",
        )
    )
    store.create_unit(
        UnitCreate(
            property_id=property_item.id,
            label="1.2",
            unit_type="Wohnung",
            status="vacant",
        )
    )

    report = reports.get_occupancy_report()

    assert report["totalUnits"] == 2
    assert report["rentedUnits"] == 1
    assert report["occupancyRate"] == 0.5


def test_reports_receivables_aging() -> None:
    store.portfolios.clear()
    store.properties.clear()
    store.units.clear()
    store.contracts.clear()
    store.bookings.clear()
    store.receivables.clear()
    store.invoices.clear()
    store.maintenance_cases.clear()
    store.accounts.clear()
    store.tenants.clear()
    store.categories.clear()

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
    tenant = store.create_tenant(TenantCreate(full_name="Mieter"))
    contract = store.create_contract(
        ContractCreate(
            contract_number="C-400",
            property_id=property_item.id,
            unit_id=unit.id,
            tenant_id=tenant.id,
            start_date=datetime.date(2024, 1, 1),
        )
    )

    today = datetime.date.today()
    store.create_receivable(
        ReceivableCreate(
            contract_id=contract.id,
            due_date=today,
            amount_due=100.0,
            status="open",
        )
    )
    store.create_receivable(
        ReceivableCreate(
            contract_id=contract.id,
            due_date=today - datetime.timedelta(days=15),
            amount_due=200.0,
            status="overdue",
        )
    )
    store.create_receivable(
        ReceivableCreate(
            contract_id=contract.id,
            due_date=today - datetime.timedelta(days=45),
            amount_due=300.0,
            status="overdue",
        )
    )
    store.create_receivable(
        ReceivableCreate(
            contract_id=contract.id,
            due_date=today - datetime.timedelta(days=75),
            amount_due=400.0,
            status="overdue",
        )
    )
    store.create_receivable(
        ReceivableCreate(
            contract_id=contract.id,
            due_date=today - datetime.timedelta(days=120),
            amount_due=500.0,
            status="overdue",
        )
    )

    report = reports.get_receivables_aging()

    assert report["openTotal"] == 1500.0
    assert report["buckets"]["current"] == 100.0
    assert report["buckets"]["days1to30"] == 200.0
    assert report["buckets"]["days31to60"] == 300.0
    assert report["buckets"]["days61to90"] == 400.0
    assert report["buckets"]["days90plus"] == 500.0


def test_reports_cashflow() -> None:
    store.portfolios.clear()
    store.properties.clear()
    store.units.clear()
    store.contracts.clear()
    store.bookings.clear()
    store.receivables.clear()
    store.invoices.clear()
    store.maintenance_cases.clear()
    store.accounts.clear()
    store.tenants.clear()
    store.categories.clear()

    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))
    account = store.create_account(
        AccountCreate(
            portfolio_id=portfolio.id,
            name="Konto",
            account_type="Bankkonto",
        )
    )
    store.create_booking(
        BookingCreate(
            account_id=account.id,
            booking_date=datetime.date(2024, 3, 1),
            amount=2000.0,
        )
    )
    store.create_booking(
        BookingCreate(
            account_id=account.id,
            booking_date=datetime.date(2024, 3, 2),
            amount=-750.0,
        )
    )

    report = reports.get_cashflow_report()

    assert report["incomeTotal"] == 2000.0
    assert report["expenseTotal"] == 750.0
    assert report["netTotal"] == 1250.0


def test_reports_contracts_expiring() -> None:
    store.portfolios.clear()
    store.properties.clear()
    store.units.clear()
    store.contracts.clear()
    store.bookings.clear()
    store.receivables.clear()
    store.invoices.clear()
    store.maintenance_cases.clear()
    store.accounts.clear()
    store.tenants.clear()
    store.categories.clear()

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
            label="5.1",
            unit_type="Wohnung",
        )
    )
    tenant = store.create_tenant(TenantCreate(full_name="Mieter A"))

    today = datetime.date.today()
    store.create_contract(
        ContractCreate(
            contract_number="C-500",
            property_id=property_item.id,
            unit_id=unit.id,
            tenant_id=tenant.id,
            start_date=today - datetime.timedelta(days=365),
            end_date=today + datetime.timedelta(days=30),
        )
    )
    store.create_contract(
        ContractCreate(
            contract_number="C-501",
            property_id=property_item.id,
            unit_id=unit.id,
            tenant_id=tenant.id,
            start_date=today - datetime.timedelta(days=400),
            end_date=today + datetime.timedelta(days=150),
        )
    )

    report = reports.get_contracts_expiring_report(days=90)

    assert report["windowDays"] == 90
    assert report["count"] == 1
    assert report["contracts"][0]["contractNumber"] == "C-500"


def test_reports_maintenance_costs() -> None:
    store.portfolios.clear()
    store.properties.clear()
    store.units.clear()
    store.contracts.clear()
    store.bookings.clear()
    store.receivables.clear()
    store.invoices.clear()
    store.maintenance_cases.clear()
    store.accounts.clear()
    store.tenants.clear()
    store.categories.clear()

    portfolio = store.create_portfolio(PortfolioCreate(name="Portfolio"))
    property_item = store.create_property(
        PropertyCreate(
            portfolio_id=portfolio.id,
            name="Objekt",
            property_type="Wohnung",
        )
    )

    store.create_maintenance_case(
        MaintenanceCaseCreate(
            property_id=property_item.id,
            title="Heizung",
            category="Heizung",
            status="open",
            estimated_cost=350.0,
        )
    )
    store.create_maintenance_case(
        MaintenanceCaseCreate(
            property_id=property_item.id,
            title="Elektrik",
            category="Elektrik",
            status="in_progress",
            estimated_cost=150.0,
        )
    )
    store.create_maintenance_case(
        MaintenanceCaseCreate(
            property_id=property_item.id,
            title="Sonstiges",
            status="done",
            estimated_cost=50.0,
        )
    )

    report = reports.get_maintenance_costs_report()

    assert report["openCases"] == 2
    assert report["totalEstimatedCost"] == 550.0
    assert {item["category"] for item in report["categories"]} == {"Elektrik", "Heizung", "Unkategorisiert"}
