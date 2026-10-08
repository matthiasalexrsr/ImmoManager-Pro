"""Billing domain repository — billing periods, allocation keys, cost items, utility statements."""

import logging

from sqlalchemy.orm import Session

from ..db.orm_models import (
    AllocationKeyORM,
    BillingObjectionORM,
    BillingPeriodORM,
    CostItemORM,
    UtilityStatementORM,
)
from ..models import (
    AllocationKey,
    AllocationKeyCreate,
    BillingObjection,
    BillingObjectionCreate,
    BillingPeriod,
    BillingPeriodCreate,
    CostItem,
    CostItemCreate,
    UtilityStatement,
    UtilityStatementCreate,
)
from ..storage import (
    FINAL_STATEMENT_MESSAGE,
    ValidationError,
    check_final_statement_change,
    check_final_statement_delete,
)
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
        self._objections = BaseRepository(db, BillingObjectionORM, BillingObjection, "Widerspruch nicht gefunden")
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
        statements = self._utility_statements.filter_by(billing_period_id=period_id)
        if any(s.snapshot_hash for s in statements):
            raise ValidationError(FINAL_STATEMENT_MESSAGE)
        # an objection answered by this (draft) correction is open again
        for objection in self._objections.filter_by(correction_period_id=period_id):
            orm = self._objections.get_orm(objection.id)
            orm.correction_period_id = None
            orm.status = "open"
        for objection in self._objections.filter_by(billing_period_id=period_id):
            self._objections.delete(objection.id)
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
        if tr and data.contract_id is not None and not tr._contracts.exists(data.contract_id):
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
        if tr and data.contract_id is not None and not tr._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        pr = self._portfolio_repo
        if pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        old = self._utility_statements.get(statement_id)
        check_final_statement_change(old, UtilityStatement.model_validate({**old.model_dump(), **data.model_dump()}))
        result = self._utility_statements.update(statement_id, data)
        self._commit()
        return result

    def delete_utility_statement(self, statement_id: str) -> None:
        check_final_statement_delete(self._utility_statements.get(statement_id))
        for objection in self._objections.filter_by(statement_id=statement_id):
            self._objections.delete(objection.id)
        self._utility_statements.delete(statement_id)
        self._commit()

    # --- Objections (Widerspruch) ---
    def list_billing_objections(self, billing_period_id: str | None = None) -> list[BillingObjection]:
        items = (self._objections.filter_by(billing_period_id=billing_period_id) if billing_period_id
                 else self._objections.list_all())
        return sorted(items, key=lambda o: (o.received_on, o.created_at, o.id))

    def _check_objection(self, data: BillingObjectionCreate) -> None:
        if not self._billing_periods.exists(data.billing_period_id):
            raise ValidationError("Abrechnungsperiode existiert nicht")
        if data.statement_id is not None:
            if not self._utility_statements.exists(data.statement_id) or (
                    self._utility_statements.get(data.statement_id).billing_period_id != data.billing_period_id):
                raise ValidationError("Die Einzelabrechnung gehört nicht zu dieser Abrechnungsperiode")
        if data.correction_period_id is not None and not self._billing_periods.exists(data.correction_period_id):
            raise ValidationError("Korrektur existiert nicht")

    def create_billing_objection(self, data: BillingObjectionCreate) -> BillingObjection:
        self._check_objection(data)
        result = self._objections.create(data)
        self._commit()
        return result

    def get_billing_objection(self, objection_id: str) -> BillingObjection:
        return self._objections.get(objection_id)

    def update_billing_objection(self, objection_id: str, data: BillingObjectionCreate) -> BillingObjection:
        self._objections.get(objection_id)
        self._check_objection(data)
        result = self._objections.update(objection_id, data)
        self._commit()
        return result
