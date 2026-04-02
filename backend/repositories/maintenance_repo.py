"""Maintenance domain repository."""

import logging

from sqlalchemy.orm import Session

from ..db.orm_models import MaintenanceCaseORM
from ..models import MaintenanceCase, MaintenanceCaseCreate
from ..storage import ValidationError
from .base import BaseRepository

logger = logging.getLogger(__name__)


class MaintenanceRepository:
    """Maintenance cases."""

    def __init__(self, db: Session, portfolio_repo=None):
        self.db = db
        self._maintenance = BaseRepository(
            db, MaintenanceCaseORM, MaintenanceCase, "Instandhaltungsfall nicht gefunden",
        )
        self._portfolio_repo = portfolio_repo

    def _commit(self):
        self.db.commit()

    def list_maintenance_cases(self) -> list[MaintenanceCase]:
        return self._maintenance.list_all()

    def create_maintenance_case(self, data: MaintenanceCaseCreate) -> MaintenanceCase:
        pr = self._portfolio_repo
        if pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._maintenance.create(data)
        self._commit()
        return result

    def get_maintenance_case(self, case_id: str) -> MaintenanceCase:
        return self._maintenance.get(case_id)

    def update_maintenance_case(self, case_id: str, data: MaintenanceCaseCreate) -> MaintenanceCase:
        pr = self._portfolio_repo
        if pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._maintenance.update(case_id, data)
        self._commit()
        return result

    def delete_maintenance_case(self, case_id: str) -> None:
        self._maintenance.delete(case_id)
        self._commit()
