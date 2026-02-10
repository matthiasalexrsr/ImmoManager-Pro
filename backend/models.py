from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class PortfolioCreate(BaseModel):
    name: str
    description: Optional[str] = None
    owner_name: Optional[str] = None
    currency: str = "EUR"
    timezone: str = "Europe/Berlin"
    status: str = "active"


class Portfolio(PortfolioCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PropertyCreate(BaseModel):
    portfolio_id: str
    name: str
    property_type: str
    status: str = "active"
    year_built: Optional[int] = None
    living_area_sqm: Optional[float] = None
    usable_area_sqm: Optional[float] = None
    plot_area_sqm: Optional[float] = None
    ownership_share: Optional[float] = None
    purchase_price: Optional[float] = None
    purchase_date: Optional[date] = None
    market_value: Optional[float] = None
    valuation_date: Optional[date] = None
    address_line: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


class Property(PropertyCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UnitCreate(BaseModel):
    property_id: str
    label: str
    unit_type: str
    status: str = "vacant"
    area_sqm: Optional[float] = None
    rooms: Optional[float] = None
    floor: Optional[str] = None
    cold_rent: Optional[float] = None
    service_charge_advance: Optional[float] = None
    heating_advance: Optional[float] = None
    features: Optional[str] = None


class Unit(UnitCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TenantCreate(BaseModel):
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address_line: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    payment_method: Optional[str] = None
    sepa_mandate: Optional[str] = None
    notes: Optional[str] = None


class Tenant(TenantCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ContractCreate(BaseModel):
    contract_number: str
    property_id: str
    unit_id: str
    tenant_id: str
    status: str = "active"
    start_date: date
    end_date: Optional[date] = None
    notice_period: Optional[str] = None
    deposit_amount: Optional[float] = None
    index_rent: Optional[str] = None
    service_charge_settlement: Optional[str] = None


class Contract(ContractCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AccountCreate(BaseModel):
    portfolio_id: str
    name: str
    bank_name: Optional[str] = None
    iban: Optional[str] = None
    bic: Optional[str] = None
    account_type: str
    opening_balance: float = 0.0
    balance: float = 0.0


class Account(AccountCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CategoryCreate(BaseModel):
    portfolio_id: str
    name: str
    category_type: str


class Category(CategoryCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BookingCreate(BaseModel):
    account_id: str
    category_id: Optional[str] = None
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    tenant_id: Optional[str] = None
    booking_date: date
    amount: float
    status: str = "open"
    payment_text: Optional[str] = None
    receipt_url: Optional[str] = None


class Booking(BookingCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ReceivableCreate(BaseModel):
    contract_id: str
    due_date: date
    amount_due: float
    dunning_level: Optional[str] = None
    status: str = "open"


class Receivable(ReceivableCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class InvoiceCreate(BaseModel):
    property_id: Optional[str] = None
    supplier: str
    invoice_date: date
    due_date: Optional[date] = None
    net_amount: float
    vat_amount: float = 0.0
    gross_amount: float
    payment_terms: Optional[str] = None
    status: str = "open"


class Invoice(InvoiceCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MaintenanceCaseCreate(BaseModel):
    property_id: str
    unit_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    priority: str = "medium"
    status: str = "open"
    reported_by: Optional[str] = None
    assignee: Optional[str] = None
    due_date: Optional[date] = None
    estimated_cost: Optional[float] = None
    contractor: Optional[str] = None
    appointment_at: Optional[date] = None


class MaintenanceCase(MaintenanceCaseCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DocumentCreate(BaseModel):
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    contract_id: Optional[str] = None
    title: str
    document_type: Optional[str] = None
    document_date: Optional[date] = None
    tags: Optional[str] = None
    description: Optional[str] = None
    file_url: str


class Document(DocumentCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    assignee: Optional[str] = None
    due_date: Optional[date] = None
    priority: str = "medium"
    status: str = "open"
    property_id: Optional[str] = None
    unit_id: Optional[str] = None


class Task(TaskCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CalendarEventCreate(BaseModel):
    title: str
    event_type: str
    event_date: date
    event_time: Optional[str] = None
    location: Optional[str] = None
    participants: Optional[str] = None
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    description: Optional[str] = None


class CalendarEvent(CalendarEventCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ListingCreate(BaseModel):
    unit_id: str
    title: str
    description: Optional[str] = None
    portal: Optional[str] = None
    listing_url: Optional[str] = None
    status: str = "draft"
    target_rent: Optional[float] = None
    service_charge: Optional[float] = None
    available_from: Optional[date] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None


class Listing(ListingCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ListingPhotoCreate(BaseModel):
    listing_id: str
    title: Optional[str] = None
    file_url: str
    is_primary: bool = False
    sort_order: int = 0


class ListingPhoto(ListingPhotoCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Patch (partial update) models – all fields optional
# ---------------------------------------------------------------------------


class PortfolioPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    owner_name: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None
    status: Optional[str] = None


class PropertyPatch(BaseModel):
    portfolio_id: Optional[str] = None
    name: Optional[str] = None
    property_type: Optional[str] = None
    status: Optional[str] = None
    year_built: Optional[int] = None
    living_area_sqm: Optional[float] = None
    usable_area_sqm: Optional[float] = None
    plot_area_sqm: Optional[float] = None
    ownership_share: Optional[float] = None
    purchase_price: Optional[float] = None
    purchase_date: Optional[date] = None
    market_value: Optional[float] = None
    valuation_date: Optional[date] = None
    address_line: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


class UnitPatch(BaseModel):
    property_id: Optional[str] = None
    label: Optional[str] = None
    unit_type: Optional[str] = None
    status: Optional[str] = None
    area_sqm: Optional[float] = None
    rooms: Optional[float] = None
    floor: Optional[str] = None
    cold_rent: Optional[float] = None
    service_charge_advance: Optional[float] = None
    heating_advance: Optional[float] = None
    features: Optional[str] = None


class TenantPatch(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address_line: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    payment_method: Optional[str] = None
    sepa_mandate: Optional[str] = None
    notes: Optional[str] = None


class ContractPatch(BaseModel):
    contract_number: Optional[str] = None
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    tenant_id: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notice_period: Optional[str] = None
    deposit_amount: Optional[float] = None
    index_rent: Optional[str] = None
    service_charge_settlement: Optional[str] = None


class AccountPatch(BaseModel):
    portfolio_id: Optional[str] = None
    name: Optional[str] = None
    bank_name: Optional[str] = None
    iban: Optional[str] = None
    bic: Optional[str] = None
    account_type: Optional[str] = None
    opening_balance: Optional[float] = None
    balance: Optional[float] = None


class CategoryPatch(BaseModel):
    portfolio_id: Optional[str] = None
    name: Optional[str] = None
    category_type: Optional[str] = None


class BookingPatch(BaseModel):
    account_id: Optional[str] = None
    category_id: Optional[str] = None
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    tenant_id: Optional[str] = None
    booking_date: Optional[date] = None
    amount: Optional[float] = None
    status: Optional[str] = None
    payment_text: Optional[str] = None
    receipt_url: Optional[str] = None


class ReceivablePatch(BaseModel):
    contract_id: Optional[str] = None
    due_date: Optional[date] = None
    amount_due: Optional[float] = None
    dunning_level: Optional[str] = None
    status: Optional[str] = None


class InvoicePatch(BaseModel):
    property_id: Optional[str] = None
    supplier: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    net_amount: Optional[float] = None
    vat_amount: Optional[float] = None
    gross_amount: Optional[float] = None
    payment_terms: Optional[str] = None
    status: Optional[str] = None


class MaintenanceCasePatch(BaseModel):
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    reported_by: Optional[str] = None
    assignee: Optional[str] = None
    due_date: Optional[date] = None
    estimated_cost: Optional[float] = None
    contractor: Optional[str] = None
    appointment_at: Optional[date] = None


class DocumentPatch(BaseModel):
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    contract_id: Optional[str] = None
    title: Optional[str] = None
    document_type: Optional[str] = None
    document_date: Optional[date] = None
    tags: Optional[str] = None
    description: Optional[str] = None
    file_url: Optional[str] = None


class TaskPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assignee: Optional[str] = None
    due_date: Optional[date] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    property_id: Optional[str] = None
    unit_id: Optional[str] = None


class CalendarEventPatch(BaseModel):
    title: Optional[str] = None
    event_type: Optional[str] = None
    event_date: Optional[date] = None
    event_time: Optional[str] = None
    location: Optional[str] = None
    participants: Optional[str] = None
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    description: Optional[str] = None


class ListingPatch(BaseModel):
    unit_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    portal: Optional[str] = None
    listing_url: Optional[str] = None
    status: Optional[str] = None
    target_rent: Optional[float] = None
    service_charge: Optional[float] = None
    available_from: Optional[date] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None


class ListingPhotoPatch(BaseModel):
    listing_id: Optional[str] = None
    title: Optional[str] = None
    file_url: Optional[str] = None
    is_primary: Optional[bool] = None
    sort_order: Optional[int] = None


# ---------------------------------------------------------------------------
# Phase 3.1: Leads & Viewings (Interessenten & Besichtigungen)
# ---------------------------------------------------------------------------


class LeadCreate(BaseModel):
    listing_id: Optional[str] = None
    unit_id: Optional[str] = None
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    status: str = "new"
    notes: Optional[str] = None


class Lead(LeadCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class LeadPatch(BaseModel):
    listing_id: Optional[str] = None
    unit_id: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class ViewingAppointmentCreate(BaseModel):
    lead_id: str
    unit_id: str
    scheduled_at: datetime
    status: str = "scheduled"
    agent: Optional[str] = None
    notes: Optional[str] = None


class ViewingAppointment(ViewingAppointmentCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ViewingAppointmentPatch(BaseModel):
    lead_id: Optional[str] = None
    unit_id: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    status: Optional[str] = None
    agent: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Phase 3.2: Billing Periods & Utility Statements (Betriebskostenabrechnung)
# ---------------------------------------------------------------------------


class BillingPeriodCreate(BaseModel):
    property_id: str
    label: str
    start_date: date
    end_date: date
    status: str = "draft"


class BillingPeriod(BillingPeriodCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BillingPeriodPatch(BaseModel):
    property_id: Optional[str] = None
    label: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[str] = None


class AllocationKeyCreate(BaseModel):
    property_id: str
    name: str
    key_type: str  # area_sqm, unit_count, person_count, consumption
    description: Optional[str] = None


class AllocationKey(AllocationKeyCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AllocationKeyPatch(BaseModel):
    property_id: Optional[str] = None
    name: Optional[str] = None
    key_type: Optional[str] = None
    description: Optional[str] = None


class CostItemCreate(BaseModel):
    billing_period_id: str
    description: str
    amount: float
    allocation_key_id: str


class CostItem(CostItemCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CostItemPatch(BaseModel):
    billing_period_id: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    allocation_key_id: Optional[str] = None


class UtilityStatementCreate(BaseModel):
    billing_period_id: str
    contract_id: str
    unit_id: str
    total_cost: float
    advance_paid: float
    balance: float  # positive = tenant owes, negative = refund
    status: str = "draft"
    notes: Optional[str] = None


class UtilityStatement(UtilityStatementCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UtilityStatementPatch(BaseModel):
    billing_period_id: Optional[str] = None
    contract_id: Optional[str] = None
    unit_id: Optional[str] = None
    total_cost: Optional[float] = None
    advance_paid: Optional[float] = None
    balance: Optional[float] = None
    status: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Phase 3.3: Deposits (Kautionsverwaltung)
# ---------------------------------------------------------------------------


class DepositCreate(BaseModel):
    contract_id: str
    amount: float
    status: str = "held"  # held, partially_returned, returned
    held_date: Optional[date] = None
    return_date: Optional[date] = None
    deductions: Optional[float] = None
    deduction_reason: Optional[str] = None
    notes: Optional[str] = None


class Deposit(DepositCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DepositPatch(BaseModel):
    contract_id: Optional[str] = None
    amount: Optional[float] = None
    status: Optional[str] = None
    held_date: Optional[date] = None
    return_date: Optional[date] = None
    deductions: Optional[float] = None
    deduction_reason: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Phase 3.4: Notifications (Benachrichtigungen)
# ---------------------------------------------------------------------------


class NotificationCreate(BaseModel):
    notification_type: str  # overdue_payment, contract_expiry, task_due, maintenance, general
    title: str
    content: str
    severity: str = "info"  # info, warning, critical
    entity_type: Optional[str] = None  # contract, receivable, task, etc.
    entity_id: Optional[str] = None
    status: str = "unread"  # unread, read, archived


class Notification(NotificationCreate):
    id: str = Field(..., min_length=1)
    read_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class NotificationPatch(BaseModel):
    notification_type: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    severity: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    status: Optional[str] = None
    read_at: Optional[datetime] = None


class NotificationTemplateCreate(BaseModel):
    name: str
    notification_type: str
    title_template: str
    content_template: str
    severity: str = "info"


class NotificationTemplate(NotificationTemplateCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class NotificationTemplatePatch(BaseModel):
    name: Optional[str] = None
    notification_type: Optional[str] = None
    title_template: Optional[str] = None
    content_template: Optional[str] = None
    severity: Optional[str] = None
