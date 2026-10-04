"""Personal live-inbox contracts; no authority or runtime imports."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InboxQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["unread", "read", "all"] = "unread"
    notification_type: str | None = Field(default=None, min_length=1, max_length=255)
    severity: str | None = Field(default=None, min_length=1, max_length=255)
    after: str | None = Field(default=None, min_length=1, max_length=8192)
    limit: int = Field(default=10, ge=1, le=100, strict=True)


@dataclass(frozen=True, slots=True)
class InboxPrincipal:
    """Internal fresh SQL identity data. This value is NOT a write capability."""

    actor_id: str
    role: str
    unrestricted: bool
    portfolio_access: str
    portfolio_access_origin: str
    portfolio_ids: tuple[str, ...]

    def binding(self) -> dict:
        return {
            "actor_id": self.actor_id,
            "role": self.role,
            "unrestricted": self.unrestricted,
            "portfolio_access": self.portfolio_access,
            "portfolio_access_origin": self.portfolio_access_origin,
            "portfolio_ids": list(self.portfolio_ids),
        }


class InboxItemActions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mark_read: bool = False


class NotificationInboxItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    notification_type: str
    title: str
    content: str
    severity: str
    entity_type: str | None
    entity_id: str | None
    created_at: datetime | None
    read_at: datetime | None
    actions: InboxItemActions = Field(default_factory=InboxItemActions)


class InboxActions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mark_all_read: Literal[False] = False


class InboxPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: list[NotificationInboxItem]
    full_count: int = Field(ge=0, strict=True)
    unread_count: int = Field(ge=0, strict=True)
    has_more: bool
    next_cursor: str | None
    snapshot_token: None = None
    consistency: Literal["live"] = "live"
    actions: InboxActions = Field(default_factory=InboxActions)


class NotificationReadResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    notification_id: str
    read_at: datetime
