import datetime
from decimal import Decimal

from backend.models import (
    AccountCreate,
    BookingCreate,
    ContractCreate,
    InvoiceCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)
from backend.routers import contracts, invoices
from backend.dependencies import store


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


def _seed_contract_with_payments() -> tuple:
    """Create a portfolio, property, unit, tenant, contract, account, and bookings."""
    portfolio = store.create_portfolio(PortfolioCreate(name="Test-Portfolio"))
    prop = store.create_property(
        PropertyCreate(
            portfolio_id=portfolio.id,
            name="Testhaus",
            property_type="Mehrfamilienhaus",
        )
    )
    unit = store.create_unit(
        UnitCreate(
            property_id=prop.id,
            label="EG links",
            unit_type="Wohnung",
            cold_rent=800.0,
            service_charge_advance=150.0,
            heating_advance=50.0,
        )
    )
    tenant = store.create_tenant(TenantCreate(full_name="Max Mustermann"))
    contract = store.create_contract(
        ContractCreate(
            contract_number="V-001",
            property_id=prop.id,
            unit_id=unit.id,
            tenant_id=tenant.id,
            start_date=datetime.date(2025, 1, 1),
            end_date=datetime.date(2025, 6, 30),
        )
    )
    account = store.create_account(
        AccountCreate(
            portfolio_id=portfolio.id,
            name="Mietkonto",
            account_type="Bankkonto",
        )
    )
    # Tenant pays Jan + Feb fully (1000 each = 800 + 150 + 50)
    store.create_booking(
        BookingCreate(
            account_id=account.id,
            tenant_id=tenant.id,
            booking_date=datetime.date(2025, 1, 5),
            amount=1000.0,
        )
    )
    store.create_booking(
        BookingCreate(
            account_id=account.id,
            tenant_id=tenant.id,
            booking_date=datetime.date(2025, 2, 5),
            amount=1000.0,
        )
    )
    return portfolio, prop, unit, tenant, contract, account


# --- Settlement endpoint tests ---


def test_settlement_returns_dashboard() -> None:
    _clear_store()
    _, _, _, _, contract, _ = _seed_contract_with_payments()

    result = contracts.get_contract_settlement(
        contract_id=contract.id,
        as_of=datetime.date(2025, 3, 15),
    )

    assert "summary" in result
    assert "balance" in result
    assert "aging" in result
    assert "receivables" in result
    assert "settlement_lines" in result

    # 3 months of receivables (Jan, Feb, Mar) since as_of is Mar 15
    assert len(result["receivables"]) == 3

    summary = result["summary"]
    # 2 paid, 1 overdue (Mar is past due_day=3 but we're at Mar 15)
    assert summary["paid_receivables"] == 2
    assert summary["total_receivables"] == 3


def test_settlement_balance_reflects_payments() -> None:
    _clear_store()
    _, _, _, _, contract, _ = _seed_contract_with_payments()

    result = contracts.get_contract_settlement(
        contract_id=contract.id,
        as_of=datetime.date(2025, 3, 15),
    )

    balance = result["balance"]
    # 3 months * 1000 = 3000 expected, 2000 paid
    assert balance["expected_total"] == 3000.0
    assert balance["paid_total"] == 2000.0
    assert balance["outstanding_total"] == 1000.0
    assert balance["overpaid_total"] == 0.0


def test_settlement_not_found() -> None:
    _clear_store()
    try:
        contracts.get_contract_settlement(contract_id="nonexistent")
        assert False, "Should have raised HTTPException"
    except Exception as exc:
        assert "404" in str(exc.status_code)


def test_settlement_no_payments() -> None:
    """Settlement with no payments should show all receivables as outstanding."""
    _clear_store()
    portfolio = store.create_portfolio(PortfolioCreate(name="P"))
    prop = store.create_property(
        PropertyCreate(portfolio_id=portfolio.id, name="H", property_type="MFH")
    )
    unit = store.create_unit(
        UnitCreate(
            property_id=prop.id,
            label="1",
            unit_type="Wohnung",
            cold_rent=500.0,
        )
    )
    tenant = store.create_tenant(TenantCreate(full_name="Leer"))
    contract = store.create_contract(
        ContractCreate(
            contract_number="V-002",
            property_id=prop.id,
            unit_id=unit.id,
            tenant_id=tenant.id,
            start_date=datetime.date(2025, 1, 1),
        )
    )

    result = contracts.get_contract_settlement(
        contract_id=contract.id,
        as_of=datetime.date(2025, 2, 15),
    )

    assert result["balance"]["paid_total"] == 0.0
    assert result["balance"]["outstanding_total"] == 1000.0  # 2 * 500
    assert result["summary"]["overdue_receivables"] == 2


# --- Dunning campaign endpoint tests ---


def test_dunning_campaign_generates_notices() -> None:
    _clear_store()
    _, _, _, _, contract, _ = _seed_contract_with_payments()

    # As of April 15, March is unpaid and overdue by 42 days
    result = contracts.create_dunning_campaign(
        contract_id=contract.id,
        as_of=datetime.date(2025, 4, 15),
    )

    assert "lines" in result
    assert "total_cases" in result
    assert "total_principal" in result
    assert "total_fees" in result
    assert "total_claim" in result

    # Should have dunning notices for overdue months (Mar + Apr)
    assert result["total_cases"] > 0
    assert result["total_principal"] > 0


def test_dunning_campaign_with_custom_policy() -> None:
    _clear_store()
    _, _, _, _, contract, _ = _seed_contract_with_payments()

    policy = contracts.DunningPolicyRequest(
        level_1_after_days=5,
        level_2_after_days=20,
        level_3_after_days=40,
        fee_level_1=3.00,
        fee_level_2=6.00,
        fee_level_3=10.00,
    )

    result = contracts.create_dunning_campaign(
        contract_id=contract.id,
        policy=policy,
        as_of=datetime.date(2025, 4, 15),
    )

    assert result["total_cases"] > 0
    # Fees should reflect the custom policy
    for line in result["lines"]:
        assert line["dunning_fee"] in [3.0, 6.0, 10.0]


def test_dunning_campaign_no_overdue() -> None:
    _clear_store()
    _, _, _, _, contract, _ = _seed_contract_with_payments()

    # As of Jan 2 (before due_day=3), nothing is overdue yet
    result = contracts.create_dunning_campaign(
        contract_id=contract.id,
        as_of=datetime.date(2025, 1, 2),
    )

    assert result["total_cases"] == 0
    assert result["total_principal"] == 0.0


def test_dunning_campaign_not_found() -> None:
    _clear_store()
    try:
        contracts.create_dunning_campaign(contract_id="nonexistent")
        assert False, "Should have raised HTTPException"
    except Exception as exc:
        assert "404" in str(exc.status_code)


# --- Invoice matching endpoint tests ---


def test_invoice_match_allocates_to_open_bookings() -> None:
    _clear_store()
    portfolio = store.create_portfolio(PortfolioCreate(name="P"))
    account = store.create_account(
        AccountCreate(
            portfolio_id=portfolio.id,
            name="Konto",
            account_type="Bankkonto",
        )
    )

    # Create expense bookings (negative = outgoing payments, open status)
    store.create_booking(
        BookingCreate(
            account_id=account.id,
            booking_date=datetime.date(2025, 1, 10),
            amount=-200.0,
            status="open",
        )
    )
    store.create_booking(
        BookingCreate(
            account_id=account.id,
            booking_date=datetime.date(2025, 1, 20),
            amount=-150.0,
            status="open",
        )
    )

    invoice = store.create_invoice(
        InvoiceCreate(
            supplier="Handwerker GmbH",
            invoice_date=datetime.date(2025, 1, 15),
            net_amount=250.0,
            vat_amount=47.50,
            gross_amount=297.50,
        )
    )

    result = invoices.match_invoice_to_bookings(invoice_id=invoice.id)

    assert result["allocated_total"] == 297.50
    assert result["unmatched_amount"] == 0.0
    assert len(result["allocations"]) == 2
    # First booking (200) fully used, second partially (97.50)
    assert result["allocations"][0]["allocated_amount"] == 200.0
    assert result["allocations"][1]["allocated_amount"] == 97.50


def test_invoice_match_partial_allocation() -> None:
    _clear_store()
    portfolio = store.create_portfolio(PortfolioCreate(name="P"))
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
            booking_date=datetime.date(2025, 2, 1),
            amount=-100.0,
            status="open",
        )
    )

    invoice = store.create_invoice(
        InvoiceCreate(
            supplier="Lieferant",
            invoice_date=datetime.date(2025, 2, 5),
            net_amount=200.0,
            gross_amount=200.0,
        )
    )

    result = invoices.match_invoice_to_bookings(invoice_id=invoice.id)

    assert result["allocated_total"] == 100.0
    assert result["unmatched_amount"] == 100.0
    assert len(result["allocations"]) == 1


def test_invoice_match_no_candidates() -> None:
    _clear_store()
    invoice = store.create_invoice(
        InvoiceCreate(
            supplier="Niemand",
            invoice_date=datetime.date(2025, 3, 1),
            net_amount=500.0,
            gross_amount=500.0,
        )
    )

    result = invoices.match_invoice_to_bookings(invoice_id=invoice.id)

    assert result["allocated_total"] == 0.0
    assert result["unmatched_amount"] == 500.0
    assert len(result["allocations"]) == 0


def test_invoice_match_not_found() -> None:
    _clear_store()
    try:
        invoices.match_invoice_to_bookings(invoice_id="nonexistent")
        assert False, "Should have raised HTTPException"
    except Exception as exc:
        assert "404" in str(exc.status_code)
