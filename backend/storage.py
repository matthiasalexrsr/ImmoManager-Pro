from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List
from uuid import uuid4

from pydantic import BaseModel as PydanticBaseModel

from .models import (
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


class NotFoundError(KeyError):
    pass


class ValidationError(ValueError):
    pass


def _generate_id() -> str:
    return str(uuid4())


@dataclass
class InMemoryStore:
    accounts: Dict[str, Account] = field(default_factory=dict)
    bookings: Dict[str, Booking] = field(default_factory=dict)
    calendar_events: Dict[str, CalendarEvent] = field(default_factory=dict)
    categories: Dict[str, Category] = field(default_factory=dict)
    portfolios: Dict[str, Portfolio] = field(default_factory=dict)
    properties: Dict[str, Property] = field(default_factory=dict)
    units: Dict[str, Unit] = field(default_factory=dict)
    documents: Dict[str, Document] = field(default_factory=dict)
    invoices: Dict[str, Invoice] = field(default_factory=dict)
    maintenance_cases: Dict[str, MaintenanceCase] = field(default_factory=dict)
    receivables: Dict[str, Receivable] = field(default_factory=dict)
    tasks: Dict[str, Task] = field(default_factory=dict)
    tenants: Dict[str, Tenant] = field(default_factory=dict)
    contracts: Dict[str, Contract] = field(default_factory=dict)
    listings: Dict[str, Listing] = field(default_factory=dict)
    listing_photos: Dict[str, ListingPhoto] = field(default_factory=dict)
    leads: Dict[str, Lead] = field(default_factory=dict)
    viewing_appointments: Dict[str, ViewingAppointment] = field(default_factory=dict)
    billing_periods: Dict[str, BillingPeriod] = field(default_factory=dict)
    allocation_keys: Dict[str, AllocationKey] = field(default_factory=dict)
    cost_items: Dict[str, CostItem] = field(default_factory=dict)
    utility_statements: Dict[str, UtilityStatement] = field(default_factory=dict)
    deposits: Dict[str, Deposit] = field(default_factory=dict)
    notifications: Dict[str, Notification] = field(default_factory=dict)
    notification_templates: Dict[str, NotificationTemplate] = field(default_factory=dict)
    tax_rates: Dict[str, TaxRate] = field(default_factory=dict)
    rent_adjustments: Dict[str, RentAdjustment] = field(default_factory=dict)
    handover_protocols: Dict[str, HandoverProtocol] = field(default_factory=dict)
    meter_readings: Dict[str, MeterReading] = field(default_factory=dict)
    change_history: Dict[str, ChangeHistoryEntry] = field(default_factory=dict)
    budgets: Dict[str, Budget] = field(default_factory=dict)
    escalation_rules: Dict[str, EscalationRule] = field(default_factory=dict)
    contacts: Dict[str, Contact] = field(default_factory=dict)
    meters: Dict[str, Meter] = field(default_factory=dict)
    standalone_meter_readings: Dict[str, StandaloneMeterReading] = field(default_factory=dict)
    message_threads: Dict[str, MessageThread] = field(default_factory=dict)
    messages: Dict[str, Message] = field(default_factory=dict)
    rent_charges: Dict[str, RentCharge] = field(default_factory=dict)
    insurances: Dict[str, Insurance] = field(default_factory=dict)
    entity_photos: Dict[str, EntityPhoto] = field(default_factory=dict)

    def list_portfolios(self) -> List[Portfolio]:
        return list(self.portfolios.values())

    def create_portfolio(self, data: PortfolioCreate) -> Portfolio:
        portfolio = Portfolio(id=_generate_id(), **data.model_dump())
        self.portfolios[portfolio.id] = portfolio
        return portfolio

    def get_portfolio(self, portfolio_id: str) -> Portfolio:
        try:
            return self.portfolios[portfolio_id]
        except KeyError as exc:
            raise NotFoundError("Portfolio nicht gefunden") from exc

    def update_portfolio(self, portfolio_id: str, data: PortfolioCreate) -> Portfolio:
        if portfolio_id not in self.portfolios:
            raise NotFoundError("Portfolio nicht gefunden")
        old = self.portfolios[portfolio_id]
        portfolio = Portfolio(
            id=portfolio_id, created_at=old.created_at,
            updated_at=datetime.now(timezone.utc), **data.model_dump(),
        )
        self.portfolios[portfolio_id] = portfolio
        return portfolio

    def delete_portfolio(self, portfolio_id: str) -> None:
        if portfolio_id not in self.portfolios:
            raise NotFoundError("Portfolio nicht gefunden")
        property_ids = {prop.id for prop in self.properties.values() if prop.portfolio_id == portfolio_id}
        account_ids = {acc.id for acc in self.accounts.values() if acc.portfolio_id == portfolio_id}
        category_ids = {cat.id for cat in self.categories.values() if cat.portfolio_id == portfolio_id}
        self._delete_properties(property_ids)
        self._delete_accounts(account_ids)
        self._delete_categories(category_ids)
        del self.portfolios[portfolio_id]

    def list_accounts(self) -> List[Account]:
        return list(self.accounts.values())

    def create_account(self, data: AccountCreate) -> Account:
        if data.portfolio_id not in self.portfolios:
            raise ValidationError("Portfolio existiert nicht")
        account = Account(id=_generate_id(), **data.model_dump())
        self.accounts[account.id] = account
        return account

    def get_account(self, account_id: str) -> Account:
        try:
            return self.accounts[account_id]
        except KeyError as exc:
            raise NotFoundError("Konto nicht gefunden") from exc

    def list_categories(self) -> List[Category]:
        return list(self.categories.values())

    def create_category(self, data: CategoryCreate) -> Category:
        if data.portfolio_id not in self.portfolios:
            raise ValidationError("Portfolio existiert nicht")
        category = Category(id=_generate_id(), **data.model_dump())
        self.categories[category.id] = category
        return category

    def get_category(self, category_id: str) -> Category:
        try:
            return self.categories[category_id]
        except KeyError as exc:
            raise NotFoundError("Kategorie nicht gefunden") from exc

    def update_category(self, category_id: str, data: CategoryCreate) -> Category:
        if category_id not in self.categories:
            raise NotFoundError("Kategorie nicht gefunden")
        if data.portfolio_id not in self.portfolios:
            raise ValidationError("Portfolio existiert nicht")
        old = self.categories[category_id]
        category = Category(
            id=category_id, created_at=old.created_at,
            updated_at=datetime.now(timezone.utc), **data.model_dump(),
        )
        self.categories[category_id] = category
        return category

    def delete_category(self, category_id: str) -> None:
        if category_id not in self.categories:
            raise NotFoundError("Kategorie nicht gefunden")
        for booking_id, booking in list(self.bookings.items()):
            if booking.category_id == category_id:
                updated = booking.model_copy(update={"category_id": None})
                self.bookings[booking_id] = updated
        del self.categories[category_id]

    def update_account(self, account_id: str, data: AccountCreate) -> Account:
        if account_id not in self.accounts:
            raise NotFoundError("Konto nicht gefunden")
        if data.portfolio_id not in self.portfolios:
            raise ValidationError("Portfolio existiert nicht")
        old = self.accounts[account_id]
        account = Account(id=account_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.accounts[account_id] = account
        return account

    def delete_account(self, account_id: str) -> None:
        if account_id not in self.accounts:
            raise NotFoundError("Konto nicht gefunden")
        for booking_id, booking in list(self.bookings.items()):
            if booking.account_id == account_id:
                del self.bookings[booking_id]
        del self.accounts[account_id]

    def list_properties(self) -> List[Property]:
        return list(self.properties.values())

    def create_property(self, data: PropertyCreate) -> Property:
        if data.portfolio_id not in self.portfolios:
            raise ValidationError("Portfolio existiert nicht")
        property_item = Property(id=_generate_id(), **data.model_dump())
        self.properties[property_item.id] = property_item
        return property_item

    def get_property(self, property_id: str) -> Property:
        try:
            return self.properties[property_id]
        except KeyError as exc:
            raise NotFoundError("Immobilie nicht gefunden") from exc

    def update_property(self, property_id: str, data: PropertyCreate) -> Property:
        if property_id not in self.properties:
            raise NotFoundError("Immobilie nicht gefunden")
        if data.portfolio_id not in self.portfolios:
            raise ValidationError("Portfolio existiert nicht")
        old = self.properties[property_id]
        property_item = Property(
            id=property_id, created_at=old.created_at,
            updated_at=datetime.now(timezone.utc), **data.model_dump(),
        )
        self.properties[property_id] = property_item
        return property_item

    def delete_property(self, property_id: str) -> None:
        if property_id not in self.properties:
            raise NotFoundError("Immobilie nicht gefunden")
        unit_ids = {unit.id for unit in self.units.values() if unit.property_id == property_id}
        self._delete_units(unit_ids)
        for contract_id, contract in list(self.contracts.items()):
            if contract.property_id == property_id:
                self._delete_contract(contract_id)
        for booking_id, booking in list(self.bookings.items()):
            if booking.property_id == property_id:
                del self.bookings[booking_id]
        for invoice_id, invoice in list(self.invoices.items()):
            if invoice.property_id == property_id:
                del self.invoices[invoice_id]
        for case_id, case in list(self.maintenance_cases.items()):
            if case.property_id == property_id:
                del self.maintenance_cases[case_id]
        for document_id, document in list(self.documents.items()):
            if document.property_id == property_id:
                del self.documents[document_id]
        for task_id, task in list(self.tasks.items()):
            if task.property_id == property_id:
                del self.tasks[task_id]
        for event_id, event in list(self.calendar_events.items()):
            if event.property_id == property_id:
                del self.calendar_events[event_id]
        del self.properties[property_id]

    def list_units(self) -> List[Unit]:
        return list(self.units.values())

    def create_unit(self, data: UnitCreate) -> Unit:
        if data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        unit = Unit(id=_generate_id(), **data.model_dump())
        self.units[unit.id] = unit
        return unit

    def get_unit(self, unit_id: str) -> Unit:
        try:
            return self.units[unit_id]
        except KeyError as exc:
            raise NotFoundError("Einheit nicht gefunden") from exc

    def update_unit(self, unit_id: str, data: UnitCreate) -> Unit:
        if unit_id not in self.units:
            raise NotFoundError("Einheit nicht gefunden")
        if data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        old = self.units[unit_id]
        unit = Unit(id=unit_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.units[unit_id] = unit
        return unit

    def delete_unit(self, unit_id: str) -> None:
        if unit_id not in self.units:
            raise NotFoundError("Einheit nicht gefunden")
        for contract_id, contract in list(self.contracts.items()):
            if contract.unit_id == unit_id:
                self._delete_contract(contract_id)
        for booking_id, booking in list(self.bookings.items()):
            if booking.unit_id == unit_id:
                del self.bookings[booking_id]
        for case_id, case in list(self.maintenance_cases.items()):
            if case.unit_id == unit_id:
                del self.maintenance_cases[case_id]
        for document_id, document in list(self.documents.items()):
            if document.unit_id == unit_id:
                del self.documents[document_id]
        for task_id, task in list(self.tasks.items()):
            if task.unit_id == unit_id:
                del self.tasks[task_id]
        for event_id, event in list(self.calendar_events.items()):
            if event.unit_id == unit_id:
                del self.calendar_events[event_id]
        for listing_id, listing in list(self.listings.items()):
            if listing.unit_id == unit_id:
                self.delete_listing(listing_id)
        del self.units[unit_id]

    def list_tenants(self) -> List[Tenant]:
        return list(self.tenants.values())

    def create_tenant(self, data: TenantCreate) -> Tenant:
        tenant = Tenant(id=_generate_id(), **data.model_dump())
        self.tenants[tenant.id] = tenant
        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant:
        try:
            return self.tenants[tenant_id]
        except KeyError as exc:
            raise NotFoundError("Mieter nicht gefunden") from exc

    def update_tenant(self, tenant_id: str, data: TenantCreate) -> Tenant:
        if tenant_id not in self.tenants:
            raise NotFoundError("Mieter nicht gefunden")
        old = self.tenants[tenant_id]
        tenant = Tenant(id=tenant_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.tenants[tenant_id] = tenant
        return tenant

    def delete_tenant(self, tenant_id: str) -> None:
        if tenant_id not in self.tenants:
            raise NotFoundError("Mieter nicht gefunden")
        for contract_id, contract in list(self.contracts.items()):
            if contract.tenant_id == tenant_id:
                self._delete_contract(contract_id)
        for booking_id, booking in list(self.bookings.items()):
            if booking.tenant_id == tenant_id:
                del self.bookings[booking_id]
        del self.tenants[tenant_id]

    def list_contracts(self) -> List[Contract]:
        return list(self.contracts.values())

    def create_contract(self, data: ContractCreate) -> Contract:
        if data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        if data.tenant_id not in self.tenants:
            raise ValidationError("Mieter existiert nicht")
        if self.units[data.unit_id].property_id != data.property_id:
            raise ValidationError("Einheit gehört nicht zur Immobilie")
        if any(contract.contract_number == data.contract_number for contract in self.contracts.values()):
            raise ValidationError("Vertragsnummer existiert bereits")
        contract = Contract(id=_generate_id(), **data.model_dump())
        self.contracts[contract.id] = contract
        return contract

    def get_contract(self, contract_id: str) -> Contract:
        try:
            return self.contracts[contract_id]
        except KeyError as exc:
            raise NotFoundError("Vertrag nicht gefunden") from exc

    def update_contract(self, contract_id: str, data: ContractCreate) -> Contract:
        if contract_id not in self.contracts:
            raise NotFoundError("Vertrag nicht gefunden")
        if data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        if data.tenant_id not in self.tenants:
            raise ValidationError("Mieter existiert nicht")
        if self.units[data.unit_id].property_id != data.property_id:
            raise ValidationError("Einheit gehört nicht zur Immobilie")
        if any(
            contract.contract_number == data.contract_number and contract.id != contract_id
            for contract in self.contracts.values()
        ):
            raise ValidationError("Vertragsnummer existiert bereits")
        old = self.contracts[contract_id]
        contract = Contract(
            id=contract_id, created_at=old.created_at,
            updated_at=datetime.now(timezone.utc), **data.model_dump(),
        )
        self.contracts[contract_id] = contract
        return contract

    def delete_contract(self, contract_id: str) -> None:
        if contract_id not in self.contracts:
            raise NotFoundError("Vertrag nicht gefunden")
        self._delete_contract(contract_id)

    def list_bookings(self) -> List[Booking]:
        return list(self.bookings.values())

    def create_booking(self, data: BookingCreate) -> Booking:
        if data.account_id not in self.accounts:
            raise ValidationError("Konto existiert nicht")
        if data.category_id and data.category_id not in self.categories:
            raise ValidationError("Kategorie existiert nicht")
        if data.property_id and data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        if data.tenant_id and data.tenant_id not in self.tenants:
            raise ValidationError("Mieter existiert nicht")
        booking = Booking(id=_generate_id(), **data.model_dump())
        self.bookings[booking.id] = booking
        return booking

    def get_booking(self, booking_id: str) -> Booking:
        try:
            return self.bookings[booking_id]
        except KeyError as exc:
            raise NotFoundError("Buchung nicht gefunden") from exc

    def update_booking(self, booking_id: str, data: BookingCreate) -> Booking:
        if booking_id not in self.bookings:
            raise NotFoundError("Buchung nicht gefunden")
        if data.account_id not in self.accounts:
            raise ValidationError("Konto existiert nicht")
        if data.category_id and data.category_id not in self.categories:
            raise ValidationError("Kategorie existiert nicht")
        if data.property_id and data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        if data.tenant_id and data.tenant_id not in self.tenants:
            raise ValidationError("Mieter existiert nicht")
        old = self.bookings[booking_id]
        booking = Booking(id=booking_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.bookings[booking_id] = booking
        return booking

    def delete_booking(self, booking_id: str) -> None:
        if booking_id not in self.bookings:
            raise NotFoundError("Buchung nicht gefunden")
        del self.bookings[booking_id]

    def list_receivables(self) -> List[Receivable]:
        return list(self.receivables.values())

    def create_receivable(self, data: ReceivableCreate) -> Receivable:
        if data.contract_id not in self.contracts:
            raise ValidationError("Vertrag existiert nicht")
        receivable = Receivable(id=_generate_id(), **data.model_dump())
        self.receivables[receivable.id] = receivable
        return receivable

    def get_receivable(self, receivable_id: str) -> Receivable:
        try:
            return self.receivables[receivable_id]
        except KeyError as exc:
            raise NotFoundError("Forderung nicht gefunden") from exc

    def update_receivable(self, receivable_id: str, data: ReceivableCreate) -> Receivable:
        if receivable_id not in self.receivables:
            raise NotFoundError("Forderung nicht gefunden")
        if data.contract_id not in self.contracts:
            raise ValidationError("Vertrag existiert nicht")
        old = self.receivables[receivable_id]
        receivable = Receivable(
            id=receivable_id, created_at=old.created_at,
            updated_at=datetime.now(timezone.utc), **data.model_dump(),
        )
        self.receivables[receivable_id] = receivable
        return receivable

    def delete_receivable(self, receivable_id: str) -> None:
        if receivable_id not in self.receivables:
            raise NotFoundError("Forderung nicht gefunden")
        del self.receivables[receivable_id]

    def list_invoices(self) -> List[Invoice]:
        return list(self.invoices.values())

    def create_invoice(self, data: InvoiceCreate) -> Invoice:
        if data.property_id and data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        invoice = Invoice(id=_generate_id(), **data.model_dump())
        self.invoices[invoice.id] = invoice
        return invoice

    def get_invoice(self, invoice_id: str) -> Invoice:
        try:
            return self.invoices[invoice_id]
        except KeyError as exc:
            raise NotFoundError("Rechnung nicht gefunden") from exc

    def update_invoice(self, invoice_id: str, data: InvoiceCreate) -> Invoice:
        if invoice_id not in self.invoices:
            raise NotFoundError("Rechnung nicht gefunden")
        if data.property_id and data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        old = self.invoices[invoice_id]
        invoice = Invoice(id=invoice_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.invoices[invoice_id] = invoice
        return invoice

    def delete_invoice(self, invoice_id: str) -> None:
        if invoice_id not in self.invoices:
            raise NotFoundError("Rechnung nicht gefunden")
        del self.invoices[invoice_id]

    def list_maintenance_cases(self) -> List[MaintenanceCase]:
        return list(self.maintenance_cases.values())

    def create_maintenance_case(self, data: MaintenanceCaseCreate) -> MaintenanceCase:
        if data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        case = MaintenanceCase(id=_generate_id(), **data.model_dump())
        self.maintenance_cases[case.id] = case
        return case

    def get_maintenance_case(self, case_id: str) -> MaintenanceCase:
        try:
            return self.maintenance_cases[case_id]
        except KeyError as exc:
            raise NotFoundError("Instandhaltungsfall nicht gefunden") from exc

    def update_maintenance_case(self, case_id: str, data: MaintenanceCaseCreate) -> MaintenanceCase:
        if case_id not in self.maintenance_cases:
            raise NotFoundError("Instandhaltungsfall nicht gefunden")
        if data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        old = self.maintenance_cases[case_id]
        case = MaintenanceCase(id=case_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.maintenance_cases[case_id] = case
        return case

    def delete_maintenance_case(self, case_id: str) -> None:
        if case_id not in self.maintenance_cases:
            raise NotFoundError("Instandhaltungsfall nicht gefunden")
        del self.maintenance_cases[case_id]

    def list_documents(self) -> List[Document]:
        return list(self.documents.values())

    def create_document(self, data: DocumentCreate) -> Document:
        if data.property_id and data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        if data.contract_id and data.contract_id not in self.contracts:
            raise ValidationError("Vertrag existiert nicht")
        document = Document(id=_generate_id(), **data.model_dump())
        self.documents[document.id] = document
        return document

    def get_document(self, document_id: str) -> Document:
        try:
            return self.documents[document_id]
        except KeyError as exc:
            raise NotFoundError("Dokument nicht gefunden") from exc

    def update_document(self, document_id: str, data: DocumentCreate) -> Document:
        if document_id not in self.documents:
            raise NotFoundError("Dokument nicht gefunden")
        if data.property_id and data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        if data.contract_id and data.contract_id not in self.contracts:
            raise ValidationError("Vertrag existiert nicht")
        old = self.documents[document_id]
        document = Document(
            id=document_id, created_at=old.created_at,
            updated_at=datetime.now(timezone.utc), **data.model_dump(),
        )
        self.documents[document_id] = document
        return document

    def delete_document(self, document_id: str) -> None:
        if document_id not in self.documents:
            raise NotFoundError("Dokument nicht gefunden")
        del self.documents[document_id]

    def list_tasks(self) -> List[Task]:
        return list(self.tasks.values())

    def create_task(self, data: TaskCreate) -> Task:
        if data.property_id and data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        task = Task(id=_generate_id(), **data.model_dump())
        self.tasks[task.id] = task
        return task

    def get_task(self, task_id: str) -> Task:
        try:
            return self.tasks[task_id]
        except KeyError as exc:
            raise NotFoundError("Aufgabe nicht gefunden") from exc

    def update_task(self, task_id: str, data: TaskCreate) -> Task:
        if task_id not in self.tasks:
            raise NotFoundError("Aufgabe nicht gefunden")
        if data.property_id and data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        old = self.tasks[task_id]
        task = Task(id=task_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.tasks[task_id] = task
        return task

    def delete_task(self, task_id: str) -> None:
        if task_id not in self.tasks:
            raise NotFoundError("Aufgabe nicht gefunden")
        del self.tasks[task_id]

    def list_calendar_events(self) -> List[CalendarEvent]:
        return list(self.calendar_events.values())

    def create_calendar_event(self, data: CalendarEventCreate) -> CalendarEvent:
        if data.property_id and data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        event = CalendarEvent(id=_generate_id(), **data.model_dump())
        self.calendar_events[event.id] = event
        return event

    def get_calendar_event(self, event_id: str) -> CalendarEvent:
        try:
            return self.calendar_events[event_id]
        except KeyError as exc:
            raise NotFoundError("Termin nicht gefunden") from exc

    def update_calendar_event(self, event_id: str, data: CalendarEventCreate) -> CalendarEvent:
        if event_id not in self.calendar_events:
            raise NotFoundError("Termin nicht gefunden")
        if data.property_id and data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        if data.unit_id and data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        old = self.calendar_events[event_id]
        event = CalendarEvent(id=event_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.calendar_events[event_id] = event
        return event

    def delete_calendar_event(self, event_id: str) -> None:
        if event_id not in self.calendar_events:
            raise NotFoundError("Termin nicht gefunden")
        del self.calendar_events[event_id]

    def list_listings(self) -> List[Listing]:
        return list(self.listings.values())

    def create_listing(self, data: ListingCreate) -> Listing:
        if data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        listing = Listing(id=_generate_id(), **data.model_dump())
        self.listings[listing.id] = listing
        return listing

    def get_listing(self, listing_id: str) -> Listing:
        try:
            return self.listings[listing_id]
        except KeyError as exc:
            raise NotFoundError("Inserat nicht gefunden") from exc

    def update_listing(self, listing_id: str, data: ListingCreate) -> Listing:
        if listing_id not in self.listings:
            raise NotFoundError("Inserat nicht gefunden")
        if data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        old = self.listings[listing_id]
        listing = Listing(id=listing_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.listings[listing_id] = listing
        return listing

    def delete_listing(self, listing_id: str) -> None:
        if listing_id not in self.listings:
            raise NotFoundError("Inserat nicht gefunden")
        for photo_id, photo in list(self.listing_photos.items()):
            if photo.listing_id == listing_id:
                del self.listing_photos[photo_id]
        del self.listings[listing_id]

    def list_listing_photos(self) -> List[ListingPhoto]:
        return list(self.listing_photos.values())

    def create_listing_photo(self, data: ListingPhotoCreate) -> ListingPhoto:
        if data.listing_id not in self.listings:
            raise ValidationError("Inserat existiert nicht")
        photo = ListingPhoto(id=_generate_id(), **data.model_dump())
        self.listing_photos[photo.id] = photo
        return photo

    def get_listing_photo(self, photo_id: str) -> ListingPhoto:
        try:
            return self.listing_photos[photo_id]
        except KeyError as exc:
            raise NotFoundError("Inseratsfoto nicht gefunden") from exc

    def update_listing_photo(self, photo_id: str, data: ListingPhotoCreate) -> ListingPhoto:
        if photo_id not in self.listing_photos:
            raise NotFoundError("Inseratsfoto nicht gefunden")
        if data.listing_id not in self.listings:
            raise ValidationError("Inserat existiert nicht")
        old = self.listing_photos[photo_id]
        photo = ListingPhoto(id=photo_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.listing_photos[photo_id] = photo
        return photo

    def delete_listing_photo(self, photo_id: str) -> None:
        if photo_id not in self.listing_photos:
            raise NotFoundError("Inseratsfoto nicht gefunden")
        del self.listing_photos[photo_id]

    # --- Leads ---

    def list_leads(self) -> List[Lead]:
        return list(self.leads.values())

    def create_lead(self, data: LeadCreate) -> Lead:
        if data.listing_id and data.listing_id not in self.listings:
            raise ValidationError("Inserat existiert nicht")
        if data.unit_id and data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        lead = Lead(id=_generate_id(), **data.model_dump())
        self.leads[lead.id] = lead
        return lead

    def get_lead(self, lead_id: str) -> Lead:
        try:
            return self.leads[lead_id]
        except KeyError as exc:
            raise NotFoundError("Interessent nicht gefunden") from exc

    def update_lead(self, lead_id: str, data: LeadCreate) -> Lead:
        if lead_id not in self.leads:
            raise NotFoundError("Interessent nicht gefunden")
        if data.listing_id and data.listing_id not in self.listings:
            raise ValidationError("Inserat existiert nicht")
        if data.unit_id and data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        old = self.leads[lead_id]
        lead = Lead(id=lead_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.leads[lead_id] = lead
        return lead

    def delete_lead(self, lead_id: str) -> None:
        if lead_id not in self.leads:
            raise NotFoundError("Interessent nicht gefunden")
        # Cascade: delete associated viewing appointments
        for va_id, va in list(self.viewing_appointments.items()):
            if va.lead_id == lead_id:
                del self.viewing_appointments[va_id]
        del self.leads[lead_id]

    # --- Viewing Appointments ---

    def list_viewing_appointments(self) -> List[ViewingAppointment]:
        return list(self.viewing_appointments.values())

    def create_viewing_appointment(self, data: ViewingAppointmentCreate) -> ViewingAppointment:
        if data.lead_id not in self.leads:
            raise ValidationError("Interessent existiert nicht")
        if data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        appointment = ViewingAppointment(id=_generate_id(), **data.model_dump())
        self.viewing_appointments[appointment.id] = appointment
        return appointment

    def get_viewing_appointment(self, appointment_id: str) -> ViewingAppointment:
        try:
            return self.viewing_appointments[appointment_id]
        except KeyError as exc:
            raise NotFoundError("Besichtigungstermin nicht gefunden") from exc

    def update_viewing_appointment(self, appointment_id: str, data: ViewingAppointmentCreate) -> ViewingAppointment:
        if appointment_id not in self.viewing_appointments:
            raise NotFoundError("Besichtigungstermin nicht gefunden")
        if data.lead_id not in self.leads:
            raise ValidationError("Interessent existiert nicht")
        if data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        old = self.viewing_appointments[appointment_id]
        appointment = ViewingAppointment(
            id=appointment_id, created_at=old.created_at,
            updated_at=datetime.now(timezone.utc), **data.model_dump(),
        )
        self.viewing_appointments[appointment_id] = appointment
        return appointment

    def delete_viewing_appointment(self, appointment_id: str) -> None:
        if appointment_id not in self.viewing_appointments:
            raise NotFoundError("Besichtigungstermin nicht gefunden")
        del self.viewing_appointments[appointment_id]

    # --- Billing Periods ---

    def list_billing_periods(self) -> List[BillingPeriod]:
        return list(self.billing_periods.values())

    def create_billing_period(self, data: BillingPeriodCreate) -> BillingPeriod:
        if data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        if data.end_date <= data.start_date:
            raise ValidationError("Enddatum muss nach Startdatum liegen")
        period = BillingPeriod(id=_generate_id(), **data.model_dump())
        self.billing_periods[period.id] = period
        return period

    def get_billing_period(self, period_id: str) -> BillingPeriod:
        try:
            return self.billing_periods[period_id]
        except KeyError as exc:
            raise NotFoundError("Abrechnungsperiode nicht gefunden") from exc

    def update_billing_period(self, period_id: str, data: BillingPeriodCreate) -> BillingPeriod:
        if period_id not in self.billing_periods:
            raise NotFoundError("Abrechnungsperiode nicht gefunden")
        if data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        if data.end_date <= data.start_date:
            raise ValidationError("Enddatum muss nach Startdatum liegen")
        old = self.billing_periods[period_id]
        period = BillingPeriod(
            id=period_id, created_at=old.created_at,
            updated_at=datetime.now(timezone.utc), **data.model_dump(),
        )
        self.billing_periods[period_id] = period
        return period

    def delete_billing_period(self, period_id: str) -> None:
        if period_id not in self.billing_periods:
            raise NotFoundError("Abrechnungsperiode nicht gefunden")
        # Cascade: delete cost items and utility statements
        for ci_id, ci in list(self.cost_items.items()):
            if ci.billing_period_id == period_id:
                del self.cost_items[ci_id]
        for us_id, us in list(self.utility_statements.items()):
            if us.billing_period_id == period_id:
                del self.utility_statements[us_id]
        del self.billing_periods[period_id]

    # --- Allocation Keys ---

    def list_allocation_keys(self) -> List[AllocationKey]:
        return list(self.allocation_keys.values())

    def create_allocation_key(self, data: AllocationKeyCreate) -> AllocationKey:
        if data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        key = AllocationKey(id=_generate_id(), **data.model_dump())
        self.allocation_keys[key.id] = key
        return key

    def get_allocation_key(self, key_id: str) -> AllocationKey:
        try:
            return self.allocation_keys[key_id]
        except KeyError as exc:
            raise NotFoundError("Verteilerschlüssel nicht gefunden") from exc

    def update_allocation_key(self, key_id: str, data: AllocationKeyCreate) -> AllocationKey:
        if key_id not in self.allocation_keys:
            raise NotFoundError("Verteilerschlüssel nicht gefunden")
        if data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        old = self.allocation_keys[key_id]
        key = AllocationKey(id=key_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.allocation_keys[key_id] = key
        return key

    def delete_allocation_key(self, key_id: str) -> None:
        if key_id not in self.allocation_keys:
            raise NotFoundError("Verteilerschlüssel nicht gefunden")
        # Cascade: delete cost items using this key
        for ci_id, ci in list(self.cost_items.items()):
            if ci.allocation_key_id == key_id:
                del self.cost_items[ci_id]
        del self.allocation_keys[key_id]

    # --- Cost Items ---

    def list_cost_items(self) -> List[CostItem]:
        return list(self.cost_items.values())

    def create_cost_item(self, data: CostItemCreate) -> CostItem:
        if data.billing_period_id not in self.billing_periods:
            raise ValidationError("Abrechnungsperiode existiert nicht")
        if data.allocation_key_id not in self.allocation_keys:
            raise ValidationError("Verteilerschlüssel existiert nicht")
        item = CostItem(id=_generate_id(), **data.model_dump())
        self.cost_items[item.id] = item
        return item

    def get_cost_item(self, item_id: str) -> CostItem:
        try:
            return self.cost_items[item_id]
        except KeyError as exc:
            raise NotFoundError("Kostenposition nicht gefunden") from exc

    def update_cost_item(self, item_id: str, data: CostItemCreate) -> CostItem:
        if item_id not in self.cost_items:
            raise NotFoundError("Kostenposition nicht gefunden")
        if data.billing_period_id not in self.billing_periods:
            raise ValidationError("Abrechnungsperiode existiert nicht")
        if data.allocation_key_id not in self.allocation_keys:
            raise ValidationError("Verteilerschlüssel existiert nicht")
        old = self.cost_items[item_id]
        item = CostItem(id=item_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.cost_items[item_id] = item
        return item

    def delete_cost_item(self, item_id: str) -> None:
        if item_id not in self.cost_items:
            raise NotFoundError("Kostenposition nicht gefunden")
        del self.cost_items[item_id]

    # --- Utility Statements ---

    def list_utility_statements(self) -> List[UtilityStatement]:
        return list(self.utility_statements.values())

    def create_utility_statement(self, data: UtilityStatementCreate) -> UtilityStatement:
        if data.billing_period_id not in self.billing_periods:
            raise ValidationError("Abrechnungsperiode existiert nicht")
        if data.contract_id not in self.contracts:
            raise ValidationError("Vertrag existiert nicht")
        if data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        statement = UtilityStatement(id=_generate_id(), **data.model_dump())
        self.utility_statements[statement.id] = statement
        return statement

    def get_utility_statement(self, statement_id: str) -> UtilityStatement:
        try:
            return self.utility_statements[statement_id]
        except KeyError as exc:
            raise NotFoundError("Betriebskostenabrechnung nicht gefunden") from exc

    def update_utility_statement(self, statement_id: str, data: UtilityStatementCreate) -> UtilityStatement:
        if statement_id not in self.utility_statements:
            raise NotFoundError("Betriebskostenabrechnung nicht gefunden")
        if data.billing_period_id not in self.billing_periods:
            raise ValidationError("Abrechnungsperiode existiert nicht")
        if data.contract_id not in self.contracts:
            raise ValidationError("Vertrag existiert nicht")
        if data.unit_id not in self.units:
            raise ValidationError("Einheit existiert nicht")
        old = self.utility_statements[statement_id]
        statement = UtilityStatement(
            id=statement_id, created_at=old.created_at,
            updated_at=datetime.now(timezone.utc), **data.model_dump(),
        )
        self.utility_statements[statement_id] = statement
        return statement

    def delete_utility_statement(self, statement_id: str) -> None:
        if statement_id not in self.utility_statements:
            raise NotFoundError("Betriebskostenabrechnung nicht gefunden")
        del self.utility_statements[statement_id]

    # --- Deposits ---

    def list_deposits(self) -> List[Deposit]:
        return list(self.deposits.values())

    def create_deposit(self, data: DepositCreate) -> Deposit:
        if data.contract_id not in self.contracts:
            raise ValidationError("Vertrag existiert nicht")
        deposit = Deposit(id=_generate_id(), **data.model_dump())
        self.deposits[deposit.id] = deposit
        return deposit

    def get_deposit(self, deposit_id: str) -> Deposit:
        try:
            return self.deposits[deposit_id]
        except KeyError as exc:
            raise NotFoundError("Kaution nicht gefunden") from exc

    def update_deposit(self, deposit_id: str, data: DepositCreate) -> Deposit:
        if deposit_id not in self.deposits:
            raise NotFoundError("Kaution nicht gefunden")
        if data.contract_id not in self.contracts:
            raise ValidationError("Vertrag existiert nicht")
        old = self.deposits[deposit_id]
        deposit = Deposit(id=deposit_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.deposits[deposit_id] = deposit
        return deposit

    def delete_deposit(self, deposit_id: str) -> None:
        if deposit_id not in self.deposits:
            raise NotFoundError("Kaution nicht gefunden")
        del self.deposits[deposit_id]

    # --- Notifications ---

    def list_notifications(self) -> List[Notification]:
        return list(self.notifications.values())

    def create_notification(self, data: NotificationCreate) -> Notification:
        notification = Notification(id=_generate_id(), **data.model_dump())
        self.notifications[notification.id] = notification
        return notification

    def get_notification(self, notification_id: str) -> Notification:
        try:
            return self.notifications[notification_id]
        except KeyError as exc:
            raise NotFoundError("Benachrichtigung nicht gefunden") from exc

    def mark_notification_read(self, notification_id: str) -> Notification:
        if notification_id not in self.notifications:
            raise NotFoundError("Benachrichtigung nicht gefunden")
        old = self.notifications[notification_id]
        updated = old.model_copy(update={
            "status": "read", "read_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })
        self.notifications[notification_id] = updated
        return updated

    def delete_notification(self, notification_id: str) -> None:
        if notification_id not in self.notifications:
            raise NotFoundError("Benachrichtigung nicht gefunden")
        del self.notifications[notification_id]

    # --- Notification Templates ---

    def list_notification_templates(self) -> List[NotificationTemplate]:
        return list(self.notification_templates.values())

    def create_notification_template(self, data: NotificationTemplateCreate) -> NotificationTemplate:
        template = NotificationTemplate(id=_generate_id(), **data.model_dump())
        self.notification_templates[template.id] = template
        return template

    def get_notification_template(self, template_id: str) -> NotificationTemplate:
        try:
            return self.notification_templates[template_id]
        except KeyError as exc:
            raise NotFoundError("Benachrichtigungsvorlage nicht gefunden") from exc

    def update_notification_template(self, template_id: str, data: NotificationTemplateCreate) -> NotificationTemplate:
        if template_id not in self.notification_templates:
            raise NotFoundError("Benachrichtigungsvorlage nicht gefunden")
        old = self.notification_templates[template_id]
        template = NotificationTemplate(
            id=template_id, created_at=old.created_at,
            updated_at=datetime.now(timezone.utc), **data.model_dump(),
        )
        self.notification_templates[template_id] = template
        return template

    def delete_notification_template(self, template_id: str) -> None:
        if template_id not in self.notification_templates:
            raise NotFoundError("Benachrichtigungsvorlage nicht gefunden")
        del self.notification_templates[template_id]

    _ENTITY_TYPE_MAP = {
        "portfolio": ("portfolios", "Portfolio nicht gefunden"),
        "property": ("properties", "Immobilie nicht gefunden"),
        "unit": ("units", "Einheit nicht gefunden"),
        "tenant": ("tenants", "Mieter nicht gefunden"),
        "contract": ("contracts", "Vertrag nicht gefunden"),
        "account": ("accounts", "Konto nicht gefunden"),
        "category": ("categories", "Kategorie nicht gefunden"),
        "booking": ("bookings", "Buchung nicht gefunden"),
        "receivable": ("receivables", "Forderung nicht gefunden"),
        "invoice": ("invoices", "Rechnung nicht gefunden"),
        "maintenance": ("maintenance_cases", "Instandhaltungsfall nicht gefunden"),
        "document": ("documents", "Dokument nicht gefunden"),
        "task": ("tasks", "Aufgabe nicht gefunden"),
        "calendar": ("calendar_events", "Termin nicht gefunden"),
        "listing": ("listings", "Inserat nicht gefunden"),
        "listing_photo": ("listing_photos", "Inseratsfoto nicht gefunden"),
        "lead": ("leads", "Interessent nicht gefunden"),
        "viewing": ("viewing_appointments", "Besichtigungstermin nicht gefunden"),
        "billing_period": ("billing_periods", "Abrechnungsperiode nicht gefunden"),
        "allocation_key": ("allocation_keys", "Verteilerschlüssel nicht gefunden"),
        "cost_item": ("cost_items", "Kostenposition nicht gefunden"),
        "utility_statement": ("utility_statements", "Betriebskostenabrechnung nicht gefunden"),
        "deposit": ("deposits", "Kaution nicht gefunden"),
        "notification": ("notifications", "Benachrichtigung nicht gefunden"),
        "notification_template": ("notification_templates", "Benachrichtigungsvorlage nicht gefunden"),
        "tax_rate": ("tax_rates", "Steuersatz nicht gefunden"),
        "rent_adjustment": ("rent_adjustments", "Mietanpassung nicht gefunden"),
        "handover_protocol": ("handover_protocols", "Übergabeprotokoll nicht gefunden"),
        "meter_reading": ("meter_readings", "Zählerstand nicht gefunden"),
        "budget": ("budgets", "Budget nicht gefunden"),
        "escalation_rule": ("escalation_rules", "Eskalationsregel nicht gefunden"),
        "insurance": ("insurances", "Versicherung nicht gefunden"),
        "entity_photo": ("entity_photos", "Foto nicht gefunden"),
        "contact": ("contacts", "Kontakt nicht gefunden"),
        "meter": ("meters", "Zähler nicht gefunden"),
        "standalone_reading": ("standalone_meter_readings", "Ablesung nicht gefunden"),
        "message_thread": ("message_threads", "Thread nicht gefunden"),
        "message": ("messages", "Nachricht nicht gefunden"),
        "rent_charge": ("rent_charges", "Sollstellung nicht gefunden"),
    }

    def _patch_entity(self, entity_type: str, entity_id: str, patch: PydanticBaseModel):
        """Apply a partial update to an entity. Only non-None fields in the patch are applied."""
        entry = self._ENTITY_TYPE_MAP.get(entity_type)
        if entry is None:
            raise ValueError(f"Unknown entity type: {entity_type}")
        attr_name, not_found_msg = entry
        collection = getattr(self, attr_name)
        if entity_id not in collection:
            raise NotFoundError(not_found_msg)
        old = collection[entity_id]
        updates = patch.model_dump(exclude_unset=True)
        updated = old.model_copy(update={**updates, "updated_at": datetime.now(timezone.utc)})
        collection[entity_id] = updated
        return updated

    def _list_paginated(
        self,
        entity_type: str,
        skip: int = 0,
        limit: int = 100,
        filters: dict | None = None,
        order_by: str | None = None,
        order_desc: bool = False,
    ) -> list:
        """Generic paginated list with filtering and sorting for in-memory store."""
        entry = self._ENTITY_TYPE_MAP.get(entity_type)
        if entry is None:
            raise ValueError(f"Unknown entity type: {entity_type}")
        attr_name, _not_found_msg = entry
        collection = getattr(self, attr_name)
        results = list(collection.values())
        if filters:
            for key, value in filters.items():
                if value is None:
                    continue
                results = [r for r in results if getattr(r, key, None) == value]
        if order_by and isinstance(order_by, str):
            results.sort(
                key=lambda r: (getattr(r, order_by, None) is None, getattr(r, order_by, None)),
                reverse=order_desc,
            )
        return results[skip : skip + limit]

    def _delete_contract(self, contract_id: str) -> None:
        for receivable_id, receivable in list(self.receivables.items()):
            if receivable.contract_id == contract_id:
                del self.receivables[receivable_id]
        for document_id, document in list(self.documents.items()):
            if document.contract_id == contract_id:
                del self.documents[document_id]
        del self.contracts[contract_id]

    def _delete_units(self, unit_ids: set[str]) -> None:
        for unit_id in unit_ids:
            if unit_id in self.units:
                self.delete_unit(unit_id)

    def _delete_properties(self, property_ids: set[str]) -> None:
        for property_id in property_ids:
            if property_id in self.properties:
                self.delete_property(property_id)

    def _delete_accounts(self, account_ids: set[str]) -> None:
        for account_id in account_ids:
            if account_id in self.accounts:
                self.delete_account(account_id)

    def _delete_categories(self, category_ids: set[str]) -> None:
        for category_id in category_ids:
            if category_id in self.categories:
                self.delete_category(category_id)

    # --- Tax Rates (T14) ---
    def list_tax_rates(self) -> List[TaxRate]:
        return list(self.tax_rates.values())

    def create_tax_rate(self, data: TaxRateCreate) -> TaxRate:
        item = TaxRate(id=_generate_id(), **data.model_dump())
        self.tax_rates[item.id] = item
        return item

    def get_tax_rate(self, tax_rate_id: str) -> TaxRate:
        try:
            return self.tax_rates[tax_rate_id]
        except KeyError as exc:
            raise NotFoundError("Steuersatz nicht gefunden") from exc

    def update_tax_rate(self, tax_rate_id: str, data: TaxRateCreate) -> TaxRate:
        if tax_rate_id not in self.tax_rates:
            raise NotFoundError("Steuersatz nicht gefunden")
        old = self.tax_rates[tax_rate_id]
        item = TaxRate(id=tax_rate_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.tax_rates[tax_rate_id] = item
        return item

    def delete_tax_rate(self, tax_rate_id: str) -> None:
        if tax_rate_id not in self.tax_rates:
            raise NotFoundError("Steuersatz nicht gefunden")
        del self.tax_rates[tax_rate_id]

    # --- Rent Adjustments (T15) ---
    def list_rent_adjustments(self) -> List[RentAdjustment]:
        return list(self.rent_adjustments.values())

    def create_rent_adjustment(self, data: RentAdjustmentCreate) -> RentAdjustment:
        if data.contract_id not in self.contracts:
            raise ValidationError("Vertrag nicht gefunden")
        item = RentAdjustment(id=_generate_id(), **data.model_dump())
        self.rent_adjustments[item.id] = item
        return item

    def get_rent_adjustment(self, adj_id: str) -> RentAdjustment:
        try:
            return self.rent_adjustments[adj_id]
        except KeyError as exc:
            raise NotFoundError("Mietanpassung nicht gefunden") from exc

    def update_rent_adjustment(self, adj_id: str, data: RentAdjustmentCreate) -> RentAdjustment:
        if adj_id not in self.rent_adjustments:
            raise NotFoundError("Mietanpassung nicht gefunden")
        old = self.rent_adjustments[adj_id]
        item = RentAdjustment(id=adj_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.rent_adjustments[adj_id] = item
        return item

    def delete_rent_adjustment(self, adj_id: str) -> None:
        if adj_id not in self.rent_adjustments:
            raise NotFoundError("Mietanpassung nicht gefunden")
        del self.rent_adjustments[adj_id]

    # --- Handover Protocols (T16) ---
    def list_handover_protocols(self) -> List[HandoverProtocol]:
        return list(self.handover_protocols.values())

    def create_handover_protocol(self, data: HandoverProtocolCreate) -> HandoverProtocol:
        if data.contract_id not in self.contracts:
            raise ValidationError("Vertrag nicht gefunden")
        if data.unit_id not in self.units:
            raise ValidationError("Einheit nicht gefunden")
        item = HandoverProtocol(id=_generate_id(), **data.model_dump())
        self.handover_protocols[item.id] = item
        return item

    def get_handover_protocol(self, proto_id: str) -> HandoverProtocol:
        try:
            return self.handover_protocols[proto_id]
        except KeyError as exc:
            raise NotFoundError("Übergabeprotokoll nicht gefunden") from exc

    def update_handover_protocol(self, proto_id: str, data: HandoverProtocolCreate) -> HandoverProtocol:
        if proto_id not in self.handover_protocols:
            raise NotFoundError("Übergabeprotokoll nicht gefunden")
        old = self.handover_protocols[proto_id]
        item = HandoverProtocol(
            id=proto_id, created_at=old.created_at,
            updated_at=datetime.now(timezone.utc), **data.model_dump(),
        )
        self.handover_protocols[proto_id] = item
        return item

    def delete_handover_protocol(self, proto_id: str) -> None:
        if proto_id not in self.handover_protocols:
            raise NotFoundError("Übergabeprotokoll nicht gefunden")
        # Cascade delete meter readings
        for mr_id, mr in list(self.meter_readings.items()):
            if mr.handover_id == proto_id:
                del self.meter_readings[mr_id]
        del self.handover_protocols[proto_id]

    # --- Meter Readings (T16) ---
    def list_meter_readings(self) -> List[MeterReading]:
        return list(self.meter_readings.values())

    def create_meter_reading(self, data: MeterReadingCreate) -> MeterReading:
        if data.handover_id not in self.handover_protocols:
            raise ValidationError("Übergabeprotokoll nicht gefunden")
        item = MeterReading(id=_generate_id(), **data.model_dump())
        self.meter_readings[item.id] = item
        return item

    def get_meter_reading(self, reading_id: str) -> MeterReading:
        try:
            return self.meter_readings[reading_id]
        except KeyError as exc:
            raise NotFoundError("Zählerstand nicht gefunden") from exc

    def update_meter_reading(self, reading_id: str, data: MeterReadingCreate) -> MeterReading:
        if reading_id not in self.meter_readings:
            raise NotFoundError("Zählerstand nicht gefunden")
        old = self.meter_readings[reading_id]
        item = MeterReading(id=reading_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.meter_readings[reading_id] = item
        return item

    def delete_meter_reading(self, reading_id: str) -> None:
        if reading_id not in self.meter_readings:
            raise NotFoundError("Zählerstand nicht gefunden")
        del self.meter_readings[reading_id]

    # --- Change History (T18) ---
    def list_change_history(self) -> List[ChangeHistoryEntry]:
        return list(self.change_history.values())

    def add_change_history(self, entity_type: str, entity_id: str,
                           field_name: str, old_value: str | None,
                           new_value: str | None, changed_by: str | None = None,
                           reason: str | None = None) -> ChangeHistoryEntry:
        entry = ChangeHistoryEntry(
            id=_generate_id(), entity_type=entity_type, entity_id=entity_id,
            field_name=field_name, old_value=old_value, new_value=new_value,
            changed_by=changed_by, reason=reason,
        )
        self.change_history[entry.id] = entry
        return entry

    def get_entity_history(self, entity_type: str, entity_id: str) -> List[ChangeHistoryEntry]:
        return [h for h in self.change_history.values()
                if h.entity_type == entity_type and h.entity_id == entity_id]

    # --- Budgets (T27) ---
    def list_budgets(self) -> List[Budget]:
        return list(self.budgets.values())

    def create_budget(self, data: BudgetCreate) -> Budget:
        if data.property_id not in self.properties:
            raise ValidationError("Immobilie nicht gefunden")
        item = Budget(id=_generate_id(), **data.model_dump())
        self.budgets[item.id] = item
        return item

    def get_budget(self, budget_id: str) -> Budget:
        try:
            return self.budgets[budget_id]
        except KeyError as exc:
            raise NotFoundError("Budget nicht gefunden") from exc

    def update_budget(self, budget_id: str, data: BudgetCreate) -> Budget:
        if budget_id not in self.budgets:
            raise NotFoundError("Budget nicht gefunden")
        old = self.budgets[budget_id]
        item = Budget(id=budget_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.budgets[budget_id] = item
        return item

    def delete_budget(self, budget_id: str) -> None:
        if budget_id not in self.budgets:
            raise NotFoundError("Budget nicht gefunden")
        del self.budgets[budget_id]

    # --- Escalation Rules (T17) ---
    def list_escalation_rules(self) -> List[EscalationRule]:
        return list(self.escalation_rules.values())

    def create_escalation_rule(self, data: EscalationRuleCreate) -> EscalationRule:
        item = EscalationRule(id=_generate_id(), **data.model_dump())
        self.escalation_rules[item.id] = item
        return item

    def get_escalation_rule(self, rule_id: str) -> EscalationRule:
        try:
            return self.escalation_rules[rule_id]
        except KeyError as exc:
            raise NotFoundError("Eskalationsregel nicht gefunden") from exc

    def update_escalation_rule(self, rule_id: str, data: EscalationRuleCreate) -> EscalationRule:
        if rule_id not in self.escalation_rules:
            raise NotFoundError("Eskalationsregel nicht gefunden")
        old = self.escalation_rules[rule_id]
        item = EscalationRule(id=rule_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.escalation_rules[rule_id] = item
        return item

    def delete_escalation_rule(self, rule_id: str) -> None:
        if rule_id not in self.escalation_rules:
            raise NotFoundError("Eskalationsregel nicht gefunden")
        del self.escalation_rules[rule_id]

    # --- Contacts ---
    def list_contacts(self) -> List[Contact]:
        return list(self.contacts.values())

    def create_contact(self, data: ContactCreate) -> Contact:
        contact = Contact(id=_generate_id(), **data.model_dump())
        self.contacts[contact.id] = contact
        return contact

    def get_contact(self, contact_id: str) -> Contact:
        try:
            return self.contacts[contact_id]
        except KeyError as exc:
            raise NotFoundError("Kontakt nicht gefunden") from exc

    def update_contact(self, contact_id: str, data: ContactCreate) -> Contact:
        if contact_id not in self.contacts:
            raise NotFoundError("Kontakt nicht gefunden")
        old = self.contacts[contact_id]
        contact = Contact(id=contact_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.contacts[contact_id] = contact
        return contact

    def delete_contact(self, contact_id: str) -> None:
        if contact_id not in self.contacts:
            raise NotFoundError("Kontakt nicht gefunden")
        del self.contacts[contact_id]

    # --- Meters ---
    def list_meters(self) -> List[Meter]:
        return list(self.meters.values())

    def create_meter(self, data: MeterCreate) -> Meter:
        meter = Meter(id=_generate_id(), **data.model_dump())
        self.meters[meter.id] = meter
        return meter

    def get_meter(self, meter_id: str) -> Meter:
        try:
            return self.meters[meter_id]
        except KeyError as exc:
            raise NotFoundError("Zähler nicht gefunden") from exc

    def update_meter(self, meter_id: str, data: MeterCreate) -> Meter:
        if meter_id not in self.meters:
            raise NotFoundError("Zähler nicht gefunden")
        old = self.meters[meter_id]
        meter = Meter(id=meter_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.meters[meter_id] = meter
        return meter

    def delete_meter(self, meter_id: str) -> None:
        if meter_id not in self.meters:
            raise NotFoundError("Zähler nicht gefunden")
        del self.meters[meter_id]

    # --- Standalone Meter Readings ---
    def list_standalone_meter_readings(self) -> List[StandaloneMeterReading]:
        return list(self.standalone_meter_readings.values())

    def create_standalone_meter_reading(self, data: StandaloneMeterReadingCreate) -> StandaloneMeterReading:
        reading = StandaloneMeterReading(id=_generate_id(), **data.model_dump())
        self.standalone_meter_readings[reading.id] = reading
        return reading

    def get_standalone_meter_reading(self, reading_id: str) -> StandaloneMeterReading:
        try:
            return self.standalone_meter_readings[reading_id]
        except KeyError as exc:
            raise NotFoundError("Ablesung nicht gefunden") from exc

    def update_standalone_meter_reading(self, reading_id: str, data: StandaloneMeterReadingCreate) -> StandaloneMeterReading:
        if reading_id not in self.standalone_meter_readings:
            raise NotFoundError("Ablesung nicht gefunden")
        old = self.standalone_meter_readings[reading_id]
        reading = StandaloneMeterReading(id=reading_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.standalone_meter_readings[reading_id] = reading
        return reading

    def delete_standalone_meter_reading(self, reading_id: str) -> None:
        if reading_id not in self.standalone_meter_readings:
            raise NotFoundError("Ablesung nicht gefunden")
        del self.standalone_meter_readings[reading_id]

    # --- Message Threads ---
    def list_message_threads(self) -> List[MessageThread]:
        return list(self.message_threads.values())

    def create_message_thread(self, data: MessageThreadCreate) -> MessageThread:
        thread = MessageThread(id=_generate_id(), **data.model_dump())
        self.message_threads[thread.id] = thread
        return thread

    def get_message_thread(self, thread_id: str) -> MessageThread:
        try:
            return self.message_threads[thread_id]
        except KeyError as exc:
            raise NotFoundError("Thread nicht gefunden") from exc

    def update_message_thread(self, thread_id: str, data: MessageThreadCreate) -> MessageThread:
        if thread_id not in self.message_threads:
            raise NotFoundError("Thread nicht gefunden")
        old = self.message_threads[thread_id]
        thread = MessageThread(id=thread_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.message_threads[thread_id] = thread
        return thread

    def delete_message_thread(self, thread_id: str) -> None:
        if thread_id not in self.message_threads:
            raise NotFoundError("Thread nicht gefunden")
        # Also delete associated messages
        msg_ids = [m.id for m in self.messages.values() if m.thread_id == thread_id]
        for mid in msg_ids:
            del self.messages[mid]
        del self.message_threads[thread_id]

    # --- Messages ---
    def list_messages(self) -> List[Message]:
        return list(self.messages.values())

    def create_message(self, data: MessageCreate) -> Message:
        message = Message(id=_generate_id(), **data.model_dump())
        self.messages[message.id] = message
        # Update thread stats
        if data.thread_id in self.message_threads:
            thread = self.message_threads[data.thread_id]
            self.message_threads[data.thread_id] = thread.model_copy(update={
                "last_message_at": message.sent_at,
                "message_count": thread.message_count + 1,
                "updated_at": datetime.now(timezone.utc),
            })
        return message

    def get_message(self, message_id: str) -> Message:
        try:
            return self.messages[message_id]
        except KeyError as exc:
            raise NotFoundError("Nachricht nicht gefunden") from exc

    def delete_message(self, message_id: str) -> None:
        if message_id not in self.messages:
            raise NotFoundError("Nachricht nicht gefunden")
        del self.messages[message_id]

    # --- Rent Charges (Sollstellung) ---
    def list_rent_charges(self) -> List[RentCharge]:
        return list(self.rent_charges.values())

    def create_rent_charge(self, data: RentChargeCreate) -> RentCharge:
        charge = RentCharge(id=_generate_id(), **data.model_dump())
        self.rent_charges[charge.id] = charge
        return charge

    def get_rent_charge(self, charge_id: str) -> RentCharge:
        try:
            return self.rent_charges[charge_id]
        except KeyError as exc:
            raise NotFoundError("Sollstellung nicht gefunden") from exc

    def update_rent_charge(self, charge_id: str, data: RentChargeCreate) -> RentCharge:
        if charge_id not in self.rent_charges:
            raise NotFoundError("Sollstellung nicht gefunden")
        old = self.rent_charges[charge_id]
        charge = RentCharge(id=charge_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.rent_charges[charge_id] = charge
        return charge

    def delete_rent_charge(self, charge_id: str) -> None:
        if charge_id not in self.rent_charges:
            raise NotFoundError("Sollstellung nicht gefunden")
        del self.rent_charges[charge_id]

    # --- Insurances ---

    def list_insurances(self) -> List[Insurance]:
        return list(self.insurances.values())

    def create_insurance(self, data: InsuranceCreate) -> Insurance:
        if data.property_id not in self.properties:
            raise ValidationError("Immobilie existiert nicht")
        item = Insurance(id=_generate_id(), **data.model_dump())
        self.insurances[item.id] = item
        return item

    def get_insurance(self, insurance_id: str) -> Insurance:
        try:
            return self.insurances[insurance_id]
        except KeyError as exc:
            raise NotFoundError("Versicherung nicht gefunden") from exc

    def update_insurance(self, insurance_id: str, data: InsuranceCreate) -> Insurance:
        if insurance_id not in self.insurances:
            raise NotFoundError("Versicherung nicht gefunden")
        old = self.insurances[insurance_id]
        item = Insurance(id=insurance_id, created_at=old.created_at, updated_at=datetime.now(timezone.utc), **data.model_dump())
        self.insurances[insurance_id] = item
        return item

    def delete_insurance(self, insurance_id: str) -> None:
        if insurance_id not in self.insurances:
            raise NotFoundError("Versicherung nicht gefunden")
        del self.insurances[insurance_id]

    # --- Entity Photos ---

    def list_entity_photos(self, entity_type: str, entity_id: str) -> List[EntityPhoto]:
        return [p for p in self.entity_photos.values() if p.entity_type == entity_type and p.entity_id == entity_id]

    def create_entity_photo(self, data: EntityPhotoCreate) -> EntityPhoto:
        item = EntityPhoto(id=_generate_id(), **data.model_dump())
        self.entity_photos[item.id] = item
        return item

    def get_entity_photo(self, photo_id: str) -> EntityPhoto:
        try:
            return self.entity_photos[photo_id]
        except KeyError as exc:
            raise NotFoundError("Foto nicht gefunden") from exc

    def delete_entity_photo(self, photo_id: str) -> None:
        if photo_id not in self.entity_photos:
            raise NotFoundError("Foto nicht gefunden")
        del self.entity_photos[photo_id]
