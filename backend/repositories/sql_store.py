"""SQLAlchemy-backed store — thin facade over domain repositories.

This class delegates all domain logic to extracted repository modules while
maintaining the same public API for backward compatibility with routers and tests.
"""

import logging

from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy.orm import Session

from ..models import (
    Account, AccountCreate,
    AllocationKey, AllocationKeyCreate,
    BillingPeriod, BillingPeriodCreate,
    Booking, BookingCreate,
    Budget, BudgetCreate,
    CalendarEvent, CalendarEventCreate,
    Category, CategoryCreate,
    ChangeHistoryEntry,
    Contact, ContactCreate,
    Contract, ContractCreate,
    CostItem, CostItemCreate,
    Deposit, DepositCreate,
    Document, DocumentCreate,
    EntityPhoto, EntityPhotoCreate,
    EscalationRule, EscalationRuleCreate,
    HandoverProtocol, HandoverProtocolCreate,
    Insurance, InsuranceCreate,
    Invoice, InvoiceCreate,
    Lead, LeadCreate,
    Listing, ListingCreate,
    ListingPhoto, ListingPhotoCreate,
    MaintenanceCase, MaintenanceCaseCreate,
    Message, MessageCreate,
    MessageThread, MessageThreadCreate,
    Meter, MeterCreate,
    MeterReading, MeterReadingCreate,
    Notification, NotificationCreate,
    NotificationTemplate, NotificationTemplateCreate,
    Portfolio, PortfolioCreate,
    Property, PropertyCreate,
    Receivable, ReceivableCreate,
    RentAdjustment, RentAdjustmentCreate,
    RentCharge, RentChargeCreate,
    StandaloneMeterReading, StandaloneMeterReadingCreate,
    Task, TaskCreate,
    TaxRate, TaxRateCreate,
    Tenant, TenantCreate,
    Unit, UnitCreate,
    UtilityStatement, UtilityStatementCreate,
    ViewingAppointment, ViewingAppointmentCreate,
)
from .billing_repo import BillingRepository
from .communication_repo import CommunicationRepository
from .document_repo import DocumentRepository
from .finance_repo import FinanceRepository
from .maintenance_repo import MaintenanceRepository
from .marketing_repo import MarketingRepository
from .portfolio_repo import PortfolioRepository
from .system_repo import SystemRepository
from .tenant_repo import TenantRepository

logger = logging.getLogger(__name__)


class SQLAlchemyStore:
    """Facade that composes domain repositories.

    All public methods delegate to the appropriate domain repository.
    Routers continue to import and use ``store.method_name()`` unchanged.
    """

    def __init__(self, db: Session):
        self.db = db

        # Domain repositories
        self.portfolio = PortfolioRepository(db)
        self.marketing = MarketingRepository(db, portfolio_repo=self.portfolio)
        self.tenant = TenantRepository(db, portfolio_repo=self.portfolio, marketing_repo=self.marketing)
        self.finance = FinanceRepository(db, portfolio_repo=self.portfolio, tenant_repo=self.tenant)
        self.billing = BillingRepository(db, portfolio_repo=self.portfolio, tenant_repo=self.tenant)
        self.document = DocumentRepository(db, portfolio_repo=self.portfolio, tenant_repo=self.tenant)
        self.communication = CommunicationRepository(db, portfolio_repo=self.portfolio)
        self.maintenance_repo = MaintenanceRepository(db, portfolio_repo=self.portfolio)
        self.system = SystemRepository(db)

    def _commit(self):
        self.db.commit()

    def clear_all(self) -> None:
        """Delete all rows from every mapped table. Used by tests to reset state."""
        from ..db.orm_models import Base
        for table in reversed(Base.metadata.sorted_tables):
            self.db.execute(table.delete())
        self._commit()

    # ── Generic helpers (used by search, admin, etc.) ──

    _ENTITY_TYPE_MAP = {
        "portfolio": ("portfolio", "_portfolios"),
        "property": ("portfolio", "_properties"),
        "unit": ("portfolio", "_units"),
        "account": ("portfolio", "_accounts"),
        "category": ("portfolio", "_categories"),
        "tenant": ("tenant", "_tenants"),
        "contract": ("tenant", "_contracts"),
        "viewing": ("tenant", "_viewings"),
        "handover_protocol": ("tenant", "_handover_protocols"),
        "lead": ("tenant", "_leads"),
        "deposit": ("tenant", "_deposits"),
        "rent_adjustment": ("tenant", "_rent_adjustments"),
        "meter_reading": ("tenant", "_meter_readings"),
        "booking": ("finance", "_bookings"),
        "receivable": ("finance", "_receivables"),
        "invoice": ("finance", "_invoices"),
        "tax_rate": ("finance", "_tax_rates"),
        "budget": ("finance", "_budgets"),
        "escalation_rule": ("finance", "_escalation_rules"),
        "insurance": ("finance", "_insurances"),
        "rent_charge": ("finance", "_rent_charges"),
        "meter": ("finance", "_meters"),
        "standalone_reading": ("finance", "_standalone_readings"),
        "billing_period": ("billing", "_billing_periods"),
        "allocation_key": ("billing", "_allocation_keys"),
        "cost_item": ("billing", "_cost_items"),
        "utility_statement": ("billing", "_utility_statements"),
        "document": ("document", "_documents"),
        "entity_photo": ("document", "_entity_photos"),
        "task": ("communication", "_tasks"),
        "calendar": ("communication", "_calendar"),
        "notification": ("communication", "_notifications"),
        "notification_template": ("communication", "_notification_templates"),
        "contact": ("communication", "_contacts"),
        "message_thread": ("communication", "_message_threads"),
        "message": ("communication", "_messages"),
        "maintenance": ("maintenance_repo", "_maintenance"),
        "listing": ("marketing", "_listings"),
        "listing_photo": ("marketing", "_listing_photos"),
    }

    def _resolve_repo(self, entity_type: str):
        """Return (domain_repo_instance, base_repo_instance) for an entity type."""
        mapping = self._ENTITY_TYPE_MAP.get(entity_type)
        if mapping is None:
            raise ValueError(f"Unknown entity type: {entity_type}")
        domain_attr, repo_attr = mapping
        domain_repo = getattr(self, domain_attr)
        return getattr(domain_repo, repo_attr)

    def _patch_entity(self, entity_type: str, entity_id: str, patch: PydanticBaseModel):
        """Apply a partial update using the entity type string to resolve the repository."""
        repo = self._resolve_repo(entity_type)
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
        repo = self._resolve_repo(entity_type)
        return repo.list_paginated(
            skip=skip, limit=limit, filters=filters,
            order_by=order_by, order_desc=order_desc,
        )

    def _count(self, entity_type: str, filters: dict | None = None) -> int:
        """Generic count using entity type to resolve the repository."""
        repo = self._resolve_repo(entity_type)
        return repo.count(filters=filters)

    def count_entities(self, entity_type: str, filters: dict | None = None) -> int:
        """Count entities of a given type, optionally filtered."""
        return self._count(entity_type, filters)

    # ══════════════════════════════════════════════════════════════════════
    # Delegation methods — one-liner proxies preserving the original API
    # ══════════════════════════════════════════════════════════════════════

    # --- Portfolios ---
    def list_portfolios(self) -> list[Portfolio]:
        return self.portfolio.list_portfolios()

    def create_portfolio(self, data: PortfolioCreate) -> Portfolio:
        return self.portfolio.create_portfolio(data)

    def get_portfolio(self, portfolio_id: str) -> Portfolio:
        return self.portfolio.get_portfolio(portfolio_id)

    def update_portfolio(self, portfolio_id: str, data: PortfolioCreate) -> Portfolio:
        return self.portfolio.update_portfolio(portfolio_id, data)

    def delete_portfolio(self, portfolio_id: str) -> None:
        self.portfolio.delete_portfolio(portfolio_id)

    # --- Accounts ---
    def list_accounts(self) -> list[Account]:
        return self.portfolio.list_accounts()

    def create_account(self, data: AccountCreate) -> Account:
        return self.portfolio.create_account(data)

    def get_account(self, account_id: str) -> Account:
        return self.portfolio.get_account(account_id)

    def update_account(self, account_id: str, data: AccountCreate) -> Account:
        return self.portfolio.update_account(account_id, data)

    def delete_account(self, account_id: str) -> None:
        self.portfolio.delete_account(account_id)

    # --- Categories ---
    def list_categories(self) -> list[Category]:
        return self.portfolio.list_categories()

    def create_category(self, data: CategoryCreate) -> Category:
        return self.portfolio.create_category(data)

    def get_category(self, category_id: str) -> Category:
        return self.portfolio.get_category(category_id)

    def update_category(self, category_id: str, data: CategoryCreate) -> Category:
        return self.portfolio.update_category(category_id, data)

    def delete_category(self, category_id: str) -> None:
        self.portfolio.delete_category(category_id)

    # --- Properties ---
    def list_properties(self) -> list[Property]:
        return self.portfolio.list_properties()

    def create_property(self, data: PropertyCreate) -> Property:
        return self.portfolio.create_property(data)

    def get_property(self, property_id: str) -> Property:
        return self.portfolio.get_property(property_id)

    def update_property(self, property_id: str, data: PropertyCreate) -> Property:
        return self.portfolio.update_property(property_id, data)

    def delete_property(self, property_id: str) -> None:
        self.portfolio.delete_property(property_id)

    # --- Units ---
    def list_units(self) -> list[Unit]:
        return self.portfolio.list_units()

    def create_unit(self, data: UnitCreate) -> Unit:
        return self.portfolio.create_unit(data)

    def get_unit(self, unit_id: str) -> Unit:
        return self.portfolio.get_unit(unit_id)

    def update_unit(self, unit_id: str, data: UnitCreate) -> Unit:
        return self.portfolio.update_unit(unit_id, data)

    def delete_unit(self, unit_id: str) -> None:
        self.portfolio.delete_unit(unit_id)

    # --- Tenants ---
    def list_tenants(self) -> list[Tenant]:
        return self.tenant.list_tenants()

    def create_tenant(self, data: TenantCreate) -> Tenant:
        return self.tenant.create_tenant(data)

    def get_tenant(self, tenant_id: str) -> Tenant:
        return self.tenant.get_tenant(tenant_id)

    def update_tenant(self, tenant_id: str, data: TenantCreate) -> Tenant:
        return self.tenant.update_tenant(tenant_id, data)

    def delete_tenant(self, tenant_id: str) -> None:
        self.tenant.delete_tenant(tenant_id)

    # --- Contracts ---
    def list_contracts(self) -> list[Contract]:
        return self.tenant.list_contracts()

    def create_contract(self, data: ContractCreate) -> Contract:
        return self.tenant.create_contract(data)

    def get_contract(self, contract_id: str) -> Contract:
        return self.tenant.get_contract(contract_id)

    def update_contract(self, contract_id: str, data: ContractCreate) -> Contract:
        return self.tenant.update_contract(contract_id, data)

    def delete_contract(self, contract_id: str) -> None:
        self.tenant.delete_contract(contract_id)

    # --- Bookings ---
    def list_bookings(self) -> list[Booking]:
        return self.finance.list_bookings()

    def create_booking(self, data: BookingCreate) -> Booking:
        return self.finance.create_booking(data)

    def get_booking(self, booking_id: str) -> Booking:
        return self.finance.get_booking(booking_id)

    def update_booking(self, booking_id: str, data: BookingCreate) -> Booking:
        return self.finance.update_booking(booking_id, data)

    def delete_booking(self, booking_id: str) -> None:
        self.finance.delete_booking(booking_id)

    # --- Receivables ---
    def list_receivables(self) -> list[Receivable]:
        return self.finance.list_receivables()

    def create_receivable(self, data: ReceivableCreate) -> Receivable:
        return self.finance.create_receivable(data)

    def get_receivable(self, receivable_id: str) -> Receivable:
        return self.finance.get_receivable(receivable_id)

    def update_receivable(self, receivable_id: str, data: ReceivableCreate) -> Receivable:
        return self.finance.update_receivable(receivable_id, data)

    def delete_receivable(self, receivable_id: str) -> None:
        self.finance.delete_receivable(receivable_id)

    # --- Invoices ---
    def list_invoices(self) -> list[Invoice]:
        return self.finance.list_invoices()

    def create_invoice(self, data: InvoiceCreate) -> Invoice:
        return self.finance.create_invoice(data)

    def get_invoice(self, invoice_id: str) -> Invoice:
        return self.finance.get_invoice(invoice_id)

    def update_invoice(self, invoice_id: str, data: InvoiceCreate) -> Invoice:
        return self.finance.update_invoice(invoice_id, data)

    def delete_invoice(self, invoice_id: str) -> None:
        self.finance.delete_invoice(invoice_id)

    # --- Maintenance Cases ---
    def list_maintenance_cases(self) -> list[MaintenanceCase]:
        return self.maintenance_repo.list_maintenance_cases()

    def create_maintenance_case(self, data: MaintenanceCaseCreate) -> MaintenanceCase:
        return self.maintenance_repo.create_maintenance_case(data)

    def get_maintenance_case(self, case_id: str) -> MaintenanceCase:
        return self.maintenance_repo.get_maintenance_case(case_id)

    def update_maintenance_case(self, case_id: str, data: MaintenanceCaseCreate) -> MaintenanceCase:
        return self.maintenance_repo.update_maintenance_case(case_id, data)

    def delete_maintenance_case(self, case_id: str) -> None:
        self.maintenance_repo.delete_maintenance_case(case_id)

    # --- Documents ---
    def list_documents(self) -> list[Document]:
        return self.document.list_documents()

    def create_document(self, data: DocumentCreate) -> Document:
        return self.document.create_document(data)

    def get_document(self, document_id: str) -> Document:
        return self.document.get_document(document_id)

    def update_document(self, document_id: str, data: DocumentCreate) -> Document:
        return self.document.update_document(document_id, data)

    def delete_document(self, document_id: str) -> None:
        self.document.delete_document(document_id)

    # --- Tasks ---
    def list_tasks(self) -> list[Task]:
        return self.communication.list_tasks()

    def create_task(self, data: TaskCreate) -> Task:
        return self.communication.create_task(data)

    def get_task(self, task_id: str) -> Task:
        return self.communication.get_task(task_id)

    def update_task(self, task_id: str, data: TaskCreate) -> Task:
        return self.communication.update_task(task_id, data)

    def delete_task(self, task_id: str) -> None:
        self.communication.delete_task(task_id)

    # --- Calendar Events ---
    def list_calendar_events(self) -> list[CalendarEvent]:
        return self.communication.list_calendar_events()

    def create_calendar_event(self, data: CalendarEventCreate) -> CalendarEvent:
        return self.communication.create_calendar_event(data)

    def get_calendar_event(self, event_id: str) -> CalendarEvent:
        return self.communication.get_calendar_event(event_id)

    def update_calendar_event(self, event_id: str, data: CalendarEventCreate) -> CalendarEvent:
        return self.communication.update_calendar_event(event_id, data)

    def delete_calendar_event(self, event_id: str) -> None:
        self.communication.delete_calendar_event(event_id)

    # --- Listings ---
    def list_listings(self) -> list[Listing]:
        return self.marketing.list_listings()

    def create_listing(self, data: ListingCreate) -> Listing:
        return self.marketing.create_listing(data)

    def get_listing(self, listing_id: str) -> Listing:
        return self.marketing.get_listing(listing_id)

    def update_listing(self, listing_id: str, data: ListingCreate) -> Listing:
        return self.marketing.update_listing(listing_id, data)

    def delete_listing(self, listing_id: str) -> None:
        self.marketing.delete_listing(listing_id)

    # --- Listing Photos ---
    def list_listing_photos(self) -> list[ListingPhoto]:
        return self.marketing.list_listing_photos()

    def create_listing_photo(self, data: ListingPhotoCreate) -> ListingPhoto:
        return self.marketing.create_listing_photo(data)

    def get_listing_photo(self, photo_id: str) -> ListingPhoto:
        return self.marketing.get_listing_photo(photo_id)

    def update_listing_photo(self, photo_id: str, data: ListingPhotoCreate) -> ListingPhoto:
        return self.marketing.update_listing_photo(photo_id, data)

    def delete_listing_photo(self, photo_id: str) -> None:
        self.marketing.delete_listing_photo(photo_id)

    # --- Leads ---
    def list_leads(self) -> list[Lead]:
        return self.tenant.list_leads()

    def create_lead(self, data: LeadCreate) -> Lead:
        return self.tenant.create_lead(data)

    def get_lead(self, lead_id: str) -> Lead:
        return self.tenant.get_lead(lead_id)

    def update_lead(self, lead_id: str, data: LeadCreate) -> Lead:
        return self.tenant.update_lead(lead_id, data)

    def delete_lead(self, lead_id: str) -> None:
        self.tenant.delete_lead(lead_id)

    # --- Viewing Appointments ---
    def list_viewing_appointments(self) -> list[ViewingAppointment]:
        return self.tenant.list_viewing_appointments()

    def create_viewing_appointment(self, data: ViewingAppointmentCreate) -> ViewingAppointment:
        return self.tenant.create_viewing_appointment(data)

    def get_viewing_appointment(self, appointment_id: str) -> ViewingAppointment:
        return self.tenant.get_viewing_appointment(appointment_id)

    def update_viewing_appointment(self, appointment_id: str, data: ViewingAppointmentCreate) -> ViewingAppointment:
        return self.tenant.update_viewing_appointment(appointment_id, data)

    def delete_viewing_appointment(self, appointment_id: str) -> None:
        self.tenant.delete_viewing_appointment(appointment_id)

    # --- Billing Periods ---
    def list_billing_periods(self) -> list[BillingPeriod]:
        return self.billing.list_billing_periods()

    def create_billing_period(self, data: BillingPeriodCreate) -> BillingPeriod:
        return self.billing.create_billing_period(data)

    def get_billing_period(self, period_id: str) -> BillingPeriod:
        return self.billing.get_billing_period(period_id)

    def update_billing_period(self, period_id: str, data: BillingPeriodCreate) -> BillingPeriod:
        return self.billing.update_billing_period(period_id, data)

    def delete_billing_period(self, period_id: str) -> None:
        self.billing.delete_billing_period(period_id)

    # --- Allocation Keys ---
    def list_allocation_keys(self) -> list[AllocationKey]:
        return self.billing.list_allocation_keys()

    def create_allocation_key(self, data: AllocationKeyCreate) -> AllocationKey:
        return self.billing.create_allocation_key(data)

    def get_allocation_key(self, key_id: str) -> AllocationKey:
        return self.billing.get_allocation_key(key_id)

    def update_allocation_key(self, key_id: str, data: AllocationKeyCreate) -> AllocationKey:
        return self.billing.update_allocation_key(key_id, data)

    def delete_allocation_key(self, key_id: str) -> None:
        self.billing.delete_allocation_key(key_id)

    # --- Cost Items ---
    def list_cost_items(self) -> list[CostItem]:
        return self.billing.list_cost_items()

    def create_cost_item(self, data: CostItemCreate) -> CostItem:
        return self.billing.create_cost_item(data)

    def get_cost_item(self, item_id: str) -> CostItem:
        return self.billing.get_cost_item(item_id)

    def update_cost_item(self, item_id: str, data: CostItemCreate) -> CostItem:
        return self.billing.update_cost_item(item_id, data)

    def delete_cost_item(self, item_id: str) -> None:
        self.billing.delete_cost_item(item_id)

    # --- Utility Statements ---
    def list_utility_statements(self) -> list[UtilityStatement]:
        return self.billing.list_utility_statements()

    def create_utility_statement(self, data: UtilityStatementCreate) -> UtilityStatement:
        return self.billing.create_utility_statement(data)

    def get_utility_statement(self, statement_id: str) -> UtilityStatement:
        return self.billing.get_utility_statement(statement_id)

    def update_utility_statement(self, statement_id: str, data: UtilityStatementCreate) -> UtilityStatement:
        return self.billing.update_utility_statement(statement_id, data)

    def delete_utility_statement(self, statement_id: str) -> None:
        self.billing.delete_utility_statement(statement_id)

    # --- Deposits ---
    def list_deposits(self) -> list[Deposit]:
        return self.tenant.list_deposits()

    def create_deposit(self, data: DepositCreate) -> Deposit:
        return self.tenant.create_deposit(data)

    def get_deposit(self, deposit_id: str) -> Deposit:
        return self.tenant.get_deposit(deposit_id)

    def update_deposit(self, deposit_id: str, data: DepositCreate) -> Deposit:
        return self.tenant.update_deposit(deposit_id, data)

    def delete_deposit(self, deposit_id: str) -> None:
        self.tenant.delete_deposit(deposit_id)

    # --- Notifications ---
    def list_notifications(self) -> list[Notification]:
        return self.communication.list_notifications()

    def create_notification(self, data: NotificationCreate) -> Notification:
        return self.communication.create_notification(data)

    def get_notification(self, notification_id: str) -> Notification:
        return self.communication.get_notification(notification_id)

    def mark_notification_read(self, notification_id: str) -> Notification:
        return self.communication.mark_notification_read(notification_id)

    def delete_notification(self, notification_id: str) -> None:
        self.communication.delete_notification(notification_id)

    # --- Notification Templates ---
    def list_notification_templates(self) -> list[NotificationTemplate]:
        return self.communication.list_notification_templates()

    def create_notification_template(self, data: NotificationTemplateCreate) -> NotificationTemplate:
        return self.communication.create_notification_template(data)

    def get_notification_template(self, template_id: str) -> NotificationTemplate:
        return self.communication.get_notification_template(template_id)

    def update_notification_template(self, template_id: str, data: NotificationTemplateCreate) -> NotificationTemplate:
        return self.communication.update_notification_template(template_id, data)

    def delete_notification_template(self, template_id: str) -> None:
        self.communication.delete_notification_template(template_id)

    # --- Tax Rates ---
    def list_tax_rates(self) -> list[TaxRate]:
        return self.finance.list_tax_rates()

    def create_tax_rate(self, data: TaxRateCreate) -> TaxRate:
        return self.finance.create_tax_rate(data)

    def get_tax_rate(self, tax_rate_id: str) -> TaxRate:
        return self.finance.get_tax_rate(tax_rate_id)

    def update_tax_rate(self, tax_rate_id: str, data: TaxRateCreate) -> TaxRate:
        return self.finance.update_tax_rate(tax_rate_id, data)

    def delete_tax_rate(self, tax_rate_id: str) -> None:
        self.finance.delete_tax_rate(tax_rate_id)

    # --- Rent Adjustments ---
    def list_rent_adjustments(self) -> list[RentAdjustment]:
        return self.tenant.list_rent_adjustments()

    def create_rent_adjustment(self, data: RentAdjustmentCreate) -> RentAdjustment:
        return self.tenant.create_rent_adjustment(data)

    def get_rent_adjustment(self, adj_id: str) -> RentAdjustment:
        return self.tenant.get_rent_adjustment(adj_id)

    def update_rent_adjustment(self, adj_id: str, data: RentAdjustmentCreate) -> RentAdjustment:
        return self.tenant.update_rent_adjustment(adj_id, data)

    def delete_rent_adjustment(self, adj_id: str) -> None:
        self.tenant.delete_rent_adjustment(adj_id)

    # --- Handover Protocols ---
    def list_handover_protocols(self) -> list[HandoverProtocol]:
        return self.tenant.list_handover_protocols()

    def create_handover_protocol(self, data: HandoverProtocolCreate) -> HandoverProtocol:
        return self.tenant.create_handover_protocol(data)

    def get_handover_protocol(self, protocol_id: str) -> HandoverProtocol:
        return self.tenant.get_handover_protocol(protocol_id)

    def update_handover_protocol(self, protocol_id: str, data: HandoverProtocolCreate) -> HandoverProtocol:
        return self.tenant.update_handover_protocol(protocol_id, data)

    def delete_handover_protocol(self, protocol_id: str) -> None:
        self.tenant.delete_handover_protocol(protocol_id)

    # --- Meter Readings ---
    def list_meter_readings(self) -> list[MeterReading]:
        return self.tenant.list_meter_readings()

    def create_meter_reading(self, data: MeterReadingCreate) -> MeterReading:
        return self.tenant.create_meter_reading(data)

    def get_meter_reading(self, reading_id: str) -> MeterReading:
        return self.tenant.get_meter_reading(reading_id)

    def update_meter_reading(self, reading_id: str, data: MeterReadingCreate) -> MeterReading:
        return self.tenant.update_meter_reading(reading_id, data)

    def delete_meter_reading(self, reading_id: str) -> None:
        self.tenant.delete_meter_reading(reading_id)

    # --- Budgets ---
    def list_budgets(self) -> list[Budget]:
        return self.finance.list_budgets()

    def create_budget(self, data: BudgetCreate) -> Budget:
        return self.finance.create_budget(data)

    def get_budget(self, budget_id: str) -> Budget:
        return self.finance.get_budget(budget_id)

    def update_budget(self, budget_id: str, data: BudgetCreate) -> Budget:
        return self.finance.update_budget(budget_id, data)

    def delete_budget(self, budget_id: str) -> None:
        self.finance.delete_budget(budget_id)

    # --- Escalation Rules ---
    def list_escalation_rules(self) -> list[EscalationRule]:
        return self.finance.list_escalation_rules()

    def create_escalation_rule(self, data: EscalationRuleCreate) -> EscalationRule:
        return self.finance.create_escalation_rule(data)

    def get_escalation_rule(self, rule_id: str) -> EscalationRule:
        return self.finance.get_escalation_rule(rule_id)

    def update_escalation_rule(self, rule_id: str, data: EscalationRuleCreate) -> EscalationRule:
        return self.finance.update_escalation_rule(rule_id, data)

    def delete_escalation_rule(self, rule_id: str) -> None:
        self.finance.delete_escalation_rule(rule_id)

    # --- Change History ---
    def list_change_history(self) -> list[ChangeHistoryEntry]:
        return self.system.list_change_history()

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
        return self.system.add_change_history(
            entity_type, entity_id, field_name, old_value, new_value,
            changed_by=changed_by, reason=reason,
        )

    def get_entity_history(self, entity_type: str, entity_id: str) -> list[ChangeHistoryEntry]:
        return self.system.get_entity_history(entity_type, entity_id)

    # --- Insurances ---
    def list_insurances(self) -> list[Insurance]:
        return self.finance.list_insurances()

    def create_insurance(self, data: InsuranceCreate) -> Insurance:
        return self.finance.create_insurance(data)

    def get_insurance(self, insurance_id: str) -> Insurance:
        return self.finance.get_insurance(insurance_id)

    def update_insurance(self, insurance_id: str, data: InsuranceCreate) -> Insurance:
        return self.finance.update_insurance(insurance_id, data)

    def delete_insurance(self, insurance_id: str) -> None:
        self.finance.delete_insurance(insurance_id)

    # --- Entity Photos ---
    def list_entity_photos(self, entity_type: str, entity_id: str) -> list[EntityPhoto]:
        return self.document.list_entity_photos(entity_type, entity_id)

    def create_entity_photo(self, data: EntityPhotoCreate) -> EntityPhoto:
        return self.document.create_entity_photo(data)

    def get_entity_photo(self, photo_id: str) -> EntityPhoto:
        return self.document.get_entity_photo(photo_id)

    def delete_entity_photo(self, photo_id: str) -> None:
        self.document.delete_entity_photo(photo_id)

    # --- Contacts ---
    def list_contacts(self) -> list[Contact]:
        return self.communication.list_contacts()

    def create_contact(self, data: ContactCreate) -> Contact:
        return self.communication.create_contact(data)

    def get_contact(self, contact_id: str) -> Contact:
        return self.communication.get_contact(contact_id)

    def update_contact(self, contact_id: str, data: ContactCreate) -> Contact:
        return self.communication.update_contact(contact_id, data)

    def delete_contact(self, contact_id: str) -> None:
        self.communication.delete_contact(contact_id)

    # --- Meters ---
    def list_meters(self) -> list[Meter]:
        return self.finance.list_meters()

    def create_meter(self, data: MeterCreate) -> Meter:
        return self.finance.create_meter(data)

    def get_meter(self, meter_id: str) -> Meter:
        return self.finance.get_meter(meter_id)

    def update_meter(self, meter_id: str, data: MeterCreate) -> Meter:
        return self.finance.update_meter(meter_id, data)

    def delete_meter(self, meter_id: str) -> None:
        self.finance.delete_meter(meter_id)

    # --- Standalone Meter Readings ---
    def list_standalone_meter_readings(self) -> list[StandaloneMeterReading]:
        return self.finance.list_standalone_meter_readings()

    def create_standalone_meter_reading(self, data: StandaloneMeterReadingCreate) -> StandaloneMeterReading:
        return self.finance.create_standalone_meter_reading(data)

    def get_standalone_meter_reading(self, reading_id: str) -> StandaloneMeterReading:
        return self.finance.get_standalone_meter_reading(reading_id)

    def update_standalone_meter_reading(self, reading_id: str, data: StandaloneMeterReadingCreate) -> StandaloneMeterReading:
        return self.finance.update_standalone_meter_reading(reading_id, data)

    def delete_standalone_meter_reading(self, reading_id: str) -> None:
        self.finance.delete_standalone_meter_reading(reading_id)

    # --- Message Threads ---
    def list_message_threads(self) -> list[MessageThread]:
        return self.communication.list_message_threads()

    def create_message_thread(self, data: MessageThreadCreate) -> MessageThread:
        return self.communication.create_message_thread(data)

    def get_message_thread(self, thread_id: str) -> MessageThread:
        return self.communication.get_message_thread(thread_id)

    def update_message_thread(self, thread_id: str, data: MessageThreadCreate) -> MessageThread:
        return self.communication.update_message_thread(thread_id, data)

    def delete_message_thread(self, thread_id: str) -> None:
        self.communication.delete_message_thread(thread_id)

    # --- Messages ---
    def list_messages(self, *, thread_id: str | None = None) -> list[Message]:
        return self.communication.list_messages(thread_id=thread_id)

    def create_message(self, data: MessageCreate) -> Message:
        return self.communication.create_message(data)

    def get_message(self, message_id: str) -> Message:
        return self.communication.get_message(message_id)

    def delete_message(self, message_id: str) -> None:
        self.communication.delete_message(message_id)

    # --- Rent Charges ---
    def list_rent_charges(self) -> list[RentCharge]:
        return self.finance.list_rent_charges()

    def create_rent_charge(self, data: RentChargeCreate) -> RentCharge:
        return self.finance.create_rent_charge(data)

    def get_rent_charge(self, charge_id: str) -> RentCharge:
        return self.finance.get_rent_charge(charge_id)

    def update_rent_charge(self, charge_id: str, data: RentChargeCreate) -> RentCharge:
        return self.finance.update_rent_charge(charge_id, data)

    def delete_rent_charge(self, charge_id: str) -> None:
        self.finance.delete_rent_charge(charge_id)
