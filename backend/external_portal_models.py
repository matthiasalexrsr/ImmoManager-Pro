from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Bounded mailbox syntax, without DNS lookups or an optional runtime dependency.
PortalEmail = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254,
    pattern=r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotency_key: str = Field(min_length=16, max_length=100)


class InviteParty(Command):
    kind: Literal["tenant", "owner"]
    party_id: str = Field(min_length=1, max_length=100)
    relation_id: str = Field(min_length=1, max_length=100)
    email: PortalEmail
    verification: str = Field(min_length=10, max_length=2000)
    expires_hours: int = Field(default=48, ge=1, le=168)


class ChangeAccess(Command):
    expected_revision: int = Field(ge=1)
    active: bool
    reason: str = Field(min_length=10, max_length=2000)


class RecoverAccess(Command):
    expected_revision: int = Field(ge=1)
    grant_revision: int = Field(ge=1)
    verification: str = Field(min_length=20, max_length=2000)


class PublishDocument(Command):
    grant_revision: int = Field(ge=1)
    version_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    reason: str = Field(min_length=10, max_length=2000)


class PortalLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: PortalEmail
    password: str = Field(min_length=1, max_length=128)


class AcceptInvitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=100)
    password: str = Field(min_length=12, max_length=128)


class ReportDamage(Command):
    grant_id: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=1)
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=10000)


class SendMessage(Command):
    expected_revision: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=10000)


class ShareCase(Command):
    grant_revision: int = Field(ge=1)
    case_id: str = Field(min_length=1, max_length=100)
    case_updated_at: datetime
    title: str = Field(min_length=3, max_length=200)
    reason: str = Field(min_length=10, max_length=2000)
