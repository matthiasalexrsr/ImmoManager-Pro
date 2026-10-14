"""Records of the dunning tables (db/dunning_models.py), field for field, and the API requests.

The records are what the memory store keeps and what snapshots carry; money is a cent
amount (float at the boundary, Decimal in every calculation: domain.money).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .domain.money import money


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _Stamped(BaseModel):
    id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class DunningStageSetting(_Stamped):
    stage: int
    label: str
    days_after: int
    fee: float = 0.0
    payment_deadline_days: int = 14
    charge_interest: bool = True


class DunningBaseRate(_Stamped):
    valid_from: date
    rate_percent: float
    source_note: Optional[str] = None


class DunningBlock(_Stamped):
    contract_id: str
    reason: str
    blocked_until: date
    created_by: Optional[str] = None
    lifted_at: Optional[datetime] = None
    lifted_by: Optional[str] = None
    lift_note: Optional[str] = None


class DunningDispute(_Stamped):
    contract_id: str
    claim_key: str
    reason: str
    raised_on: date
    status: str = "open"
    decided_on: Optional[date] = None
    decision_note: Optional[str] = None
    created_by: Optional[str] = None


class DunningRun(_Stamped):
    portfolio_id: str
    contract_id: Optional[str] = None
    as_of: date
    letter_date: date
    preview_hash: str
    request_sha256: str
    command_key: str
    created_by: str
    summary: Optional[dict] = None


class DunningCase(_Stamped):
    contract_id: str
    reference: str
    status: str = "open"
    stage: int = 0
    opened_on: date
    closed_on: Optional[date] = None
    result: Optional[str] = None
    result_date: Optional[date] = None
    result_reference: Optional[str] = None
    result_note: Optional[str] = None
    result_outstanding: Optional[float] = None
    created_by: Optional[str] = None


class DunningCaseItem(_Stamped):
    case_id: str
    claim_key: str
    kind: str
    receivable_id: Optional[str] = None
    due_date: date
    description: str
    amount: float
    first_stage: int
    interest_until: Optional[date] = None


class DunningLetter(_Stamped):
    case_id: str
    contract_id: str
    run_id: Optional[str] = None
    stage: int
    status: str = "draft"
    letter_date: date
    payment_deadline: date
    principal: float
    earlier_charges: float = 0.0
    fee: float = 0.0
    interest: float = 0.0
    total: float
    content: dict
    draft_hash: str
    document_id: Optional[str] = None
    version_id: Optional[str] = None
    finalized_at: Optional[datetime] = None
    finalized_by: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    cancel_reason: Optional[str] = None
    created_by: Optional[str] = None


class DunningOutbox(_Stamped):
    letter_id: str
    contract_id: str
    channel: str = "letter"
    status: str = "queued"
    recipient_name: Optional[str] = None
    recipient_address: Optional[str] = None
    recipient_email: Optional[str] = None
    subject: str
    body: str
    prepared_at: Optional[datetime] = None
    sent_on: Optional[date] = None
    sent_via: Optional[str] = None
    sent_note: Optional[str] = None
    sent_by: Optional[str] = None


class DunningReply(_Stamped):
    case_id: Optional[str] = None
    contract_id: Optional[str] = None
    reference: Optional[str] = None
    received_on: date
    channel: str = "letter"
    sender: Optional[str] = None
    body: str
    status: str = "review"
    review_reason: Optional[str] = None
    assigned_by: Optional[str] = None
    assigned_at: Optional[datetime] = None
    created_by: Optional[str] = None


class DunningEvent(_Stamped):
    case_id: str
    contract_id: str
    kind: str
    at: datetime
    actor_id: Optional[str] = None
    summary: str
    data: Optional[dict] = None


# ─── Requests ────────────────────────────────────────────────────────────────

def _cents_not_negative(value: float) -> float:
    rounded = money(value)
    if rounded < 0:
        raise ValueError("Betrag darf nicht negativ sein")
    return float(rounded)


class StageSettingInput(BaseModel):
    stage: int = Field(ge=1, le=4)
    label: str = Field(min_length=1, max_length=80)
    days_after: int = Field(ge=0, le=365)
    fee: float = Field(ge=0, le=1000)
    payment_deadline_days: int = Field(ge=1, le=90)
    charge_interest: bool = True

    @field_validator("fee")
    @classmethod
    def _fee_in_cents(cls, v: float) -> float:
        return _cents_not_negative(v)


class StageSettingsRequest(BaseModel):
    stages: list[StageSettingInput] = Field(min_length=4, max_length=4)


class BaseRateRequest(BaseModel):
    valid_from: date
    rate_percent: float = Field(ge=-10, le=20)
    source_note: Optional[str] = Field(default=None, max_length=500)


class RunScope(BaseModel):
    contract_id: Optional[str] = None
    portfolio_id: Optional[str] = None
    as_of: Optional[date] = None
    letter_date: Optional[date] = None


class RunRequest(RunScope):
    command_key: str = Field(min_length=8, max_length=120)
    preview_hash: str = Field(min_length=64, max_length=64)


class FinalizeRequest(BaseModel):
    command_key: str = Field(min_length=8, max_length=120)
    draft_hash: str = Field(min_length=64, max_length=64)
    channel: Literal["letter", "email"] = "letter"
    confirmed: bool = False


class CancelLetterRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class BlockRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    blocked_until: date


class LiftBlockRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)


class DisputeRequest(BaseModel):
    claim_key: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=1000)
    raised_on: Optional[date] = None


class DisputeDecision(BaseModel):
    decision: Literal["upheld", "rejected"]
    decided_on: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=1000)


class ResultRequest(BaseModel):
    result: Literal["paid", "partially_paid", "written_off", "handed_over"]
    result_date: date
    reference: str = Field(min_length=1, max_length=200)
    note: Optional[str] = Field(default=None, max_length=2000)


class ReplyRequest(BaseModel):
    reference: Optional[str] = Field(default=None, max_length=200)
    received_on: Optional[date] = None
    channel: Literal["letter", "email", "phone", "note", "other"] = "letter"
    sender: Optional[str] = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=20000)


class AssignRequest(BaseModel):
    """The case by its id, or by the reference a person read on the reply (exactly one of both)."""

    case_id: Optional[str] = Field(default=None, min_length=1)
    reference: Optional[str] = Field(default=None, min_length=1, max_length=40)


class MarkSentRequest(BaseModel):
    sent_on: date
    via: str = Field(min_length=1, max_length=200)
    note: Optional[str] = Field(default=None, max_length=1000)


class NoteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
