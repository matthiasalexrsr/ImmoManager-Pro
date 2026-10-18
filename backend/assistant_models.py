"""Strict commands for personal conversations; owner is never client supplied."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .finance_models import ReportDefinition


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=120)


class RevisionCommand(Command):
    expected_revision: int = Field(ge=1)


class ConversationCreate(Command):
    title: str = Field(default="Neues Gespräch", min_length=1, max_length=200)
    provider: str = Field(default="local", pattern=r"^(local|codex|claude)$")
    model: str | None = Field(default=None, max_length=120)
    effort: str = Field(default="high", pattern=r"^(low|medium|high|xhigh)$")
    data_scope: Literal["selected", "authorized", "none"] = "selected"


class ConversationEdit(RevisionCommand):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    archived: bool | None = None
    provider: str | None = Field(default=None, pattern=r"^(local|codex|claude)$")
    model: str | None = Field(default=None, max_length=120)
    effort: str | None = Field(default=None, pattern=r"^(low|medium|high|xhigh)$")
    data_scope: Literal["selected", "authorized", "none"] | None = None


class RunCreate(RevisionCommand):
    content: str = Field(min_length=1, max_length=32000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=12)
    excluded_attachment_ids: list[str] = Field(default_factory=list, max_length=100)
    data_scope: Literal["selected", "authorized", "none"] = "selected"
    context: dict[str, Any] = Field(default_factory=dict)
    web_research: bool = False
    report: ReportDefinition | None = None

    @field_validator("content")
    @classmethod
    def content_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Bitte eine Nachricht eingeben.")
        return value


class ProposalPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    values: dict[str, Any] | None = None


class ProposalApply(RevisionCommand):
    review_hash: str = Field(min_length=64, max_length=64)
    values: dict[str, Any] | None = None


class ProposalReject(RevisionCommand):
    reason: str = Field(min_length=1, max_length=2000)
