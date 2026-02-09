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
