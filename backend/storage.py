from dataclasses import dataclass, field
from typing import Dict, List
from uuid import uuid4

from .models import (
    Account,
    AccountCreate,
    Booking,
    BookingCreate,
    CalendarEvent,
    CalendarEventCreate,
    Category,
    CategoryCreate,
    Contract,
    ContractCreate,
    Document,
    DocumentCreate,
    Invoice,
    InvoiceCreate,
    MaintenanceCase,
    MaintenanceCaseCreate,
    Portfolio,
    PortfolioCreate,
    Property,
    PropertyCreate,
    Receivable,
    ReceivableCreate,
    Task,
    TaskCreate,
    Tenant,
    TenantCreate,
    Unit,
    UnitCreate,
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
        portfolio = Portfolio(id=portfolio_id, **data.model_dump())
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
        category = Category(id=category_id, **data.model_dump())
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
        account = Account(id=account_id, **data.model_dump())
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
        property_item = Property(id=property_id, **data.model_dump())
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
        unit = Unit(id=unit_id, **data.model_dump())
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
        tenant = Tenant(id=tenant_id, **data.model_dump())
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
        contract = Contract(id=contract_id, **data.model_dump())
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
        booking = Booking(id=booking_id, **data.model_dump())
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
        receivable = Receivable(id=receivable_id, **data.model_dump())
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
        invoice = Invoice(id=invoice_id, **data.model_dump())
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
        case = MaintenanceCase(id=case_id, **data.model_dump())
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
        document = Document(id=document_id, **data.model_dump())
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
        task = Task(id=task_id, **data.model_dump())
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
        event = CalendarEvent(id=event_id, **data.model_dump())
        self.calendar_events[event_id] = event
        return event

    def delete_calendar_event(self, event_id: str) -> None:
        if event_id not in self.calendar_events:
            raise NotFoundError("Termin nicht gefunden")
        del self.calendar_events[event_id]

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
