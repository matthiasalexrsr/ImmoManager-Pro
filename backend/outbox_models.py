"""Reviewed immutable messages and explicit revision-bound manual commands."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


def valid_reference(value):
    value.encode("utf-8")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("Command references must not contain control characters")
    return value


class OutboxCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=100)
    recipient: str
    sender_address: str
    sender_name: str
    subject: str
    body_text: str
    reviewed_by: str = Field(min_length=1)
    review_confirmed: StrictBool

    _reference = field_validator("idempotency_key")(valid_reference)

    @field_validator("recipient", "sender_address", "sender_name", "subject", "body_text", "reviewed_by")
    @classmethod
    def valid_text(cls, value):
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("Text must be valid UTF-8") from None
        if "\x00" in value:
            raise ValueError("Text must not contain NUL")
        return value

    @model_validator(mode="after")
    def reviewed(self):
        if not self.review_confirmed or not self.reviewed_by.strip() or not self.subject.strip() or not self.body_text.strip():
            raise ValueError("Reviewed recipient/content and a reviewer reference are required")
        return self


class OutboxCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=0, strict=True)
    confirmed: StrictBool

    _reference = field_validator("idempotency_key")(valid_reference)

    @model_validator(mode="after")
    def explicit(self):
        if not self.confirmed:
            raise ValueError("An explicit confirmation is required")
        return self


class OutboxDecision(OutboxCommand):
    action: Literal["retry", "mark_sent", "mark_failed", "cancel"]
    note: str = Field(min_length=1)

    @field_validator("note")
    @classmethod
    def valid_note_text(cls, value):
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("Decision text must be valid UTF-8") from None
        return value

    @model_validator(mode="after")
    def documented(self):
        if not self.note.strip() or "\x00" in self.note:
            raise ValueError("A nonblank decision note is required")
        return self
