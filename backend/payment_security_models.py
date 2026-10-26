"""Explicit commands for payee changes and payment approval."""
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .services.sepa_rules import iban_problem


class RecipientChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=300)
    iban: str = Field(min_length=15, max_length=42)
    bic: str | None = Field(default=None, pattern=r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")
    reason: str = Field(min_length=10, max_length=2000)

    @field_validator("iban")
    @classmethod
    def valid_iban(cls, value):
        result = "".join(value.split()).upper()
        problem = iban_problem(result)
        if problem:
            raise ValueError(problem)
        return result

    @field_validator("name", "reason")
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError("Die Angabe darf nicht leer sein.")
        return value.strip()


class AuthorizePayment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    reason: str = Field(min_length=10, max_length=2000)
    bank_verification: str = Field(min_length=20, max_length=2000)
    totp_code: str | None = Field(default=None, pattern=r"^\d{6}$")


class SecurityModeChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    single_user_mode: bool
    reason: str = Field(min_length=20, max_length=2000)
    totp_code: str | None = Field(default=None, pattern=r"^\d{6}$")
