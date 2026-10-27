"""Commands for structured receipts; every mutation carries a revision/key."""
from pydantic import BaseModel, ConfigDict, Field


class RetryValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class AcceptIntake(RetryValidation):
    unit_id: str | None = None
    credit_for_invoice_id: str | None = None
    acknowledge_warnings: bool = False
    warning_reason: str | None = Field(default=None, max_length=2000)
    accept_duplicate: bool = False
    duplicate_reason: str | None = Field(default=None, max_length=2000)
    cost_category: str | None = Field(default=None, max_length=100)
    recoverable: bool = False
