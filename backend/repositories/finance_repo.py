"""Finance domain repository — bookings, invoices, receivables, tax, budgets, meters."""

import logging
from sqlalchemy.orm import Session

from ..db.orm_models import (
    BookingORM, BudgetORM, EscalationRuleORM, InsuranceORM, InvoiceORM,
    MeterORM, ReceivableORM, RentChargeORM,
    StandaloneMeterReadingORM, TaxRateORM,
)
from ..models import (
    Booking, BookingCreate,
    Budget, BudgetCreate,
    EscalationRule, EscalationRuleCreate,
    Insurance, InsuranceCreate,
    Invoice, InvoiceCreate,
    Meter, MeterCreate,
    Receivable, ReceivableCreate,
    RentCharge, RentChargeCreate,
    StandaloneMeterReading, StandaloneMeterReadingCreate,
    TaxRate, TaxRateCreate,
)
from ..storage import ValidationError
from .base import BaseRepository

logger = logging.getLogger(__name__)


class FinanceRepository:
    """Bookings, invoices, receivables, tax rates, budgets, meters, insurances, rent charges."""

    def __init__(self, db: Session, portfolio_repo=None, tenant_repo=None):
        self.db = db
        self._bookings = BaseRepository(db, BookingORM, Booking, "Buchung nicht gefunden")
        self._receivables = BaseRepository(db, ReceivableORM, Receivable, "Forderung nicht gefunden")
        self._invoices = BaseRepository(db, InvoiceORM, Invoice, "Rechnung nicht gefunden")
        self._tax_rates = BaseRepository(db, TaxRateORM, TaxRate, "Steuersatz nicht gefunden")
        self._budgets = BaseRepository(db, BudgetORM, Budget, "Budget nicht gefunden")
        self._escalation_rules = BaseRepository(db, EscalationRuleORM, EscalationRule, "Eskalationsregel nicht gefunden")
        self._insurances = BaseRepository(db, InsuranceORM, Insurance, "Versicherung nicht gefunden")
        self._rent_charges = BaseRepository(db, RentChargeORM, RentCharge, "Sollstellung nicht gefunden")
        self._meters = BaseRepository(db, MeterORM, Meter, "Zähler nicht gefunden")
        self._standalone_readings = BaseRepository(db, StandaloneMeterReadingORM, StandaloneMeterReading, "Ablesung nicht gefunden")
        # Cross-domain references
        self._portfolio_repo = portfolio_repo
        self._tenant_repo = tenant_repo

    def _commit(self):
        self.db.commit()

    # --- Bookings ---
    def list_bookings(self) -> list[Booking]:
        return self._bookings.list_all()

    def create_booking(self, data: BookingCreate) -> Booking:
        pr = self._portfolio_repo
        tr = self._tenant_repo
        if pr and not pr._accounts.exists(data.account_id):
            raise ValidationError("Konto existiert nicht")
        if data.category_id and pr and not pr._categories.exists(data.category_id):
            raise ValidationError("Kategorie existiert nicht")
        if data.property_id and pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        if data.tenant_id and tr and not tr._tenants.exists(data.tenant_id):
            raise ValidationError("Mieter existiert nicht")
        result = self._bookings.create(data)
        self._commit()
        return result

    def get_booking(self, booking_id: str) -> Booking:
        return self._bookings.get(booking_id)

    def update_booking(self, booking_id: str, data: BookingCreate) -> Booking:
        pr = self._portfolio_repo
        tr = self._tenant_repo
        if pr and not pr._accounts.exists(data.account_id):
            raise ValidationError("Konto existiert nicht")
        if data.category_id and pr and not pr._categories.exists(data.category_id):
            raise ValidationError("Kategorie existiert nicht")
        if data.property_id and pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and pr and not pr._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        if data.tenant_id and tr and not tr._tenants.exists(data.tenant_id):
            raise ValidationError("Mieter existiert nicht")
        result = self._bookings.update(booking_id, data)
        self._commit()
        return result

    def delete_booking(self, booking_id: str) -> None:
        self._bookings.delete(booking_id)
        self._commit()

    # --- Receivables ---
    def list_receivables(self) -> list[Receivable]:
        return self._receivables.list_all()

    def create_receivable(self, data: ReceivableCreate) -> Receivable:
        tr = self._tenant_repo
        if tr and not tr._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        result = self._receivables.create(data)
        self._commit()
        return result

    def get_receivable(self, receivable_id: str) -> Receivable:
        return self._receivables.get(receivable_id)

    def update_receivable(self, receivable_id: str, data: ReceivableCreate) -> Receivable:
        tr = self._tenant_repo
        if tr and not tr._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        result = self._receivables.update(receivable_id, data)
        self._commit()
        return result

    def delete_receivable(self, receivable_id: str) -> None:
        self._receivables.delete(receivable_id)
        self._commit()

    # --- Invoices ---
    def list_invoices(self) -> list[Invoice]:
        return self._invoices.list_all()

    def create_invoice(self, data: InvoiceCreate) -> Invoice:
        pr = self._portfolio_repo
        if data.property_id and pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        result = self._invoices.create(data)
        self._commit()
        return result

    def get_invoice(self, invoice_id: str) -> Invoice:
        return self._invoices.get(invoice_id)

    def update_invoice(self, invoice_id: str, data: InvoiceCreate) -> Invoice:
        pr = self._portfolio_repo
        if data.property_id and pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        result = self._invoices.update(invoice_id, data)
        self._commit()
        return result

    def delete_invoice(self, invoice_id: str) -> None:
        self._invoices.delete(invoice_id)
        self._commit()

    # --- Tax Rates ---
    def list_tax_rates(self) -> list[TaxRate]:
        return self._tax_rates.list_all()

    def create_tax_rate(self, data: TaxRateCreate) -> TaxRate:
        result = self._tax_rates.create(data)
        self._commit()
        return result

    def get_tax_rate(self, tax_rate_id: str) -> TaxRate:
        return self._tax_rates.get(tax_rate_id)

    def update_tax_rate(self, tax_rate_id: str, data: TaxRateCreate) -> TaxRate:
        result = self._tax_rates.update(tax_rate_id, data)
        self._commit()
        return result

    def delete_tax_rate(self, tax_rate_id: str) -> None:
        self._tax_rates.delete(tax_rate_id)
        self._commit()

    # --- Budgets ---
    def list_budgets(self) -> list[Budget]:
        return self._budgets.list_all()

    def create_budget(self, data: BudgetCreate) -> Budget:
        pr = self._portfolio_repo
        if pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        result = self._budgets.create(data)
        self._commit()
        return result

    def get_budget(self, budget_id: str) -> Budget:
        return self._budgets.get(budget_id)

    def update_budget(self, budget_id: str, data: BudgetCreate) -> Budget:
        result = self._budgets.update(budget_id, data)
        self._commit()
        return result

    def delete_budget(self, budget_id: str) -> None:
        self._budgets.delete(budget_id)
        self._commit()

    # --- Escalation Rules ---
    def list_escalation_rules(self) -> list[EscalationRule]:
        return self._escalation_rules.list_all()

    def create_escalation_rule(self, data: EscalationRuleCreate) -> EscalationRule:
        result = self._escalation_rules.create(data)
        self._commit()
        return result

    def get_escalation_rule(self, rule_id: str) -> EscalationRule:
        return self._escalation_rules.get(rule_id)

    def update_escalation_rule(self, rule_id: str, data: EscalationRuleCreate) -> EscalationRule:
        result = self._escalation_rules.update(rule_id, data)
        self._commit()
        return result

    def delete_escalation_rule(self, rule_id: str) -> None:
        self._escalation_rules.delete(rule_id)
        self._commit()

    # --- Insurances ---
    def list_insurances(self) -> list[Insurance]:
        return self._insurances.list_all()

    def create_insurance(self, data: InsuranceCreate) -> Insurance:
        pr = self._portfolio_repo
        if pr and not pr._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        result = self._insurances.create(data)
        self._commit()
        return result

    def get_insurance(self, insurance_id: str) -> Insurance:
        return self._insurances.get(insurance_id)

    def update_insurance(self, insurance_id: str, data: InsuranceCreate) -> Insurance:
        result = self._insurances.update(insurance_id, data)
        self._commit()
        return result

    def delete_insurance(self, insurance_id: str) -> None:
        self._insurances.delete(insurance_id)
        self._commit()

    # --- Rent Charges ---
    def list_rent_charges(self) -> list[RentCharge]:
        return self._rent_charges.list_all()

    def create_rent_charge(self, data: RentChargeCreate) -> RentCharge:
        result = self._rent_charges.create(data)
        self._commit()
        return result

    def get_rent_charge(self, charge_id: str) -> RentCharge:
        return self._rent_charges.get(charge_id)

    def update_rent_charge(self, charge_id: str, data: RentChargeCreate) -> RentCharge:
        result = self._rent_charges.update(charge_id, data)
        self._commit()
        return result

    def delete_rent_charge(self, charge_id: str) -> None:
        self._rent_charges.delete(charge_id)
        self._commit()

    # --- Meters ---
    def list_meters(self) -> list[Meter]:
        return self._meters.list_all()

    def create_meter(self, data: MeterCreate) -> Meter:
        result = self._meters.create(data)
        self._commit()
        return result

    def get_meter(self, meter_id: str) -> Meter:
        return self._meters.get(meter_id)

    def update_meter(self, meter_id: str, data: MeterCreate) -> Meter:
        result = self._meters.update(meter_id, data)
        self._commit()
        return result

    def delete_meter(self, meter_id: str) -> None:
        self._meters.delete(meter_id)
        self._commit()

    # --- Standalone Meter Readings ---
    def list_standalone_meter_readings(self) -> list[StandaloneMeterReading]:
        return self._standalone_readings.list_all()

    def create_standalone_meter_reading(self, data: StandaloneMeterReadingCreate) -> StandaloneMeterReading:
        result = self._standalone_readings.create(data)
        self._commit()
        return result

    def get_standalone_meter_reading(self, reading_id: str) -> StandaloneMeterReading:
        return self._standalone_readings.get(reading_id)

    def update_standalone_meter_reading(self, reading_id: str, data: StandaloneMeterReadingCreate) -> StandaloneMeterReading:
        result = self._standalone_readings.update(reading_id, data)
        self._commit()
        return result

    def delete_standalone_meter_reading(self, reading_id: str) -> None:
        self._standalone_readings.delete(reading_id)
        self._commit()
