"""Reviewed correspondence data; calculated statement amounts never come from the client."""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LetterData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender_name: str = Field(min_length=1, max_length=200)
    sender_address: str = Field(min_length=1, max_length=1500)
    recipient_name: str = Field(min_length=1, max_length=200)
    recipient_address: str = Field(min_length=1, max_length=1500)
    issue_date: date
    subject: str = Field(min_length=1, max_length=500)
    salutation: str = Field(min_length=1, max_length=500)
    intro: str = Field(default="", max_length=6000)
    closing: str = Field(default="Mit freundlichen Grüßen", max_length=2000)
    signature: str = Field(default="", max_length=300)

    @field_validator("sender_name", "recipient_name", "subject", "salutation", "signature")
    @classmethod
    def single_line(cls, value):
        value = value.strip()
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Bitte einen einzeiligen Text ohne Steuerzeichen eingeben.")
        return value

    @field_validator("sender_address", "recipient_address", "intro", "closing")
    @classmethod
    def multiline(cls, value):
        value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if any((ord(char) < 32 and char != "\n") or ord(char) == 127 for char in value):
            raise ValueError("Bitte Text ohne Steuerzeichen eingeben.")
        return value

    @field_validator("sender_name", "recipient_name", "subject", "salutation", "sender_address", "recipient_address")
    @classmethod
    def required_text(cls, value):
        if not value:
            raise ValueError("Dieses Feld darf nicht leer sein.")
        return value


class LetterPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    data: LetterData


class LetterPublish(LetterPreview):
    review_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9:_.-]+$")
