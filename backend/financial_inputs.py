"""The common boundary of financial write requests, not intermediate arithmetic.

All these amounts use Numeric(12,2) in the persistent store. Round input once,
before either repository sees it. Ratios, areas and exact tariff unit prices are
not money fields. Stored record subclasses have an id and retain legacy finite
fractions; domain.money still supplies their canonical cent value when read.
"""
from decimal import Decimal, DecimalException
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from .domain.money import input_money

MONEY_FIELDS = frozenset({
    "amount", "amount_due", "net_amount", "vat_amount", "gross_amount",
    "opening_balance", "balance", "cold_rent", "service_charge_advance", "heating_advance",
    "purchase_price", "market_value", "deposit_amount", "carried_balance", "estimated_cost",
    "total_cost", "advance_paid", "deductions", "previous_rent", "new_rent",
    "planned_amount", "actual_amount", "coverage_amount", "premium_amount",
    "service_charge", "heating_charge", "other_charges", "amount_paid", "target_rent", "net_income",
    "interest_amount", "carried_amount", "carried_interest", "approved_amount", "expected_amount",
    "net", "vat", "rounding_amount", "four_eyes_limit", "small_invoice_limit",
})


class FinancialRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    # Some workflows validate exact cent precision in the service and return
    # their established domain error. Do not round away that evidence first.
    preserve_money_precision: ClassVar[frozenset[str]] = frozenset()

    @field_validator("*", mode="before")
    @classmethod
    def valid_money_input(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None or info.field_name not in MONEY_FIELDS:
            return value
        stored_record = "id" in cls.model_fields and "created_at" in cls.model_fields
        if stored_record:
            return value
        if isinstance(value, bool):
            raise ValueError("Ein Geldbetrag muss eine Zahl sein.")
        if isinstance(value, str):
            try:
                Decimal(value)
            except DecimalException:
                # Keep Pydantic's field-specific float_parsing error for an
                # invalid number format; the UI already translates that error.
                return value
        amount = input_money(value)
        if info.field_name in cls.preserve_money_precision:
            return value
        return float(amount) + 0.0
