"""Generated notifications and escalations: unpaid receivables, readable texts, no repeats."""

from datetime import date

import pytest

from backend.dependencies import store
from backend.models import (
    ContractCreate,
    EscalationRuleCreate,
    PortfolioCreate,
    PropertyCreate,
    ReceivableCreate,
    TaskCreate,
    TenantCreate,
    UnitCreate,
)
from backend.routers import escalation, notifications
from backend.services.data_snapshot import clear_business_data

AS_OF = date(2026, 10, 4)


@pytest.fixture(autouse=True)
def _clean():
    clear_business_data(store)
    yield
    clear_business_data(store)


@pytest.fixture
def contract():
    pf = store.create_portfolio(PortfolioCreate(name="P"))
    prop = store.create_property(PropertyCreate(portfolio_id=pf.id, name="Gewerbehof", property_type="commercial"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="Büro B", unit_type="Gewerbe"))
    tenant = store.create_tenant(TenantCreate(full_name="Agentur Pixel GmbH"))
    return store.create_contract(ContractCreate(
        contract_number="MV-022", property_id=prop.id, unit_id=unit.id, tenant_id=tenant.id,
        start_date=date(2021, 6, 1)))


def _receivable(contract, amount=1620.0, status="open", due=date(2026, 8, 3)):
    return store.create_receivable(ReceivableCreate(
        contract_id=contract.id, due_date=due, amount_due=amount, status=status))


def test_every_unpaid_receivable_is_reported_but_not_credits_or_paid_ones(contract):
    """Regression: receivables marked overdue never produced a notification (stress test)."""
    unpaid = {_receivable(contract, status=s).id for s in ("open", "overdue", "partial")}
    _receivable(contract, status="paid")
    _receivable(contract, status="cancelled")
    _receivable(contract, amount=-206.32)  # a credit owed to the tenant

    created = notifications.generate_overdue_payment_notifications(as_of=AS_OF)

    assert {n.entity_id for n in created} == unpaid
    assert created[0].title == "Überfällige Zahlung: Agentur Pixel GmbH"
    assert created[0].content == "Forderung über 1.620,00 € aus Vertrag MV-022 war am 03.08.2026 fällig und ist noch offen."


def test_generators_do_not_repeat_themselves(contract):
    """Regression: every run created the same notifications again."""
    _receivable(contract)
    store.create_task(TaskCreate(title="Rauchmelder prüfen", due_date=date(2026, 9, 30), status="in_progress"))
    store.update_contract(contract.id, ContractCreate(**{
        **contract.model_dump(include=set(ContractCreate.model_fields)), "end_date": date(2026, 12, 31)}))

    def run():
        return (notifications.generate_overdue_payment_notifications(as_of=AS_OF)
                + notifications.generate_due_task_notifications(as_of=AS_OF)
                + notifications.generate_expiring_contract_notifications(days_ahead=90, as_of=AS_OF))

    first = run()
    for n in first:  # reading a notification does not bring it back
        notifications.mark_notification_read(n.id)

    assert [n.notification_type for n in first] == ["overdue_payment", "task_due", "contract_expiry"]
    assert run() == []
    assert len(store.list_notifications()) == 3


def test_a_new_due_date_is_reported_again(contract):
    receivable = _receivable(contract)
    notifications.generate_overdue_payment_notifications(as_of=AS_OF)
    store.update_receivable(receivable.id, ReceivableCreate(**{
        **receivable.model_dump(include=set(ReceivableCreate.model_fields)), "due_date": date(2026, 9, 1)}))

    again = notifications.generate_overdue_payment_notifications(as_of=AS_OF)

    assert [n.entity_id for n in again] == [receivable.id]
    assert "01.09.2026" in again[0].content


def test_receivable_escalation_names_tenant_and_contract_once(contract):
    """Regression: the text showed the receivable's id, overdue receivables were skipped, runs repeated."""
    receivable = _receivable(contract, status="overdue")
    store.create_escalation_rule(EscalationRuleCreate(
        name="Mahnung 30 Tage", entity_type="receivable", condition_field="due_date", days_overdue=30,
        action="notify", notification_severity="critical"))

    first = escalation.run_escalation(as_of=AS_OF)
    second = escalation.run_escalation(as_of=AS_OF)

    assert (first["notifications_generated"], second["notifications_generated"]) == (1, 0)
    notification = store.get_notification(first["notification_ids"][0])
    assert notification.title == "Eskalation: Überfällige Forderung – Agentur Pixel GmbH"
    assert notification.content == (
        "Forderung über 1.620,00 € aus Vertrag MV-022 (fällig am 03.08.2026) ist seit mindestens"
        " 30 Tagen überfällig. Regel: Mahnung 30 Tage")
    assert receivable.id not in notification.content
