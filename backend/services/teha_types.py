"""Explicit TEHA local commands; optimistic revisions and repetition keys."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .integrations.connection_types import ConnectionCommand


class Stage(ConnectionCommand):
    run_revision: int = Field(ge=1)
    batch_revision: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=250)


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["property", "billing_period", "unit", "tenant", "contract", "task", "maintenance"]
    id: str = Field(min_length=1, max_length=120)
    revision: str = Field(min_length=1, max_length=200)


class MapItem(ConnectionCommand):
    mapping_revision: int = Field(ge=0)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    targets: list[Target] = Field(min_length=1, max_length=6)
    confirm: Literal[True]


class Publish(ConnectionCommand):
    preview_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm: Literal[True]


class BatchDecision(ConnectionCommand):
    base_revision: int = Field(ge=1)
    state: Literal["cancelled", "revoked"]
    reason: str = Field(min_length=1, max_length=1000)


class FollowUpUserSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str = Field(min_length=1, max_length=120)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class FollowUpPreparation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    orderer_name: str = Field(min_length=1, max_length=200)
    orderer_email: str = Field(default="", max_length=320)
    users: list[FollowUpUserSource] = Field(min_length=1)


class PrepareReturn(ConnectionCommand):
    kind: Literal["cost_user_data", "maintenance_order"]
    mapping_revision: int = Field(ge=1)
    source: Target
    follow_up: FollowUpPreparation | None = None
    confirm: Literal[True]
