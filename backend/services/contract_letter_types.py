"""Reviewed letter data; tables, checks and amounts never come from the client."""
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _single_line(value: str) -> str:
    value = value.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Bitte einen einzeiligen Text ohne Steuerzeichen eingeben.")
    return value


def _multiline(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if any((ord(char) < 32 and char != "\n") or ord(char) == 127 for char in value):
        raise ValueError("Bitte Text ohne Steuerzeichen eingeben.")
    return value


class LetterText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_name: str = Field(min_length=1, max_length=200)
    recipient_address: str = Field(min_length=1, max_length=1500)
    issue_date: date
    subject: str = Field(min_length=1, max_length=300)
    salutation: str = Field(default="", max_length=300)
    body: str = Field(default="", max_length=20000)
    closing: str = Field(default="Mit freundlichen Grüßen", max_length=500)
    signature: str = Field(default="", max_length=300)
    appendix: str = Field(default="", max_length=6000)

    @field_validator("recipient_name", "subject", "salutation", "signature")
    @classmethod
    def single_line(cls, value):
        return _single_line(value)

    @field_validator("recipient_address", "body", "closing", "appendix")
    @classmethod
    def multiline(cls, value):
        return _multiline(value)

    @field_validator("recipient_name", "recipient_address", "subject")
    @classmethod
    def required_text(cls, value):
        if not value:
            raise ValueError("Dieses Feld darf nicht leer sein.")
        return value


class ComposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_id: str = Field(min_length=1, max_length=80)
    inputs: dict[str, Any] | None = None
    issue_date: date | None = None


class LetterPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    template_id: str = Field(min_length=1, max_length=80)
    inputs: dict[str, Any] = Field(default_factory=dict)
    data: LetterText


class LetterPublish(LetterPreview):
    review_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9:_.-]+$")
