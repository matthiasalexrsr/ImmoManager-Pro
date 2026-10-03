"""Read-only property inventory DTOs; current metadata, no write authority."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models import Property

COUNT_FIELDS = (
    "rent_known_unit_count", "rent_missing_unit_count", "rent_invalid_unit_count",
    "unit_count", "occupied_unit_count", "no_current_contract_unit_count",
    "multiple_current_contract_unit_count", "manual_occupied_unit_count",
    "manual_vacant_unit_count", "manual_reserved_unit_count",
    "open_maintenance_count", "unknown_maintenance_status_count",
)


class PropertyInventoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    search: str | None = None
    portfolio_id: str | None = None
    status: str | None = None
    property_type: str | None = None
    view: Literal["all", "manual_vacancy", "open_maintenance", "no_current_contract", "multiple_current_contracts"] = "all"
    as_of: date
    sort_by: Literal["name", "city", "unit_cold_rent_sum"] = "name"
    sort_order: Literal["asc", "desc"] = "asc"
    page_size: int = Field(default=25, ge=1)
    cursor: str | None = Field(default=None, min_length=1)

    @field_validator("search", "portfolio_id", "status", "property_type")
    @classmethod
    def safe_text(cls, value):
        if value is None:
            return None
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Bitte Text ohne Steuerzeichen verwenden.")
        return value.strip() or None


class PropertyInventoryCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rent_known_unit_count: int = Field(ge=0)
    rent_missing_unit_count: int = Field(ge=0)
    rent_invalid_unit_count: int = Field(ge=0)
    unit_count: int = Field(ge=0)
    occupied_unit_count: int = Field(ge=0)
    no_current_contract_unit_count: int = Field(ge=0)
    multiple_current_contract_unit_count: int = Field(ge=0)
    manual_occupied_unit_count: int = Field(ge=0)
    manual_vacant_unit_count: int = Field(ge=0)
    manual_reserved_unit_count: int = Field(ge=0)
    open_maintenance_count: int = Field(ge=0)
    unknown_maintenance_status_count: int = Field(ge=0)


class PropertyInventoryItem(Property, PropertyInventoryCounts):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    portfolio_name: str | None
    address: str | None
    rent_currency: str | None
    unit_cold_rent_sum: str | None = Field(pattern=r"^(?:0|[1-9][0-9]*)\.[0-9]{2}$")
    edit_etag: str


class PropertyInventoryPage(BaseModel):
    items: list[PropertyInventoryItem]
    has_more: bool
    next_cursor: str | None
    as_of: date


class PropertyInventoryTotals(PropertyInventoryCounts):
    property_count: int = Field(ge=0)


class PropertyInventorySummary(BaseModel):
    as_of: date
    scope_totals: PropertyInventoryTotals
    matching_totals: PropertyInventoryTotals
