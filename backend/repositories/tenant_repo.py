"""Tenant domain repository — tenants, contracts, viewings, handover protocols, leads."""

import logging

from sqlalchemy.orm import Session

from ..db.orm_models import (
    ContractORM,
    DepositORM,
    HandoverProtocolORM,
    LeadORM,
    MeterReadingORM,
    RentAdjustmentORM,
    TenantORM,
    ViewingAppointmentORM,
)
from ..models import (
    Contract,
    ContractCreate,
    Deposit,
    DepositCreate,
    HandoverProtocol,
    HandoverProtocolCreate,
    Lead,
    LeadCreate,
    MeterReading,
    MeterReadingCreate,
    RentAdjustment,
    RentAdjustmentCreate,
    Tenant,
    TenantCreate,
    ViewingAppointment,
    ViewingAppointmentCreate,
)
from ..storage import NotFoundError, ValidationError
from .base import BaseRepository

logger = logging.getLogger(__name__)


class TenantRepository:
    """Tenants, contracts, viewing appointments, handover protocols, leads."""

    def __init__(self, db: Session, portfolio_repo=None, marketing_repo=None):
        self.db = db
        self._tenants = BaseRepository(db, TenantORM, Tenant, "Mieter nicht gefunden")
        self._contracts = BaseRepository(db, ContractORM, Contract, "Vertrag nicht gefunden")
        self._viewings = BaseRepository(db, ViewingAppointmentORM, ViewingAppointment, "Besichtigungstermin nicht gefunden")
        self._handover_protocols = BaseRepository(db, HandoverProtocolORM, HandoverProtocol, "Übergabeprotokoll nicht gefunden")
        self._leads = BaseRepository(db, LeadORM, Lead, "Interessent nicht gefunden")
        self._deposits = BaseRepository(db, DepositORM, Deposit, "Kaution nicht gefunden")
        self._rent_adjustments = BaseRepository(db, RentAdjustmentORM, RentAdjustment, "Mietanpassung nicht gefunden")
        self._meter_readings = BaseRepository(db, MeterReadingORM, MeterReading, "Zählerstand nicht gefunden")
        # Cross-domain references (set by SQLAlchemyStore facade)
        self._portfolio_repo = portfolio_repo
        self._marketing_repo = marketing_repo

    def _commit(self):
        self.db.commit()

    # --- Tenants ---
    def list_tenants(self) -> list[Tenant]:
        return self._tenants.list_all()

    def create_tenant(self, data: TenantCreate) -> Tenant:
        result = self._tenants.create(data)
        self._commit()
        return result

    def get_tenant(self, tenant_id: str) -> Tenant:
        return self._tenants.get(tenant_id)

    def update_tenant(self, tenant_id: str, data: TenantCreate) -> Tenant:
        result = self._tenants.update(tenant_id, data)
        self._commit()
        return result

    def delete_tenant(self, tenant_id: str) -> None:
        self._tenants.delete(tenant_id)
        self._commit()

    # --- Contracts ---
    def list_contracts(self) -> list[Contract]:
        return self._contracts.list_all()

    def create_contract(self, data: ContractCreate) -> Contract:
        pr = self._portfolio_repo
        if pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        if not self._tenants.exists(data.tenant_id):
            raise ValidationError("Mieter existiert nicht")
        # Verify unit belongs to property
        if pr:
            unit = pr._units.get(data.unit_id)
            if unit.property_id != data.property_id:
                raise ValidationError("Einheit gehört nicht zur Immobilie")
        # Verify unique contract number
        existing = self.db.query(ContractORM).filter(ContractORM.contract_number == data.contract_number).first()
        if existing:
            raise ValidationError("Vertragsnummer existiert bereits")
        result = self._contracts.create(data)
        self._commit()
        return result

    def get_contract(self, contract_id: str) -> Contract:
        return self._contracts.get(contract_id)

    def update_contract(self, contract_id: str, data: ContractCreate) -> Contract:
        if not self._contracts.exists(contract_id):
            raise NotFoundError("Vertrag nicht gefunden")
        pr = self._portfolio_repo
        if pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        if not self._tenants.exists(data.tenant_id):
            raise ValidationError("Mieter existiert nicht")
        if pr:
            unit = pr._units.get(data.unit_id)
            if unit.property_id != data.property_id:
                raise ValidationError("Einheit gehört nicht zur Immobilie")
        existing = (
            self.db.query(ContractORM)
            .filter(ContractORM.contract_number == data.contract_number, ContractORM.id != contract_id)
            .first()
        )
        if existing:
            raise ValidationError("Vertragsnummer existiert bereits")
        result = self._contracts.update(contract_id, data)
        self._commit()
        return result

    def delete_contract(self, contract_id: str) -> None:
        self._contracts.delete(contract_id)
        self._commit()

    # --- Viewing Appointments ---
    def list_viewing_appointments(self) -> list[ViewingAppointment]:
        return self._viewings.list_all()

    def create_viewing_appointment(self, data: ViewingAppointmentCreate) -> ViewingAppointment:
        if not self._leads.exists(data.lead_id):
            raise ValidationError("Interessent existiert nicht")
        pr = self._portfolio_repo
        if pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._viewings.create(data)
        self._commit()
        return result

    def get_viewing_appointment(self, appointment_id: str) -> ViewingAppointment:
        return self._viewings.get(appointment_id)

    def update_viewing_appointment(self, appointment_id: str, data: ViewingAppointmentCreate) -> ViewingAppointment:
        if not self._leads.exists(data.lead_id):
            raise ValidationError("Interessent existiert nicht")
        pr = self._portfolio_repo
        if pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._viewings.update(appointment_id, data)
        self._commit()
        return result

    def delete_viewing_appointment(self, appointment_id: str) -> None:
        self._viewings.delete(appointment_id)
        self._commit()

    # --- Handover Protocols ---
    def list_handover_protocols(self) -> list[HandoverProtocol]:
        return self._handover_protocols.list_all()

    def create_handover_protocol(self, data: HandoverProtocolCreate) -> HandoverProtocol:
        if not self._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        pr = self._portfolio_repo
        if pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._handover_protocols.create(data)
        self._commit()
        return result

    def get_handover_protocol(self, protocol_id: str) -> HandoverProtocol:
        return self._handover_protocols.get(protocol_id)

    def update_handover_protocol(self, protocol_id: str, data: HandoverProtocolCreate) -> HandoverProtocol:
        result = self._handover_protocols.update(protocol_id, data)
        self._commit()
        return result

    def delete_handover_protocol(self, protocol_id: str) -> None:
        self._handover_protocols.delete(protocol_id)
        self._commit()

    # --- Meter Readings (handover-protocol-linked) ---
    def list_meter_readings(self) -> list[MeterReading]:
        return self._meter_readings.list_all()

    def create_meter_reading(self, data: MeterReadingCreate) -> MeterReading:
        if not self._handover_protocols.exists(data.handover_id):
            raise ValidationError("Übergabeprotokoll existiert nicht")
        result = self._meter_readings.create(data)
        self._commit()
        return result

    def get_meter_reading(self, reading_id: str) -> MeterReading:
        return self._meter_readings.get(reading_id)

    def update_meter_reading(self, reading_id: str, data: MeterReadingCreate) -> MeterReading:
        if not self._handover_protocols.exists(data.handover_id):
            raise ValidationError("Übergabeprotokoll existiert nicht")
        result = self._meter_readings.update(reading_id, data)
        self._commit()
        return result

    def delete_meter_reading(self, reading_id: str) -> None:
        self._meter_readings.delete(reading_id)
        self._commit()

    # --- Deposits ---
    def list_deposits(self) -> list[Deposit]:
        return self._deposits.list_all()

    def create_deposit(self, data: DepositCreate) -> Deposit:
        if not self._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        result = self._deposits.create(data)
        self._commit()
        return result

    def get_deposit(self, deposit_id: str) -> Deposit:
        return self._deposits.get(deposit_id)

    def update_deposit(self, deposit_id: str, data: DepositCreate) -> Deposit:
        if not self._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        result = self._deposits.update(deposit_id, data)
        self._commit()
        return result

    def delete_deposit(self, deposit_id: str) -> None:
        self._deposits.delete(deposit_id)
        self._commit()

    # --- Rent Adjustments ---
    def list_rent_adjustments(self) -> list[RentAdjustment]:
        return self._rent_adjustments.list_all()

    def create_rent_adjustment(self, data: RentAdjustmentCreate) -> RentAdjustment:
        if not self._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        result = self._rent_adjustments.create(data)
        self._commit()
        return result

    def get_rent_adjustment(self, adj_id: str) -> RentAdjustment:
        return self._rent_adjustments.get(adj_id)

    def update_rent_adjustment(self, adj_id: str, data: RentAdjustmentCreate) -> RentAdjustment:
        result = self._rent_adjustments.update(adj_id, data)
        self._commit()
        return result

    def delete_rent_adjustment(self, adj_id: str) -> None:
        self._rent_adjustments.delete(adj_id)
        self._commit()

    # --- Leads ---
    def list_leads(self) -> list[Lead]:
        return self._leads.list_all()

    def create_lead(self, data: LeadCreate) -> Lead:
        mr = self._marketing_repo
        pr = self._portfolio_repo
        if data.listing_id and mr and not mr._listings.exists(data.listing_id):
            raise ValidationError("Inserat existiert nicht")
        if data.unit_id and pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._leads.create(data)
        self._commit()
        return result

    def get_lead(self, lead_id: str) -> Lead:
        return self._leads.get(lead_id)

    def update_lead(self, lead_id: str, data: LeadCreate) -> Lead:
        mr = self._marketing_repo
        pr = self._portfolio_repo
        if data.listing_id and mr and not mr._listings.exists(data.listing_id):
            raise ValidationError("Inserat existiert nicht")
        if data.unit_id and pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._leads.update(lead_id, data)
        self._commit()
        return result

    def delete_lead(self, lead_id: str) -> None:
        # Viewing appointments cascade via DB FK
        self._leads.delete(lead_id)
        self._commit()
