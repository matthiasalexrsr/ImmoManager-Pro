import datetime

import pytest

from backend.dependencies import store
from backend.models import (
    AllocationKeyCreate,
    BillingPeriodCreate,
    ContractCreate,
    CostItemCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)
from backend.routers import billing
from backend.tests.test_billing_disputes import context as context
from backend.tests.test_billing_disputes import draft_http as draft_http
from backend.tests.test_utility_statement_draft_preview import generated


def _clear_store() -> None:
    store.clear_all()


def _setup_generated_period() -> tuple[str, str]:
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
    contract = store.create_contract(
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
    statements = billing.generate_utility_statements(period.id)
    return period.id, statements[0].id if statements else contract.id


def test_export_billing_period_csv_response():
    _clear_store()
    period_id, _ = _setup_generated_period()

    response = billing.export_billing_period(period_id, export_format='csv')

    assert response.media_type == 'text/csv'
    assert 'billing_period_' in response.headers.get('content-disposition', '')
    body = response.body.decode('utf-8')
    assert 'statement_id' in body
    assert period_id in body


@pytest.mark.parametrize("draft_http", ["memory"], indirect=True)
def test_download_utility_statement_pdf_generated_authenticated_draft(context):
    statement = generated(context)
    active = context["active"]
    path = "/api/v1/billing/statements/" + statement["id"] + "/pdf"
    assert active.client.get(path).status_code == 401
    response = active.client.get(path, headers=context["headers"])
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-") and response.headers["x-utility-preview"] == "draft-derivation"
    assert "statement_" in response.headers["content-disposition"]
