"""Billing domain repository — billing periods, allocation keys, cost items, utility statements."""

import logging
from sqlalchemy.orm import Session

from ..db.orm_models import (
    AllocationKeyORM, BillingPeriodORM, CostItemORM, UtilityStatementORM,
)
from ..models import (
    AllocationKey, AllocationKeyCreate,
    BillingPeriod, BillingPeriodCreate,
    CostItem, CostItemCreate,
    UtilityStatement, UtilityStatementCreate,
)
from ..storage import ValidationError
from .base import BaseRepository

logger = logging.getLogger(__name__)


class BillingRepository:
    """Billing periods, allocation keys, cost items, utility statements."""

    def __init__(self, db: Session, portfolio_repo=None, tenant_repo=None):
        self.db = db
        self._billing_periods = BaseRepository(db, BillingPeriodORM, BillingPeriod, "Abrechnungsperiode nicht gefunden")
        self._allocation_keys = BaseRepository(db, AllocationKeyORM, AllocationKey, "Verteilerschlüssel nicht gefunden")
        self._cost_items = BaseRepository(db, CostItemORM, CostItem, "Kostenposition nicht gefunden")
        self._utility_statements = BaseRepository(db, UtilityStatementORM, UtilityStatement, "Betriebskostenabrechnung nicht gefunden")
        # Cross-domain references
        self._portfolio_repo = portfolio_repo
        self._tenant_repo = tenant_repo

    def _commit(self):
        self.db.commit()

    # --- Billing Periods ---
    def list_billing_periods(self) -> list[BillingPeriod]:
        return self._billing_periods.list_all()

    def create_billing_period(self, data: BillingPeriodCreate) -> BillingPeriod:
        pr = self._portfolio_repo
        if pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.end_date <= data.start_date:
            raise ValidationError("Enddatum muss nach Startdatum liegen")
        result = self._billing_periods.create(data)
        self._commit()
        return result

    def get_billing_period(self, period_id: str) -> BillingPeriod:
        return self._billing_periods.get(period_id)

    def update_billing_period(self, period_id: str, data: BillingPeriodCreate) -> BillingPeriod:
        pr = self._portfolio_repo
        if pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.end_date <= data.start_date:
            raise ValidationError("Enddatum muss nach Startdatum liegen")
        result = self._billing_periods.update(period_id, data)
        self._commit()
        return result

    def delete_billing_period(self, period_id: str) -> None:
        self._billing_periods.delete(period_id)
        self._commit()

    # --- Allocation Keys ---
    def list_allocation_keys(self) -> list[AllocationKey]:
        return self._allocation_keys.list_all()

    def create_allocation_key(self, data: AllocationKeyCreate) -> AllocationKey:
        pr = self._portfolio_repo
        if pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        result = self._allocation_keys.create(data)
        self._commit()
        return result

    def get_allocation_key(self, key_id: str) -> AllocationKey:
        return self._allocation_keys.get(key_id)

    def update_allocation_key(self, key_id: str, data: AllocationKeyCreate) -> AllocationKey:
        pr = self._portfolio_repo
        if pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        result = self._allocation_keys.update(key_id, data)
        self._commit()
        return result

    def delete_allocation_key(self, key_id: str) -> None:
        self._allocation_keys.delete(key_id)
        self._commit()

    # --- Cost Items ---
    def list_cost_items(self) -> list[CostItem]:
        return self._cost_items.list_all()

    def create_cost_item(self, data: CostItemCreate) -> CostItem:
        if not self._billing_periods.exists(data.billing_period_id):
            raise ValidationError("Abrechnungsperiode existiert nicht")
        if not self._allocation_keys.exists(data.allocation_key_id):
            raise ValidationError("Verteilerschlüssel existiert nicht")
        result = self._cost_items.create(data)
        self._commit()
        return result

    def get_cost_item(self, item_id: str) -> CostItem:
        return self._cost_items.get(item_id)

    def update_cost_item(self, item_id: str, data: CostItemCreate) -> CostItem:
        if not self._billing_periods.exists(data.billing_period_id):
            raise ValidationError("Abrechnungsperiode existiert nicht")
        if not self._allocation_keys.exists(data.allocation_key_id):
            raise ValidationError("Verteilerschlüssel existiert nicht")
        result = self._cost_items.update(item_id, data)
        self._commit()
        return result

    def delete_cost_item(self, item_id: str) -> None:
        self._cost_items.delete(item_id)
        self._commit()

    # --- Utility Statements ---
    def list_utility_statements(self) -> list[UtilityStatement]:
        return self._utility_statements.list_all()

    def create_utility_statement(self, data: UtilityStatementCreate) -> UtilityStatement:
        if not self._billing_periods.exists(data.billing_period_id):
            raise ValidationError("Abrechnungsperiode existiert nicht")
        tr = self._tenant_repo
        if tr and not tr._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        pr = self._portfolio_repo
        if pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._utility_statements.create(data)
        self._commit()
        return result

    def get_utility_statement(self, statement_id: str) -> UtilityStatement:
        return self._utility_statements.get(statement_id)

    def update_utility_statement(self, statement_id: str, data: UtilityStatementCreate) -> UtilityStatement:
        if not self._billing_periods.exists(data.billing_period_id):
            raise ValidationError("Abrechnungsperiode existiert nicht")
        tr = self._tenant_repo
        if tr and not tr._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        pr = self._portfolio_repo
        if pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._utility_statements.update(statement_id, data)
        self._commit()
        return result

    def delete_utility_statement(self, statement_id: str) -> None:
        self._utility_statements.delete(statement_id)
        self._commit()
