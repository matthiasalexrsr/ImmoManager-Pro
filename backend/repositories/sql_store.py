"""SQLAlchemy-backed store implementing the same interface as InMemoryStore.

This class provides full database persistence while maintaining API compatibility
with the in-memory store used for testing.
"""

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy.orm import Session

from ..db.orm_models import (
    AccountORM,
    AllocationKeyORM,
    BillingPeriodORM,
    BookingORM,
    BudgetORM,
    CalendarEventORM,
    CategoryORM,
    ChangeHistoryORM,
    ContactORM,
    ContractORM,
    CostItemORM,
    DepositORM,
    DocumentORM,
    EntityPhotoORM,
    EscalationRuleORM,
    HandoverProtocolORM,
    InsuranceORM,
    InvoiceORM,
    LeadORM,
    ListingORM,
    ListingPhotoORM,
    MaintenanceCaseORM,
    MessageORM,
    MessageThreadORM,
    MeterORM,
    MeterReadingORM,
    NotificationORM,
    NotificationTemplateORM,
    PortfolioORM,
    PropertyORM,
    ReceivableORM,
    RentAdjustmentORM,
    RentChargeORM,
    StandaloneMeterReadingORM,
    TaskORM,
    TaxRateORM,
    TenantORM,
    UnitORM,
    UtilityStatementORM,
    ViewingAppointmentORM,
)
from ..models import (
    Account,
    AccountCreate,
    AllocationKey,
    AllocationKeyCreate,
    BillingPeriod,
    BillingPeriodCreate,
    Booking,
    BookingCreate,
    Budget,
    BudgetCreate,
    CalendarEvent,
    CalendarEventCreate,
    Category,
    CategoryCreate,
    ChangeHistoryEntry,
    Contact,
    ContactCreate,
    Contract,
    ContractCreate,
    CostItem,
    CostItemCreate,
    Deposit,
    DepositCreate,
    Document,
    DocumentCreate,
    EntityPhoto,
    EntityPhotoCreate,
    EscalationRule,
    EscalationRuleCreate,
    HandoverProtocol,
    HandoverProtocolCreate,
    Insurance,
    InsuranceCreate,
    Invoice,
    InvoiceCreate,
    Lead,
    LeadCreate,
    Listing,
    ListingCreate,
    ListingPhoto,
    ListingPhotoCreate,
    MaintenanceCase,
    MaintenanceCaseCreate,
    Message,
    MessageCreate,
    MessageThread,
    MessageThreadCreate,
    Meter,
    MeterCreate,
    MeterReading,
    MeterReadingCreate,
    Notification,
    NotificationCreate,
    NotificationTemplate,
    NotificationTemplateCreate,
    Portfolio,
    PortfolioCreate,
    Property,
    PropertyCreate,
    Receivable,
    ReceivableCreate,
    RentAdjustment,
    RentAdjustmentCreate,
    RentCharge,
    RentChargeCreate,
    StandaloneMeterReading,
    StandaloneMeterReadingCreate,
    Task,
    TaskCreate,
    TaxRate,
    TaxRateCreate,
    Tenant,
    TenantCreate,
    Unit,
    UnitCreate,
    UtilityStatement,
    UtilityStatementCreate,
    ViewingAppointment,
    ViewingAppointmentCreate,
)
from ..storage import NotFoundError, ValidationError
from .base import BaseRepository


class SQLAlchemyStore:
    """Database-backed store with the same interface as InMemoryStore."""

    def __init__(self, db: Session):
        self.db = db
        # Initialize base repositories for simple CRUD
        self._portfolios = BaseRepository(db, PortfolioORM, Portfolio, "Portfolio nicht gefunden")
        self._properties = BaseRepository(db, PropertyORM, Property, "Immobilie nicht gefunden")
        self._units = BaseRepository(db, UnitORM, Unit, "Einheit nicht gefunden")
        self._tenants = BaseRepository(db, TenantORM, Tenant, "Mieter nicht gefunden")
        self._contracts = BaseRepository(db, ContractORM, Contract, "Vertrag nicht gefunden")
        self._accounts = BaseRepository(db, AccountORM, Account, "Konto nicht gefunden")
        self._categories = BaseRepository(db, CategoryORM, Category, "Kategorie nicht gefunden")
        self._bookings = BaseRepository(db, BookingORM, Booking, "Buchung nicht gefunden")
        self._receivables = BaseRepository(db, ReceivableORM, Receivable, "Forderung nicht gefunden")
        self._invoices = BaseRepository(db, InvoiceORM, Invoice, "Rechnung nicht gefunden")
        self._maintenance = BaseRepository(
            db, MaintenanceCaseORM, MaintenanceCase, "Instandhaltungsfall nicht gefunden",
        )
        self._documents = BaseRepository(db, DocumentORM, Document, "Dokument nicht gefunden")
        self._tasks = BaseRepository(db, TaskORM, Task, "Aufgabe nicht gefunden")
        self._calendar = BaseRepository(db, CalendarEventORM, CalendarEvent, "Termin nicht gefunden")
        self._listings = BaseRepository(db, ListingORM, Listing, "Inserat nicht gefunden")
        self._listing_photos = BaseRepository(db, ListingPhotoORM, ListingPhoto, "Inseratsfoto nicht gefunden")
        self._leads = BaseRepository(db, LeadORM, Lead, "Interessent nicht gefunden")
        self._viewings = BaseRepository(
            db, ViewingAppointmentORM, ViewingAppointment, "Besichtigungstermin nicht gefunden",
        )
        self._billing_periods = BaseRepository(db, BillingPeriodORM, BillingPeriod, "Abrechnungsperiode nicht gefunden")
        self._allocation_keys = BaseRepository(db, AllocationKeyORM, AllocationKey, "Verteilerschlüssel nicht gefunden")
        self._cost_items = BaseRepository(db, CostItemORM, CostItem, "Kostenposition nicht gefunden")
        self._utility_statements = BaseRepository(
            db, UtilityStatementORM, UtilityStatement, "Betriebskostenabrechnung nicht gefunden",
        )
        self._deposits = BaseRepository(db, DepositORM, Deposit, "Kaution nicht gefunden")
        self._notifications = BaseRepository(db, NotificationORM, Notification, "Benachrichtigung nicht gefunden")
        self._notification_templates = BaseRepository(
            db, NotificationTemplateORM, NotificationTemplate,
            "Benachrichtigungsvorlage nicht gefunden",
        )
        self._tax_rates = BaseRepository(db, TaxRateORM, TaxRate, "Steuersatz nicht gefunden")
        self._rent_adjustments = BaseRepository(db, RentAdjustmentORM, RentAdjustment, "Mietanpassung nicht gefunden")
        self._handover_protocols = BaseRepository(
            db, HandoverProtocolORM, HandoverProtocol, "Übergabeprotokoll nicht gefunden",
        )
        self._meter_readings = BaseRepository(db, MeterReadingORM, MeterReading, "Zählerstand nicht gefunden")
        self._budgets = BaseRepository(db, BudgetORM, Budget, "Budget nicht gefunden")
        self._escalation_rules = BaseRepository(
            db, EscalationRuleORM, EscalationRule, "Eskalationsregel nicht gefunden",
        )
        self._change_history = BaseRepository(
            db, ChangeHistoryORM, ChangeHistoryEntry, "Änderungshistorie nicht gefunden",
        )
        self._insurances = BaseRepository(db, InsuranceORM, Insurance, "Versicherung nicht gefunden")
        self._entity_photos = BaseRepository(db, EntityPhotoORM, EntityPhoto, "Foto nicht gefunden")
        self._contacts = BaseRepository(db, ContactORM, Contact, "Kontakt nicht gefunden")
        self._meters = BaseRepository(db, MeterORM, Meter, "Zähler nicht gefunden")
        self._standalone_readings = BaseRepository(
            db, StandaloneMeterReadingORM, StandaloneMeterReading, "Ablesung nicht gefunden",
        )
        self._message_threads = BaseRepository(
            db, MessageThreadORM, MessageThread, "Thread nicht gefunden",
        )
        self._messages = BaseRepository(db, MessageORM, Message, "Nachricht nicht gefunden")
        self._rent_charges = BaseRepository(db, RentChargeORM, RentCharge, "Sollstellung nicht gefunden")

    def _commit(self):
        self.db.commit()

    # --- Portfolios ---

    def list_portfolios(self) -> list[Portfolio]:
        return self._portfolios.list_all()

    def create_portfolio(self, data: PortfolioCreate) -> Portfolio:
        result = self._portfolios.create(data)
        self._commit()
        return result

    def get_portfolio(self, portfolio_id: str) -> Portfolio:
        return self._portfolios.get(portfolio_id)

    def update_portfolio(self, portfolio_id: str, data: PortfolioCreate) -> Portfolio:
        result = self._portfolios.update(portfolio_id, data)
        self._commit()
        return result

    def delete_portfolio(self, portfolio_id: str) -> None:
        # Cascade handled by DB foreign keys (ondelete=CASCADE)
        self._portfolios.delete(portfolio_id)
        self._commit()

    # --- Accounts ---

    def list_accounts(self) -> list[Account]:
        return self._accounts.list_all()

    def create_account(self, data: AccountCreate) -> Account:
        if not self._portfolios.exists(data.portfolio_id):
            raise ValidationError("Portfolio existiert nicht")
        result = self._accounts.create(data)
        self._commit()
        return result

    def get_account(self, account_id: str) -> Account:
        return self._accounts.get(account_id)

    def update_account(self, account_id: str, data: AccountCreate) -> Account:
        if not self._portfolios.exists(data.portfolio_id):
            raise ValidationError("Portfolio existiert nicht")
        result = self._accounts.update(account_id, data)
        self._commit()
        return result

    def delete_account(self, account_id: str) -> None:
        self._accounts.delete(account_id)
        self._commit()

    # --- Categories ---

    def list_categories(self) -> list[Category]:
        return self._categories.list_all()

    def create_category(self, data: CategoryCreate) -> Category:
        if not self._portfolios.exists(data.portfolio_id):
            raise ValidationError("Portfolio existiert nicht")
        result = self._categories.create(data)
        self._commit()
        return result

    def get_category(self, category_id: str) -> Category:
        return self._categories.get(category_id)

    def update_category(self, category_id: str, data: CategoryCreate) -> Category:
        if not self._portfolios.exists(data.portfolio_id):
            raise ValidationError("Portfolio existiert nicht")
        result = self._categories.update(category_id, data)
        self._commit()
        return result

    def delete_category(self, category_id: str) -> None:
        # Set category_id to NULL on bookings (handled by DB SET NULL)
        self._categories.delete(category_id)
        self._commit()

    # --- Properties ---

    def list_properties(self) -> list[Property]:
        return self._properties.list_all()

    def create_property(self, data: PropertyCreate) -> Property:
        if not self._portfolios.exists(data.portfolio_id):
            raise ValidationError("Portfolio existiert nicht")
        result = self._properties.create(data)
        self._commit()
        return result

    def get_property(self, property_id: str) -> Property:
        return self._properties.get(property_id)

    def update_property(self, property_id: str, data: PropertyCreate) -> Property:
        if not self._portfolios.exists(data.portfolio_id):
            raise ValidationError("Portfolio existiert nicht")
        result = self._properties.update(property_id, data)
        self._commit()
        return result

    def delete_property(self, property_id: str) -> None:
        # Cascade handled by DB foreign keys
        self._properties.delete(property_id)
        self._commit()

    # --- Units ---

    def list_units(self) -> list[Unit]:
        return self._units.list_all()

    def create_unit(self, data: UnitCreate) -> Unit:
        if not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        result = self._units.create(data)
        self._commit()
        return result

    def get_unit(self, unit_id: str) -> Unit:
        return self._units.get(unit_id)

    def update_unit(self, unit_id: str, data: UnitCreate) -> Unit:
        if not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        result = self._units.update(unit_id, data)
        self._commit()
        return result

    def delete_unit(self, unit_id: str) -> None:
        self._units.delete(unit_id)
        self._commit()

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
        if not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        if not self._tenants.exists(data.tenant_id):
            raise ValidationError("Mieter existiert nicht")
        # Verify unit belongs to property
        unit = self._units.get(data.unit_id)
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
        if not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        if not self._tenants.exists(data.tenant_id):
            raise ValidationError("Mieter existiert nicht")
        unit = self._units.get(data.unit_id)
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

    # --- Bookings ---

    def list_bookings(self) -> list[Booking]:
        return self._bookings.list_all()

    def create_booking(self, data: BookingCreate) -> Booking:
        if not self._accounts.exists(data.account_id):
            raise ValidationError("Konto existiert nicht")
        if data.category_id and not self._categories.exists(data.category_id):
            raise ValidationError("Kategorie existiert nicht")
        if data.property_id and not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        if data.tenant_id and not self._tenants.exists(data.tenant_id):
            raise ValidationError("Mieter existiert nicht")
        result = self._bookings.create(data)
        self._commit()
        return result

    def get_booking(self, booking_id: str) -> Booking:
        return self._bookings.get(booking_id)

    def update_booking(self, booking_id: str, data: BookingCreate) -> Booking:
        if not self._accounts.exists(data.account_id):
            raise ValidationError("Konto existiert nicht")
        if data.category_id and not self._categories.exists(data.category_id):
            raise ValidationError("Kategorie existiert nicht")
        if data.property_id and not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        if data.tenant_id and not self._tenants.exists(data.tenant_id):
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
        if not self._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        result = self._receivables.create(data)
        self._commit()
        return result

    def get_receivable(self, receivable_id: str) -> Receivable:
        return self._receivables.get(receivable_id)

    def update_receivable(self, receivable_id: str, data: ReceivableCreate) -> Receivable:
        if not self._contracts.exists(data.contract_id):
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
        if data.property_id and not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        result = self._invoices.create(data)
        self._commit()
        return result

    def get_invoice(self, invoice_id: str) -> Invoice:
        return self._invoices.get(invoice_id)

    def update_invoice(self, invoice_id: str, data: InvoiceCreate) -> Invoice:
        if data.property_id and not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        result = self._invoices.update(invoice_id, data)
        self._commit()
        return result

    def delete_invoice(self, invoice_id: str) -> None:
        self._invoices.delete(invoice_id)
        self._commit()

    # --- Maintenance Cases ---

    def list_maintenance_cases(self) -> list[MaintenanceCase]:
        return self._maintenance.list_all()

    def create_maintenance_case(self, data: MaintenanceCaseCreate) -> MaintenanceCase:
        if not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._maintenance.create(data)
        self._commit()
        return result

    def get_maintenance_case(self, case_id: str) -> MaintenanceCase:
        return self._maintenance.get(case_id)

    def update_maintenance_case(self, case_id: str, data: MaintenanceCaseCreate) -> MaintenanceCase:
        if not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._maintenance.update(case_id, data)
        self._commit()
        return result

    def delete_maintenance_case(self, case_id: str) -> None:
        self._maintenance.delete(case_id)
        self._commit()

    # --- Documents ---

    def list_documents(self) -> list[Document]:
        return self._documents.list_all()

    def create_document(self, data: DocumentCreate) -> Document:
        if data.property_id and not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        if data.contract_id and not self._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        result = self._documents.create(data)
        self._commit()
        return result

    def get_document(self, document_id: str) -> Document:
        return self._documents.get(document_id)

    def update_document(self, document_id: str, data: DocumentCreate) -> Document:
        if data.property_id and not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        if data.contract_id and not self._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        result = self._documents.update(document_id, data)
        self._commit()
        return result

    def delete_document(self, document_id: str) -> None:
        self._documents.delete(document_id)
        self._commit()

    # --- Tasks ---

    def list_tasks(self) -> list[Task]:
        return self._tasks.list_all()

    def create_task(self, data: TaskCreate) -> Task:
        if data.property_id and not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._tasks.create(data)
        self._commit()
        return result

    def get_task(self, task_id: str) -> Task:
        return self._tasks.get(task_id)

    def update_task(self, task_id: str, data: TaskCreate) -> Task:
        if data.property_id and not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._tasks.update(task_id, data)
        self._commit()
        return result

    def delete_task(self, task_id: str) -> None:
        self._tasks.delete(task_id)
        self._commit()

    # --- Calendar Events ---

    def list_calendar_events(self) -> list[CalendarEvent]:
        return self._calendar.list_all()

    def create_calendar_event(self, data: CalendarEventCreate) -> CalendarEvent:
        if data.property_id and not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._calendar.create(data)
        self._commit()
        return result

    def get_calendar_event(self, event_id: str) -> CalendarEvent:
        return self._calendar.get(event_id)

    def update_calendar_event(self, event_id: str, data: CalendarEventCreate) -> CalendarEvent:
        if data.property_id and not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._calendar.update(event_id, data)
        self._commit()
        return result

    def delete_calendar_event(self, event_id: str) -> None:
        self._calendar.delete(event_id)
        self._commit()

    # --- Listings ---

    def list_listings(self) -> list[Listing]:
        return self._listings.list_all()

    def create_listing(self, data: ListingCreate) -> Listing:
        if not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._listings.create(data)
        self._commit()
        return result

    def get_listing(self, listing_id: str) -> Listing:
        return self._listings.get(listing_id)

    def update_listing(self, listing_id: str, data: ListingCreate) -> Listing:
        if not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._listings.update(listing_id, data)
        self._commit()
        return result

    def delete_listing(self, listing_id: str) -> None:
        # Photos cascade via DB FK
        self._listings.delete(listing_id)
        self._commit()

    # --- Listing Photos ---

    def list_listing_photos(self) -> list[ListingPhoto]:
        return self._listing_photos.list_all()

    def create_listing_photo(self, data: ListingPhotoCreate) -> ListingPhoto:
        if not self._listings.exists(data.listing_id):
            raise ValidationError("Inserat existiert nicht")
        result = self._listing_photos.create(data)
        self._commit()
        return result

    def get_listing_photo(self, photo_id: str) -> ListingPhoto:
        return self._listing_photos.get(photo_id)

    def update_listing_photo(self, photo_id: str, data: ListingPhotoCreate) -> ListingPhoto:
        if not self._listings.exists(data.listing_id):
            raise ValidationError("Inserat existiert nicht")
        result = self._listing_photos.update(photo_id, data)
        self._commit()
        return result

    def delete_listing_photo(self, photo_id: str) -> None:
        self._listing_photos.delete(photo_id)
        self._commit()

    # --- Leads ---

    def list_leads(self) -> list[Lead]:
        return self._leads.list_all()

    def create_lead(self, data: LeadCreate) -> Lead:
        if data.listing_id and not self._listings.exists(data.listing_id):
            raise ValidationError("Inserat existiert nicht")
        if data.unit_id and not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._leads.create(data)
        self._commit()
        return result

    def get_lead(self, lead_id: str) -> Lead:
        return self._leads.get(lead_id)

    def update_lead(self, lead_id: str, data: LeadCreate) -> Lead:
        if data.listing_id and not self._listings.exists(data.listing_id):
            raise ValidationError("Inserat existiert nicht")
        if data.unit_id and not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._leads.update(lead_id, data)
        self._commit()
        return result

    def delete_lead(self, lead_id: str) -> None:
        # Viewing appointments cascade via DB FK
        self._leads.delete(lead_id)
        self._commit()

    # --- Viewing Appointments ---

    def list_viewing_appointments(self) -> list[ViewingAppointment]:
        return self._viewings.list_all()

    def create_viewing_appointment(self, data: ViewingAppointmentCreate) -> ViewingAppointment:
        if not self._leads.exists(data.lead_id):
            raise ValidationError("Interessent existiert nicht")
        if not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._viewings.create(data)
        self._commit()
        return result

    def get_viewing_appointment(self, appointment_id: str) -> ViewingAppointment:
        return self._viewings.get(appointment_id)

    def update_viewing_appointment(self, appointment_id: str, data: ViewingAppointmentCreate) -> ViewingAppointment:
        if not self._leads.exists(data.lead_id):
            raise ValidationError("Interessent existiert nicht")
        if not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._viewings.update(appointment_id, data)
        self._commit()
        return result

    def delete_viewing_appointment(self, appointment_id: str) -> None:
        self._viewings.delete(appointment_id)
        self._commit()

    # --- Billing Periods ---

    def list_billing_periods(self) -> list[BillingPeriod]:
        return self._billing_periods.list_all()

    def create_billing_period(self, data: BillingPeriodCreate) -> BillingPeriod:
        if not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.end_date <= data.start_date:
            raise ValidationError("Enddatum muss nach Startdatum liegen")
        result = self._billing_periods.create(data)
        self._commit()
        return result

    def get_billing_period(self, period_id: str) -> BillingPeriod:
        return self._billing_periods.get(period_id)

    def update_billing_period(self, period_id: str, data: BillingPeriodCreate) -> BillingPeriod:
        if not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        if data.end_date <= data.start_date:
            raise ValidationError("Enddatum muss nach Startdatum liegen")
        result = self._billing_periods.update(period_id, data)
        self._commit()
        return result

    def delete_billing_period(self, period_id: str) -> None:
        # Cost items and utility statements cascade via DB FK
        self._billing_periods.delete(period_id)
        self._commit()

    # --- Allocation Keys ---

    def list_allocation_keys(self) -> list[AllocationKey]:
        return self._allocation_keys.list_all()

    def create_allocation_key(self, data: AllocationKeyCreate) -> AllocationKey:
        if not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        result = self._allocation_keys.create(data)
        self._commit()
        return result

    def get_allocation_key(self, key_id: str) -> AllocationKey:
        return self._allocation_keys.get(key_id)

    def update_allocation_key(self, key_id: str, data: AllocationKeyCreate) -> AllocationKey:
        if not self._properties.exists(data.property_id):
            raise ValidationError("Immobilie existiert nicht")
        result = self._allocation_keys.update(key_id, data)
        self._commit()
        return result

    def delete_allocation_key(self, key_id: str) -> None:
        # Cost items cascade via DB FK
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
        if not self._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        if not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._utility_statements.create(data)
        self._commit()
        return result

    def get_utility_statement(self, statement_id: str) -> UtilityStatement:
        return self._utility_statements.get(statement_id)

    def update_utility_statement(self, statement_id: str, data: UtilityStatementCreate) -> UtilityStatement:
        if not self._billing_periods.exists(data.billing_period_id):
            raise ValidationError("Abrechnungsperiode existiert nicht")
        if not self._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        if not self._units.exists(data.unit_id):
            raise ValidationError("Einheit existiert nicht")
        result = self._utility_statements.update(statement_id, data)
        self._commit()
        return result

    def delete_utility_statement(self, statement_id: str) -> None:
        self._utility_statements.delete(statement_id)
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

    # --- Notifications ---

    def list_notifications(self) -> list[Notification]:
        return self._notifications.list_all()

    def create_notification(self, data: NotificationCreate) -> Notification:
        result = self._notifications.create(data)
        self._commit()
        return result

    def get_notification(self, notification_id: str) -> Notification:
        return self._notifications.get(notification_id)

    def mark_notification_read(self, notification_id: str) -> Notification:
        orm_obj = self.db.get(NotificationORM, notification_id)
        if orm_obj is None:
            raise NotFoundError("Benachrichtigung nicht gefunden")
        orm_obj.status = "read"
        orm_obj.read_at = datetime.now(timezone.utc)
        orm_obj.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        self.db.refresh(orm_obj)
        self._commit()
        return self._notifications._to_pydantic(orm_obj)

    def delete_notification(self, notification_id: str) -> None:
        self._notifications.delete(notification_id)
        self._commit()

    # --- Notification Templates ---

    def list_notification_templates(self) -> list[NotificationTemplate]:
        return self._notification_templates.list_all()

    def create_notification_template(self, data: NotificationTemplateCreate) -> NotificationTemplate:
        result = self._notification_templates.create(data)
        self._commit()
        return result

    def get_notification_template(self, template_id: str) -> NotificationTemplate:
        return self._notification_templates.get(template_id)

    def update_notification_template(self, template_id: str, data: NotificationTemplateCreate) -> NotificationTemplate:
        result = self._notification_templates.update(template_id, data)
        self._commit()
        return result

    def delete_notification_template(self, template_id: str) -> None:
        self._notification_templates.delete(template_id)
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

    # --- Handover Protocols ---

    def list_handover_protocols(self) -> list[HandoverProtocol]:
        return self._handover_protocols.list_all()

    def create_handover_protocol(self, data: HandoverProtocolCreate) -> HandoverProtocol:
        if not self._contracts.exists(data.contract_id):
            raise ValidationError("Vertrag existiert nicht")
        if not self._units.exists(data.unit_id):
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

    # --- Meter Readings ---

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

    # --- Budgets ---

    def list_budgets(self) -> list[Budget]:
        return self._budgets.list_all()

    def create_budget(self, data: BudgetCreate) -> Budget:
        if not self._properties.exists(data.property_id):
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

    # --- Change History ---

    def list_change_history(self) -> list[ChangeHistoryEntry]:
        return self._change_history.list_all()

    def add_change_history(
        self,
        entity_type: str,
        entity_id: str,
        field_name: str,
        old_value: str | None,
        new_value: str | None,
        changed_by: str | None = None,
        reason: str | None = None,
    ) -> ChangeHistoryEntry:
        entry = ChangeHistoryORM(
            id=str(uuid4()),
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
            reason=reason,
        )
        self.db.add(entry)
        self.db.flush()
        self.db.refresh(entry)
        self._commit()
        return self._change_history.get(entry.id)

    def get_entity_history(self, entity_type: str, entity_id: str) -> list[ChangeHistoryEntry]:
        return self._change_history.filter_by(entity_type=entity_type, entity_id=entity_id)

    # --- Insurances ---

    def list_insurances(self) -> list[Insurance]:
        return self._insurances.list_all()

    def create_insurance(self, data: InsuranceCreate) -> Insurance:
        if not self._properties.exists(data.property_id):
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

    # --- Entity Photos ---

    def list_entity_photos(self, entity_type: str, entity_id: str) -> list[EntityPhoto]:
        return self._entity_photos.filter_by(entity_type=entity_type, entity_id=entity_id)

    def create_entity_photo(self, data: EntityPhotoCreate) -> EntityPhoto:
        result = self._entity_photos.create(data)
        self._commit()
        return result

    def get_entity_photo(self, photo_id: str) -> EntityPhoto:
        return self._entity_photos.get(photo_id)

    def delete_entity_photo(self, photo_id: str) -> None:
        self._entity_photos.delete(photo_id)
        self._commit()

    # --- Contacts ---

    def list_contacts(self) -> list[Contact]:
        return self._contacts.list_all()

    def create_contact(self, data: ContactCreate) -> Contact:
        result = self._contacts.create(data)
        self._commit()
        return result

    def get_contact(self, contact_id: str) -> Contact:
        return self._contacts.get(contact_id)

    def update_contact(self, contact_id: str, data: ContactCreate) -> Contact:
        result = self._contacts.update(contact_id, data)
        self._commit()
        return result

    def delete_contact(self, contact_id: str) -> None:
        self._contacts.delete(contact_id)
        self._commit()

    # --- Meters (standalone meter management) ---

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

    # --- Message Threads ---

    def list_message_threads(self) -> list[MessageThread]:
        return self._message_threads.list_all()

    def create_message_thread(self, data: MessageThreadCreate) -> MessageThread:
        result = self._message_threads.create(data)
        self._commit()
        return result

    def get_message_thread(self, thread_id: str) -> MessageThread:
        return self._message_threads.get(thread_id)

    def update_message_thread(self, thread_id: str, data: MessageThreadCreate) -> MessageThread:
        result = self._message_threads.update(thread_id, data)
        self._commit()
        return result

    def delete_message_thread(self, thread_id: str) -> None:
        # Cascade delete of messages handled by DB FK (ondelete=CASCADE)
        self._message_threads.delete(thread_id)
        self._commit()

    # --- Messages ---

    def list_messages(self) -> list[Message]:
        return self._messages.list_all()

    def create_message(self, data: MessageCreate) -> Message:
        result = self._messages.create(data)
        # Update thread stats
        try:
            thread_orm = self.db.query(MessageThreadORM).filter(
                MessageThreadORM.id == data.thread_id
            ).first()
            if thread_orm:
                thread_orm.message_count = (thread_orm.message_count or 0) + 1
                thread_orm.last_message_at = datetime.now(timezone.utc)
        except Exception:
            pass
        self._commit()
        return result

    def get_message(self, message_id: str) -> Message:
        return self._messages.get(message_id)

    def delete_message(self, message_id: str) -> None:
        self._messages.delete(message_id)
        self._commit()

    # --- Rent Charges (Sollstellung) ---

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

    # --- Generic patch (mirrors InMemoryStore._patch_entity) ---

    _ENTITY_TYPE_MAP = {
        "portfolio": "_portfolios",
        "property": "_properties",
        "unit": "_units",
        "tenant": "_tenants",
        "contract": "_contracts",
        "account": "_accounts",
        "category": "_categories",
        "booking": "_bookings",
        "receivable": "_receivables",
        "invoice": "_invoices",
        "maintenance": "_maintenance",
        "document": "_documents",
        "task": "_tasks",
        "calendar": "_calendar",
        "listing": "_listings",
        "listing_photo": "_listing_photos",
        "lead": "_leads",
        "viewing": "_viewings",
        "billing_period": "_billing_periods",
        "allocation_key": "_allocation_keys",
        "cost_item": "_cost_items",
        "utility_statement": "_utility_statements",
        "deposit": "_deposits",
        "notification": "_notifications",
        "notification_template": "_notification_templates",
        "tax_rate": "_tax_rates",
        "rent_adjustment": "_rent_adjustments",
        "handover_protocol": "_handover_protocols",
        "meter_reading": "_meter_readings",
        "budget": "_budgets",
        "escalation_rule": "_escalation_rules",
        "insurance": "_insurances",
        "entity_photo": "_entity_photos",
        "contact": "_contacts",
        "meter": "_meters",
        "standalone_reading": "_standalone_readings",
        "message_thread": "_message_threads",
        "message": "_messages",
        "rent_charge": "_rent_charges",
    }

    def _patch_entity(self, entity_type: str, entity_id: str, patch: PydanticBaseModel):
        """Apply a partial update using the entity type string to resolve the repository."""
        attr_name = self._ENTITY_TYPE_MAP.get(entity_type)
        if attr_name is None:
            raise ValueError(f"Unknown entity type: {entity_type}")
        repo = getattr(self, attr_name)
        result = repo.patch(entity_id, patch)
        self._commit()
        return result

    def _list_paginated(
        self,
        entity_type: str,
        skip: int = 0,
        limit: int = 100,
        filters: dict | None = None,
        order_by: str | None = None,
        order_desc: bool = False,
    ) -> list:
        """Generic paginated list using entity type to resolve the repository."""
        attr_name = self._ENTITY_TYPE_MAP.get(entity_type)
        if attr_name is None:
            raise ValueError(f"Unknown entity type: {entity_type}")
        repo = getattr(self, attr_name)
        return repo.list_paginated(
            skip=skip, limit=limit, filters=filters,
            order_by=order_by, order_desc=order_desc,
        )

    def _count(self, entity_type: str, filters: dict | None = None) -> int:
        """Generic count using entity type to resolve the repository."""
        attr_name = self._ENTITY_TYPE_MAP.get(entity_type)
        if attr_name is None:
            raise ValueError(f"Unknown entity type: {entity_type}")
        repo = getattr(self, attr_name)
        return repo.count(filters=filters)
