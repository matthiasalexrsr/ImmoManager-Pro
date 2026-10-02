"""Read-only contract pages; transfer budgets do not limit inventory size."""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..config import settings
from ..models import Contract

ContractSort = Literal[
    "contract_number",
    "start_date",
    "end_date",
    "status",
    "property_name",
    "unit_label",
    "tenant_name",
    "deposit_amount",
]
ContractStatus = Literal["active", "terminated", "expired", "draft"]


class ContractWorkspaceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search: str | None = None
    property_id: str | None = Field(default=None, min_length=1)
    unit_id: str | None = Field(default=None, min_length=1)
    tenant_id: str | None = Field(default=None, min_length=1)
    status: ContractStatus | None = None
    date_from: date | None = None
    date_to: date | None = None
    view: Literal["all", "ending_soon", "no_deposit"] = "all"
    sort_by: ContractSort = "contract_number"
    sort_order: Literal["asc", "desc"] = "asc"
    page_size: int = Field(default=100, ge=1)
    cursor: str | None = Field(default=None, min_length=1)

    @field_validator("search")
    @classmethod
    def safe_search(cls, value):
        maximum = getattr(settings, "contract_workspace_search_max_chars", 200)
        if type(maximum) is not int or maximum <= 0:
            raise RuntimeError("CONTRACT_WORKSPACE_SEARCH_MAX_CHARS must be a positive integer")
        if value is not None and len(value) > maximum:
            raise ValueError(
                f"Search exceeds the configured query budget ({maximum} characters); use a shorter substring"
            )
        if value is not None and any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Search must not contain control characters")
        return value.strip() or None if value is not None else None

    @field_validator("property_id", "unit_id", "tenant_id")
    @classmethod
    def safe_identifier(cls, value):
        if value is not None and any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Identifiers must not contain control characters")
        return value

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def iso_date(cls, value):
        if isinstance(value, str) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Use an ISO date YYYY-MM-DD")
        return value

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not follow date_to")
        return self


class ContractWorkspaceItem(Contract):
    property_name: str | None = None
    unit_label: str | None = None
    tenant_name: str | None = None
    unit_cold_rent: float | None = None
    edit_etag: str


class ContractWorkspacePage(BaseModel):
    items: list[ContractWorkspaceItem]
    next_cursor: str | None
    has_more: bool
    reference_date: date


class ContractWorkspaceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

    @property
    def detail(self):
        return {"clear_code": self.code, "message": str(self), "recovery": "restart_page"}
