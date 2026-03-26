import datetime

from backend.dependencies import store
from backend.models import (
    AllocationKeyCreate,
    BillingPeriodCreate,
    ContractCreate,
    CostItemCreate,
    MeterCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)
from backend.routers import billing


def _clear_store() -> None:
    store.clear_all()


def test_preflight_reports_blockers_and_warnings():
    _clear_store()

    portfolio = store.create_portfolio(PortfolioCreate(name='P'))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name='Haus', property_type='MFH'))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label='EG', unit_type='Wohnung'))
    tenant = store.create_tenant(TenantCreate(full_name='Max'))
    store.create_contract(
        ContractCreate(
            contract_number='C-1',
            property_id=prop.id,
            unit_id=unit.id,
            tenant_id=tenant.id,
            start_date=datetime.date(2024, 1, 1),
        )
    )
    period = store.create_billing_period(
        BillingPeriodCreate(
            property_id=prop.id,
            label='BK 2024',
            start_date=datetime.date(2024, 1, 1),
            end_date=datetime.date(2024, 12, 31),
        )
    )
    key = store.create_allocation_key(AllocationKeyCreate(property_id=prop.id, name='Fläche', key_type='area_sqm'))
    store.create_cost_item(
        CostItemCreate(
            billing_period_id=period.id,
            description='Wasser',
            amount=-10.0,
            allocation_key_id=key.id,
        )
    )

    result = billing.get_billing_period_preflight(period.id)

    assert result.has_blockers is True
    blocker_codes = {i.code for i in result.blockers}
    warning_codes = {i.code for i in result.warnings}
    assert 'MISSING_AREA' in blocker_codes
    assert 'NON_POSITIVE_COST' in warning_codes
    assert result.metrics['contracts_in_period'] == 1
    assert result.metrics['cost_items'] == 1


def test_preflight_ready_case_without_blockers():
    _clear_store()

    portfolio = store.create_portfolio(PortfolioCreate(name='P'))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name='Haus', property_type='MFH'))
    unit = store.create_unit(
        UnitCreate(
            property_id=prop.id,
            label='EG',
            unit_type='Wohnung',
            area_sqm=55.0,
            service_charge_advance=120.0,
            heating_advance=30.0,
        )
    )
    tenant = store.create_tenant(TenantCreate(full_name='Max'))
    store.create_contract(
        ContractCreate(
            contract_number='C-1',
            property_id=prop.id,
            unit_id=unit.id,
            tenant_id=tenant.id,
            start_date=datetime.date(2024, 1, 1),
        )
    )
    period = store.create_billing_period(
        BillingPeriodCreate(
            property_id=prop.id,
            label='BK 2024',
            start_date=datetime.date(2024, 1, 1),
            end_date=datetime.date(2024, 12, 31),
        )
    )
    key = store.create_allocation_key(AllocationKeyCreate(property_id=prop.id, name='Fläche', key_type='area_sqm'))
    store.create_cost_item(
        CostItemCreate(
            billing_period_id=period.id,
            description='Wasser',
            amount=240.0,
            allocation_key_id=key.id,
        )
    )

    result = billing.get_billing_period_preflight(period.id)

    assert result.has_blockers is False
    assert result.blockers == []
    assert result.metrics['allocation_keys_missing'] == 0


def test_preflight_consumption_blocker_without_readings():
    _clear_store()

    portfolio = store.create_portfolio(PortfolioCreate(name='P'))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name='Haus', property_type='MFH'))
    unit = store.create_unit(
        UnitCreate(
            property_id=prop.id,
            label='EG',
            unit_type='Wohnung',
            area_sqm=55.0,
            rooms=2.0,
            service_charge_advance=120.0,
            heating_advance=30.0,
        )
    )
    tenant = store.create_tenant(TenantCreate(full_name='Max'))
    store.create_contract(
        ContractCreate(
            contract_number='C-1',
            property_id=prop.id,
            unit_id=unit.id,
            tenant_id=tenant.id,
            start_date=datetime.date(2024, 1, 1),
        )
    )
    period = store.create_billing_period(
        BillingPeriodCreate(
            property_id=prop.id,
            label='BK 2024',
            start_date=datetime.date(2024, 1, 1),
            end_date=datetime.date(2024, 12, 31),
        )
    )
    key = store.create_allocation_key(
        AllocationKeyCreate(property_id=prop.id, name='Verbrauch', key_type='consumption')
    )
    store.create_cost_item(
        CostItemCreate(
            billing_period_id=period.id,
            description='Heizung',
            amount=250.0,
            allocation_key_id=key.id,
        )
    )
    store.create_meter(MeterCreate(unit_id=unit.id, meter_type='heating', serial_number='M1'))

    result = billing.get_billing_period_preflight(period.id)

    assert result.has_blockers is True
    assert 'MISSING_CONSUMPTION' in {i.code for i in result.blockers}
