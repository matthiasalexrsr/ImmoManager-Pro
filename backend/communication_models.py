"""Pydantic contracts for the communication center."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

Audience = Literal["tenant", "company", "any"]
Channel = Literal["email", "post", "whatsapp", "universal"]
RecipientType = Literal["tenant", "contact"]
DraftStatus = Literal["draft", "reviewed", "queued", "sent", "failed"]


def _clean(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Text darf kein NUL-Zeichen enthalten")
    return value


class CommunicationTemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="general", min_length=1, max_length=80)
    audience: Audience = "any"
    channel: Channel = "universal"
    locale: str = Field(default="de-DE", max_length=20)
    subject_template: str = Field(default="", max_length=500)
    body_template: str = Field(min_length=1, max_length=100_000)
    tags: str | None = Field(default=None, max_length=1000)
    is_active: bool = True

    _subject_text = field_validator("subject_template")(_clean)
    _body_text = field_validator("body_template")(_clean)


class CommunicationTemplate(CommunicationTemplateCreate):
    id: str
    revision: int = 1
    created_at: datetime
    updated_at: datetime


class CommunicationTemplateUpdate(CommunicationTemplateCreate):
    expected_revision: int = Field(ge=1)


class CommunicationBlockCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{1,79}$")
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="general", max_length=80)
    locale: str = Field(default="de-DE", max_length=20)
    content_template: str = Field(min_length=1, max_length=50_000)
    tags: str | None = Field(default=None, max_length=1000)
    is_active: bool = True

    _content_text = field_validator("content_template")(_clean)


class CommunicationBlock(CommunicationBlockCreate):
    id: str
    revision: int = 1
    created_at: datetime
    updated_at: datetime


class CommunicationBlockUpdate(CommunicationBlockCreate):
    expected_revision: int = Field(ge=1)


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient_type: RecipientType
    recipient_id: str = Field(min_length=1)
    channel: Literal["email", "post", "whatsapp"] | None = None
    contract_id: str | None = None
    template_id: str | None = None
    subject_template: str | None = Field(default=None, max_length=500)
    body_template: str | None = Field(default=None, max_length=100_000)


class RenderPreview(BaseModel):
    subject: str
    body: str
    recipient: dict
    context: dict
    context_sha256: str
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CommunicationDraftCreate(RenderRequest):
    portfolio_id: str = Field(min_length=1)
    channel: Literal["email", "post", "whatsapp"] = "email"
    title: str = Field(min_length=1, max_length=200)
    whatsapp_template_name: str | None = Field(default=None, max_length=200, pattern=r"^[a-z0-9_]+$")
    whatsapp_language_code: str = Field(default="de", max_length=20, pattern=r"^[a-z]{2,3}(?:_[A-Z]{2})?$")


class CommunicationDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    channel: Literal["email", "post", "whatsapp"] | None = None
    recipient_type: RecipientType | None = None
    recipient_id: str | None = None
    contract_id: str | None = None
    template_id: str | None = None
    subject_template: str | None = Field(default=None, max_length=500)
    body_template: str | None = Field(default=None, max_length=100_000)
    whatsapp_template_name: str | None = Field(default=None, max_length=200, pattern=r"^[a-z0-9_]+$")
    whatsapp_language_code: str | None = Field(default=None, max_length=20, pattern=r"^[a-z]{2,3}(?:_[A-Z]{2})?$")


class CommunicationDraft(BaseModel):
    id: str
    portfolio_id: str
    title: str
    channel: str
    recipient_type: str
    recipient_id: str
    contract_id: str | None = None
    template_id: str | None = None
    template_revision: int | None = None
    subject_template: str
    body_template: str
    rendered_subject: str | None = None
    rendered_body: str | None = None
    context_sha256: str | None = None
    snapshot_sha256: str | None = None
    pdf_sha256: str | None = None
    status: DraftStatus
    revision: int
    created_by: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    external_reference: str | None = None
    external_status: str | None = None
    whatsapp_template_name: str | None = None
    whatsapp_language_code: str = "de"
    created_at: datetime
    updated_at: datetime


class ReviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    confirmed: StrictBool

    @model_validator(mode="after")
    def require_confirmation(self):
        if not self.confirmed:
            raise ValueError("Explizite Freigabe erforderlich")
        return self


class DispatchCommand(ReviewCommand):
    action: Literal["email", "whatsapp", "post"]
    test_mode: StrictBool = True


class DispatchResult(BaseModel):
    draft: CommunicationDraft
    provider: str
    result: dict


class CatalogResponse(BaseModel):
    variables: list[dict]
    channels: list[dict]
    blocks: list[CommunicationBlock]
    templates: list[CommunicationTemplate]
