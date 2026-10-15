"""Shared office records and commands; personal workspace data lives separately."""

from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def now() -> datetime:
    return datetime.now(timezone.utc)


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FollowUp(Request):
    title: str = Field(min_length=1, max_length=500)
    due_date: date | None = None
    assignee: str | None = Field(default=None, max_length=200)
    priority: Literal["low", "medium", "high", "urgent"] = "medium"


class NoteCreate(Request):
    entity_type: str = Field(min_length=1, max_length=40)
    entity_id: str = Field(min_length=1, max_length=120)
    base_revision: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10_000)
    conversation_kind: Literal["note", "phone", "email", "meeting"] = "note"
    occurred_at: datetime = Field(default_factory=now)
    follow_up: FollowUp | None = None
    idempotency_key: UUID

    @field_validator("body")
    @classmethod
    def meaningful_body(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Bitte eine Gesprächsnotiz eingeben.")
        return value.strip()


class ConversationNote(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    property_id: str | None = None
    body: str
    conversation_kind: str
    occurred_at: datetime
    actor_id: str
    task_id: str | None = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class BusinessCommand(BaseModel):
    id: str
    actor_id: str
    operation: str
    entity_type: str
    entity_id: str
    property_id: str | None = None
    fingerprint: str
    response: dict[str, Any]
    inverse: dict[str, Any] | None = None
    post_revision: str | None = None
    undone_by: str | None = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class TaskChanges(Request):
    status: Literal["open", "in_progress", "completed", "done", "cancelled"] | None = None
    assignee: str | None = Field(default=None, max_length=200)
    priority: Literal["low", "medium", "high", "urgent"] | None = None
    due_date: date | None = None


class QuickEdit(Request):
    entity_type: Literal["task"] = "task"
    entity_id: str = Field(min_length=1, max_length=120)
    base_revision: str = Field(min_length=1, max_length=200)
    changes: TaskChanges
    idempotency_key: UUID


class Undo(Request):
    base_revision: str = Field(min_length=1, max_length=200)
    idempotency_key: UUID


class DocumentIntake(BaseModel):
    id: str
    document_id: str
    property_id: str | None = None
    source_file_url: str
    source_revision: str
    status: Literal["processing", "review", "done", "failed"]
    command_id: str | None = None
    lease_until: datetime | None = None
    sha256: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    actor_id: str
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class ProcessDocument(Request):
    base_revision: str = Field(min_length=1, max_length=200)
    idempotency_key: UUID
    use_ai: bool = False


class ReviewDocument(Request):
    base_revision: str = Field(min_length=1, max_length=200)
    document_revision: str = Field(min_length=1, max_length=200)
    changes: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: UUID


class DuplicateCheck(Request):
    kind: Literal["contact", "invoice", "file"]
    candidate: dict[str, Any]
    exclude_id: str | None = None
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class DuplicateAccept(Request):
    kind: Literal["contact", "invoice", "file"]
    entity_id: str = Field(min_length=1, max_length=120)
    duplicate_id: str = Field(min_length=1, max_length=120)
    base_revision: str = Field(min_length=1, max_length=200)
    duplicate_revision: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3, max_length=2000)
    idempotency_key: UUID

    @field_validator("reason")
    @classmethod
    def justified(cls, value: str) -> str:
        if len(value.strip()) < 3:
            raise ValueError("Bitte die begründete Ausnahme beschreiben.")
        return value.strip()


class DuplicateException(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    duplicate_id: str
    property_id: str | None = None
    source_revision: str
    duplicate_revision: str
    reason: str
    actor_id: str
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
