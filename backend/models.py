from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


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
    person_count: Optional[int] = None


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
    archived: bool = False

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and "@" not in v:
            raise ValueError("Ungültige E-Mail-Adresse")
        return v


class Tenant(TenantCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


_VALID_CONTRACT_STATUSES = {"active", "terminated", "expired", "draft"}


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

    @field_validator("end_date")
    @classmethod
    def validate_end_after_start(cls, v: Optional[date], info) -> Optional[date]:
        if v is not None and "start_date" in info.data and info.data["start_date"] is not None:
            if v < info.data["start_date"]:
                raise ValueError("Enddatum muss nach Startdatum liegen")
        return v

    @field_validator("status")
    @classmethod
    def validate_contract_status(cls, v: str) -> str:
        if v not in _VALID_CONTRACT_STATUSES:
            raise ValueError(f"Ungültiger Status. Erlaubt: {', '.join(sorted(_VALID_CONTRACT_STATUSES))}")
        return v


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
    statement_id: Optional[str] = None  # link back to source UtilityStatement


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
    vat_rate: float = 19.0  # T14: VAT rate percentage (0, 7, 19)
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
    appointment_at: Optional[datetime] = None


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
    recurrence_rule: Optional[str] = None  # iCal RRULE (e.g. "FREQ=MONTHLY;INTERVAL=1")
    parent_task_id: Optional[str] = None  # links recurring instances to template


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
    person_count: Optional[int] = None


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
    archived: Optional[bool] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and "@" not in v:
            raise ValueError("Ungültige E-Mail-Adresse")
        return v


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
    statement_id: Optional[str] = None


class InvoicePatch(BaseModel):
    property_id: Optional[str] = None
    supplier: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    net_amount: Optional[float] = None
    vat_rate: Optional[float] = None
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
    appointment_at: Optional[datetime] = None


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
    recurrence_rule: Optional[str] = None
    parent_task_id: Optional[str] = None


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
    priority: int = 0
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
    priority: Optional[int] = None
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

    @field_validator("end_date")
    @classmethod
    def validate_period_end_after_start(cls, v: date, info) -> date:
        if "start_date" in info.data and info.data["start_date"] is not None:
            if v < info.data["start_date"]:
                raise ValueError("Enddatum muss nach Startdatum liegen")
        return v


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
    is_recoverable: bool = True  # umlagefähig
    cost_category: Optional[str] = None  # e.g. "water", "heating", "garbage"
    source_document_id: Optional[str] = None
    vat_rate: Optional[float] = None
    net_amount: Optional[float] = None
    gross_amount: Optional[float] = None


class CostItem(CostItemCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CostItemPatch(BaseModel):
    billing_period_id: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    allocation_key_id: Optional[str] = None
    is_recoverable: Optional[bool] = None
    cost_category: Optional[str] = None
    source_document_id: Optional[str] = None
    vat_rate: Optional[float] = None
    net_amount: Optional[float] = None
    gross_amount: Optional[float] = None


class UtilityStatementCreate(BaseModel):
    billing_period_id: str
    contract_id: str
    unit_id: str
    total_cost: float
    advance_paid: float
    balance: float  # positive = tenant owes, negative = refund
    status: str = "draft"
    revision: int = 1  # T19: revision-safe versioning
    revision_notes: Optional[str] = None
    notes: Optional[str] = None
    line_items: Optional[list[dict]] = None  # [{description, allocated_amount}]
    delivery_status: Optional[str] = None  # pending | sent | delivered | failed
    delivered_at: Optional[datetime] = None
    delivery_channel: Optional[str] = None  # email | post | portal
    snapshot_hash: Optional[str] = None  # immutable content hash after finalization


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
    revision: Optional[int] = None
    revision_notes: Optional[str] = None
    notes: Optional[str] = None
    line_items: Optional[list[dict]] = None
    delivery_status: Optional[str] = None
    delivered_at: Optional[datetime] = None
    delivery_channel: Optional[str] = None
    snapshot_hash: Optional[str] = None


class BillingPreflightIssue(BaseModel):
    code: str
    message: str
    severity: str  # blocker | warning
    context: Optional[str] = None


class BillingPreflightResult(BaseModel):
    billing_period_id: str
    has_blockers: bool
    blockers: list[BillingPreflightIssue] = Field(default_factory=list)
    warnings: list[BillingPreflightIssue] = Field(default_factory=list)
    metrics: dict[str, float | int | str | bool] = Field(default_factory=dict)


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


# ---------------------------------------------------------------------------
# Phase 5.1: Authentication & Users
# ---------------------------------------------------------------------------


_VALID_ROLES = {"eigentuemer", "verwalter", "buchhaltung", "techniker", "readonly"}


class UserCreate(BaseModel):
    username: str
    email: str
    full_name: str
    password: str = Field(..., min_length=6)
    role: str = "readonly"  # eigentuemer, verwalter, buchhaltung, techniker, readonly

    @field_validator("email")
    @classmethod
    def validate_user_email(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("Ungültige E-Mail-Adresse")
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in _VALID_ROLES:
            raise ValueError(f"Ungültige Rolle. Erlaubt: {', '.join(sorted(_VALID_ROLES))}")
        return v


class UserRead(BaseModel):
    id: str = Field(..., min_length=1)
    username: str
    email: str
    full_name: str
    role: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UserPatch(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str  # user_id
    exp: datetime
    type: str  # access or refresh
    jti: Optional[str] = None  # unique token identifier for rotation


class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: Optional[str] = None  # required when 2FA is enabled


class RefreshRequest(BaseModel):
    refresh_token: str


# ---------------------------------------------------------------------------
# Phase 5.3: Audit Logging
# ---------------------------------------------------------------------------


class AuditLogEntry(BaseModel):
    id: str = Field(..., min_length=1)
    user_id: Optional[str] = None
    username: Optional[str] = None
    action: str  # create, update, patch, delete
    entity_type: str  # portfolio, property, unit, etc.
    entity_id: str
    changes: Optional[str] = None  # JSON diff
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# T14: VAT / Tax Rates (Steuerlogik)
# ---------------------------------------------------------------------------


_VALID_VAT_RATES = {0.0, 7.0, 19.0}


class TaxRateCreate(BaseModel):
    name: str  # e.g. "Regelsteuersatz", "Ermäßigt", "Steuerfrei"
    rate: float  # percentage, e.g. 19.0
    description: Optional[str] = None
    is_default: bool = False
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None


class TaxRate(TaxRateCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TaxRatePatch(BaseModel):
    name: Optional[str] = None
    rate: Optional[float] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None


# ---------------------------------------------------------------------------
# T15: Index / Stepped Rent (Indexmiete / Staffelmiete)
# ---------------------------------------------------------------------------


class RentAdjustmentCreate(BaseModel):
    contract_id: str
    adjustment_type: str  # "index" or "stepped"
    effective_date: date
    previous_rent: float
    new_rent: float
    increase_percent: Optional[float] = None
    index_base_year: Optional[int] = None  # CPI base year for index rent
    index_value: Optional[float] = None  # CPI value at adjustment
    notes: Optional[str] = None
    status: str = "pending"  # pending, applied, rejected


class RentAdjustment(RentAdjustmentCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RentAdjustmentPatch(BaseModel):
    contract_id: Optional[str] = None
    adjustment_type: Optional[str] = None
    effective_date: Optional[date] = None
    previous_rent: Optional[float] = None
    new_rent: Optional[float] = None
    increase_percent: Optional[float] = None
    index_base_year: Optional[int] = None
    index_value: Optional[float] = None
    notes: Optional[str] = None
    status: Optional[str] = None


# ---------------------------------------------------------------------------
# T16: Handover Protocol (Übergabeprotokoll)
# ---------------------------------------------------------------------------


class MeterReadingCreate(BaseModel):
    handover_id: str
    meter_type: str  # electricity, gas, water, heating
    meter_number: Optional[str] = None
    reading_value: float
    unit: str = "kWh"  # kWh, m³, etc.
    photo_url: Optional[str] = None
    notes: Optional[str] = None


class MeterReading(MeterReadingCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MeterReadingPatch(BaseModel):
    handover_id: Optional[str] = None
    meter_type: Optional[str] = None
    meter_number: Optional[str] = None
    reading_value: Optional[float] = None
    unit: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None


class HandoverProtocolCreate(BaseModel):
    contract_id: str
    unit_id: str
    protocol_type: str  # "move_in" or "move_out"
    protocol_date: date
    tenant_present: bool = True
    landlord_present: bool = True
    key_count: Optional[int] = None
    key_details: Optional[str] = None
    overall_condition: Optional[str] = None  # good, fair, poor
    damages: Optional[str] = None  # JSON list of damage descriptions
    photos: Optional[str] = None  # JSON list of photo URLs
    notes: Optional[str] = None
    tenant_signature: Optional[str] = None
    landlord_signature: Optional[str] = None
    status: str = "draft"  # draft, signed, finalized


class HandoverProtocol(HandoverProtocolCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class HandoverProtocolPatch(BaseModel):
    contract_id: Optional[str] = None
    unit_id: Optional[str] = None
    protocol_type: Optional[str] = None
    protocol_date: Optional[date] = None
    tenant_present: Optional[bool] = None
    landlord_present: Optional[bool] = None
    key_count: Optional[int] = None
    key_details: Optional[str] = None
    overall_condition: Optional[str] = None
    damages: Optional[str] = None
    photos: Optional[str] = None
    notes: Optional[str] = None
    tenant_signature: Optional[str] = None
    landlord_signature: Optional[str] = None
    status: Optional[str] = None


# ---------------------------------------------------------------------------
# T18: Change History (Historisierung)
# ---------------------------------------------------------------------------


class ChangeHistoryEntry(BaseModel):
    id: str = Field(..., min_length=1)
    entity_type: str  # property, unit, contract, tenant, etc.
    entity_id: str
    field_name: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    changed_by: Optional[str] = None  # user_id
    changed_at: datetime = Field(default_factory=datetime.utcnow)
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# T27: Budget Planning (Budgetplanung)
# ---------------------------------------------------------------------------


class BudgetCreate(BaseModel):
    property_id: str
    year: int
    category: str  # maintenance, operating_costs, renovation, reserve, other
    planned_amount: float
    actual_amount: float = 0.0
    notes: Optional[str] = None


class Budget(BudgetCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def deviation(self) -> float:
        return self.actual_amount - self.planned_amount

    @property
    def utilization_percent(self) -> float:
        if self.planned_amount == 0:
            return 0.0
        return (self.actual_amount / self.planned_amount) * 100


class BudgetPatch(BaseModel):
    property_id: Optional[str] = None
    year: Optional[int] = None
    category: Optional[str] = None
    planned_amount: Optional[float] = None
    actual_amount: Optional[float] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# T17: Escalation Rules
# ---------------------------------------------------------------------------


class EscalationRuleCreate(BaseModel):
    name: str
    entity_type: str  # task, maintenance, receivable
    condition_field: str  # due_date, appointment_at, etc.
    days_overdue: int  # trigger after N days overdue
    action: str  # notify, reassign, escalate_priority
    target_role: Optional[str] = None  # role to notify / reassign to
    notification_severity: str = "warning"
    is_active: bool = True


class EscalationRule(EscalationRuleCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class EscalationRulePatch(BaseModel):
    name: Optional[str] = None
    entity_type: Optional[str] = None
    condition_field: Optional[str] = None
    days_overdue: Optional[int] = None
    action: Optional[str] = None
    target_role: Optional[str] = None
    notification_severity: Optional[str] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Contact (unified contacts: tenant, owner, supplier, manager)
# ---------------------------------------------------------------------------


class ContactCreate(BaseModel):
    contact_type: str = "tenant"  # tenant, owner, supplier, manager
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    street: Optional[str] = None
    zip_code: Optional[str] = None
    city: Optional[str] = None
    country: str = "DE"
    iban: Optional[str] = None
    bic: Optional[str] = None
    bank_name: Optional[str] = None
    tax_id: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_contact_email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v != "" and "@" not in v:
            raise ValueError("Ungültige E-Mail-Adresse")
        return v


class Contact(ContactCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ContactPatch(BaseModel):
    contact_type: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    street: Optional[str] = None
    zip_code: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    iban: Optional[str] = None
    bic: Optional[str] = None
    bank_name: Optional[str] = None
    tax_id: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Meter (standalone meter management)
# ---------------------------------------------------------------------------


class MeterCreate(BaseModel):
    unit_id: str
    meter_type: str  # cold_water, hot_water, heating, electricity, gas
    serial_number: Optional[str] = None
    location: Optional[str] = None
    installation_date: Optional[date] = None
    next_inspection: Optional[date] = None
    supplier: Optional[str] = None
    is_active: bool = True


class Meter(MeterCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MeterPatch(BaseModel):
    unit_id: Optional[str] = None
    meter_type: Optional[str] = None
    serial_number: Optional[str] = None
    location: Optional[str] = None
    installation_date: Optional[date] = None
    next_inspection: Optional[date] = None
    supplier: Optional[str] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Standalone MeterReading (for Zähler page, not handover-bound)
# ---------------------------------------------------------------------------


class StandaloneMeterReadingCreate(BaseModel):
    meter_id: str
    reading_date: date
    value: float
    recorded_by: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None


class StandaloneMeterReading(StandaloneMeterReadingCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# T18: Insurances
# ---------------------------------------------------------------------------


class InsuranceCreate(BaseModel):
    property_id: str
    unit_id: Optional[str] = None
    insurance_type: str  # building, liability, contents, legal
    provider: str
    policy_number: Optional[str] = None
    coverage_amount: Optional[float] = None
    premium_amount: Optional[float] = None
    premium_interval: str = "annual"  # monthly, quarterly, annual
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = None
    status: str = "active"


class Insurance(InsuranceCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StandaloneMeterReadingPatch(BaseModel):
    meter_id: Optional[str] = None
    reading_date: Optional[date] = None
    value: Optional[float] = None
    recorded_by: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Message Thread & Message (internal communication)
# ---------------------------------------------------------------------------


class MessageThreadCreate(BaseModel):
    subject: str
    participant_ids: Optional[str] = None  # comma-separated contact IDs
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    contract_id: Optional[str] = None


class MessageThread(MessageThreadCreate):
    id: str = Field(..., min_length=1)
    last_message_at: Optional[datetime] = None
    message_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MessageThreadPatch(BaseModel):
    subject: Optional[str] = None
    participant_ids: Optional[str] = None
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    contract_id: Optional[str] = None


class MessageCreate(BaseModel):
    thread_id: str
    sender_name: str = "System"
    body: str
    attachment_ids: Optional[str] = None  # comma-separated document IDs


class Message(MessageCreate):
    id: str = Field(..., min_length=1)
    sent_at: datetime = Field(default_factory=datetime.utcnow)


class MessagePatch(BaseModel):
    body: Optional[str] = None


# ---------------------------------------------------------------------------
# RentCharge (Sollstellung - monthly rent charges)
# ---------------------------------------------------------------------------


class RentChargeCreate(BaseModel):
    contract_id: str
    month: str  # YYYY-MM
    cold_rent: float = 0.0
    service_charge: float = 0.0
    heating_charge: float = 0.0
    other_charges: float = 0.0
    amount_paid: float = 0.0
    status: str = "open"  # open, partial, paid, overdue


class RentCharge(RentChargeCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RentChargePatch(BaseModel):
    contract_id: Optional[str] = None
    month: Optional[str] = None
    cold_rent: Optional[float] = None
    service_charge: Optional[float] = None
    heating_charge: Optional[float] = None
    other_charges: Optional[float] = None
    amount_paid: Optional[float] = None
    status: Optional[str] = None


class InsurancePatch(BaseModel):
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    insurance_type: Optional[str] = None
    provider: Optional[str] = None
    policy_number: Optional[str] = None
    coverage_amount: Optional[float] = None
    premium_amount: Optional[float] = None
    premium_interval: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None


# ---------------------------------------------------------------------------
# T19: Entity Photos
# ---------------------------------------------------------------------------


class EntityPhotoCreate(BaseModel):
    entity_type: str  # property, unit
    entity_id: str
    file_url: str
    caption: Optional[str] = None
    is_primary: bool = False
    sort_order: int = 0


class EntityPhoto(EntityPhotoCreate):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class EntityPhotoPatch(BaseModel):
    caption: Optional[str] = None
    is_primary: Optional[bool] = None
    sort_order: Optional[int] = None
