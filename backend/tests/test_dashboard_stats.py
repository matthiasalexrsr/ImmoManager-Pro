from datetime import date

from backend.dependencies import store
from backend.models import (
    AccountCreate,
    AllocationKeyCreate,
    BillingPeriodCreate,
    ContractCreate,
    DocumentCreate,
    EscalationRuleCreate,
    InvoiceCreate,
    MaintenanceCaseCreate,
    NotificationCreate,
    PortfolioCreate,
    PropertyCreate,
    ReceivableCreate,
    RentChargeCreate,
    TaskCreate,
    TenantCreate,
    UnitCreate,
)
from backend.routers.dashboard import get_dashboard_stats


def test_dashboard_stats_include_operational_workflow_counts() -> None:
    store.clear_all()

    portfolio = store.create_portfolio(PortfolioCreate(name="Workflow Portfolio"))
    property_ = store.create_property(
        PropertyCreate(
            portfolio_id=portfolio.id,
            name="Workflow Haus",
            property_type="residential",
        ),
    )
    unit = store.create_unit(
        UnitCreate(
            property_id=property_.id,
            label="WE 1",
            unit_type="apartment",
            status="occupied",
        ),
    )
    tenant = store.create_tenant(TenantCreate(full_name="Max Workflow"))
    contract = store.create_contract(
        ContractCreate(
            property_id=property_.id,
            unit_id=unit.id,
            tenant_id=tenant.id,
            contract_number="WF-001",
            start_date=date(2026, 1, 1),
            status="active",
        ),
    )
    store.create_account(
        AccountCreate(
            portfolio_id=portfolio.id,
            name="Hauskonto",
            account_type="bank",
        ),
    )
    store.create_receivable(
        ReceivableCreate(
            contract_id=contract.id,
            due_date=date(2026, 2, 1),
            amount_due=900,
            status="open",
        ),
    )
    store.create_receivable(
        ReceivableCreate(
            contract_id=contract.id,
            due_date=date(2026, 1, 1),
            amount_due=120,
            dunning_level="level_1",
            status="overdue",
        ),
    )
    store.create_invoice(
        InvoiceCreate(
            property_id=property_.id,
            supplier="Handwerk GmbH",
            invoice_date=date(2026, 2, 15),
            net_amount=100,
            gross_amount=119,
            status="open",
        ),
    )
    store.create_document(
        DocumentCreate(
            property_id=property_.id,
            title="Rechnung Handwerk",
            file_url="/uploads/documents/rechnung.pdf",
        ),
    )
    store.create_task(TaskCreate(title="Heizung prüfen", property_id=property_.id, status="open"))
    store.create_maintenance_case(
        MaintenanceCaseCreate(
            property_id=property_.id,
            title="Wasserschaden",
            status="open",
            priority="high",
            due_date=date(2000, 1, 1),
        ),
    )
    store.create_escalation_rule(
        EscalationRuleCreate(
            name="Wartung eskalieren",
            entity_type="maintenance",
            condition_field="due_date",
            days_overdue=0,
            action="notify",
            notification_severity="critical",
            is_active=True,
        ),
    )
    store.create_notification(
        NotificationCreate(
            notification_type="task_due",
            title="Aufgabe fällig",
            content="Bitte prüfen",
            status="unread",
        ),
    )
    store.create_rent_charge(
        RentChargeCreate(
            contract_id=contract.id,
            month="2026-02",
            cold_rent=900,
            status="open",
        ),
    )
    store.create_billing_period(
        BillingPeriodCreate(
            property_id=property_.id,
            label="2026",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status="draft",
        ),
    )
    store.create_allocation_key(
        AllocationKeyCreate(
            property_id=property_.id,
            name="Wohnfläche",
            key_type="area_sqm",
        ),
    )

    stats = get_dashboard_stats()

    assert stats["portfolio_count"] == 1
    assert stats["property_count"] == 1
    assert stats["unit_count"] == 1
    assert stats["active_contracts"] == 1
    assert stats["account_count"] == 1
    assert stats["invoice_count"] == 1
    assert stats["open_invoices"] == 1
    assert stats["receivable_count"] == 2
    assert stats["open_receivables"] == 1
    assert stats["overdue_receivables"] == 1
    assert stats["dunning_receivables"] == 1
    assert stats["document_count"] == 1
    assert stats["active_contracts_missing_documents"] == 1
    assert stats["open_maintenance"] == 1
    assert stats["overdue_maintenance"] == 1
    assert stats["active_escalation_rules"] == 1
    assert stats["maintenance_escalation_candidates"] == 1
    assert stats["task_count"] == 1
    assert stats["open_tasks"] == 1
    assert stats["notification_count"] == 1
    assert stats["unread_notifications"] == 1
    assert stats["rent_charge_count"] == 1
    assert stats["open_rent_charges"] == 1
    assert stats["billing_period_count"] == 1
    assert stats["draft_billing_periods"] == 1
    assert stats["billing_preflight_periods_checked"] == 1
    assert stats["billing_preflight_blockers"] == 1
    assert stats["billing_preflight_warnings"] == 0
    assert stats["allocation_key_count"] == 1
