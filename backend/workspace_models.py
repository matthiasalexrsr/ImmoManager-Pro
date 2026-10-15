"""Private workspace wire contracts; no endpoint here executes a domain operation."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=120)


class EntityReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1, max_length=80)
    id: str = Field(min_length=1, max_length=120)


class DraftSource(EntityReference):
    revision: str = Field(min_length=1, max_length=120)


class DraftWrite(WorkspaceMutation):
    context: str = Field(min_length=1, max_length=240)
    mode: Literal["create", "edit"] = "create"
    source: DraftSource | None = None
    anchor: EntityReference | None = None
    field_keys: list[str] = Field(default_factory=list, max_length=250)
    form_key: str = Field(default="", max_length=240)
    values: dict[str, Any] = Field(default_factory=dict)


class DraftRebase(WorkspaceMutation):
    source_revision: str = Field(min_length=1, max_length=120)
    values: dict[str, Any]


class ViewWrite(WorkspaceMutation):
    context: str = Field(min_length=1, max_length=240)
    anchor: EntityReference | None = None
    name: str = Field(min_length=1, max_length=120)
    config: dict[str, Any]


class ViewStateWrite(WorkspaceMutation):
    anchor: EntityReference | None = None
    state: dict[str, Any]


class EntityWrite(WorkspaceMutation):
    pass


class RecentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1, max_length=80)
    entity_id: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=120)


class DeferralWrite(WorkspaceMutation):
    due_on: str = Field(min_length=10, max_length=10)
    reason: str = Field(min_length=1, max_length=1000)
