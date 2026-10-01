"""Pure outbox transitions, adapted from the existing assistant's reviewed draft.

Persistence must CAS every revision and append an event before any DATA release.
Unknown acceptance is resolved only by an explicit documented human decision.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

State = Literal["ready", "claimed", "sent", "failed", "unknown"]
Phase = Literal["idle", "pre_data", "data"]
Decision = Literal[
    "send",
    "wait",
    "recover_ready",
    "human_required",
    "stop",
]
HumanAction = Literal["retry", "mark_sent", "mark_failed", "cancel"]
OutcomeKind = Literal["accepted", "safe_failure", "unknown"]


class OutboxError(ValueError):
    """Fixed machine-readable code only."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise OutboxError(code)


def _aware(value: datetime) -> datetime:
    _need(
        isinstance(value, datetime) and value.tzinfo is not None
        and value.utcoffset() is not None,
        "aware_datetime_required",
    )
    return value


def _opaque(value: str, code: str) -> str:
    _need(isinstance(value, str) and bool(value), code)
    _need(not any(ord(ch) < 32 or ord(ch) == 127 for ch in value), code)
    return value


def message_id_for(
    *,
    secret: bytes,
    idempotency_scope: str,
    idempotency_key: str,
    domain: str = "outbox.invalid",
) -> str:
    """Stable opaque RFC-style Message-ID for one idempotent logical message."""
    _need(type(secret) is bytes and len(secret) >= 32, "message_id_secret")
    scope = _opaque(idempotency_scope, "idempotency_scope")
    key = _opaque(idempotency_key, "idempotency_key")
    _need(
        isinstance(domain, str)
        and re.fullmatch(r"[A-Za-z0-9.-]+", domain) is not None
        and "." in domain,
        "message_id_domain",
    )
    digest = hmac.new(
        secret,
        b"immomanager/outbox/message-id/v1\0"
        + scope.encode("utf-8")
        + b"\0"
        + key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"<immo-{digest}@{domain.lower()}>"


@dataclass(frozen=True)
class TransportOutcome:
    """Result supplied by the already bounded SMTP transport."""

    kind: OutcomeKind
    code: str
    retryable: bool = False

    def __post_init__(self) -> None:
        _need(self.kind in {"accepted", "safe_failure", "unknown"}, "outcome_kind")
        _opaque(self.code, "outcome_code")
        _need(type(self.retryable) is bool, "outcome_retryable")
        if self.kind in {"accepted", "unknown"}:
            _need(self.retryable is False, "ambiguous_outcome_cannot_autoretry")


@dataclass(frozen=True)
class OutboxMessage:
    idempotency_scope: str
    idempotency_key: str
    message_id: str

    state: State
    phase: Phase

    revision: int
    attempt_no: int

    created_at: datetime
    updated_at: datetime

    claim_owner: str | None = None
    claim_token: str | None = None
    lease_until: datetime | None = None

    last_code: str | None = None

    human_action: HumanAction | None = None
    human_actor: str | None = None
    human_note: str | None = None
    human_decided_at: datetime | None = None


def new_message(
    *,
    idempotency_scope: str,
    idempotency_key: str,
    message_id_secret: bytes,
    now: datetime,
    domain: str = "outbox.invalid",
) -> OutboxMessage:
    now = _aware(now)
    scope = _opaque(idempotency_scope, "idempotency_scope")
    key = _opaque(idempotency_key, "idempotency_key")
    return OutboxMessage(
        idempotency_scope=scope,
        idempotency_key=key,
        message_id=message_id_for(
            secret=message_id_secret,
            idempotency_scope=scope,
            idempotency_key=key,
            domain=domain,
        ),
        state="ready",
        phase="idle",
        revision=0,
        attempt_no=0,
        created_at=now,
        updated_at=now,
    )


def _clear_claim(message: OutboxMessage, **updates) -> OutboxMessage:
    return replace(
        message,
        claim_owner=None,
        claim_token=None,
        lease_until=None,
        phase="idle",
        **updates,
    )


def _owned(
    message: OutboxMessage,
    *,
    owner: str,
    claim_token: str,
) -> None:
    _need(message.state == "claimed", "not_claimed")
    _need(
        message.claim_owner == owner and message.claim_token == claim_token,
        "claim_not_owned",
    )


def claim(
    message: OutboxMessage,
    *,
    owner: str,
    claim_token: str,
    now: datetime,
    lease_seconds: int,
) -> OutboxMessage:
    now = _aware(now)
    owner = _opaque(owner, "claim_owner")
    claim_token = _opaque(claim_token, "claim_token")
    _need(message.state == "ready", "not_ready")
    _need(type(lease_seconds) is int and lease_seconds > 0, "lease_seconds")
    try:
        lease_until = now + timedelta(seconds=lease_seconds)
    except OverflowError:
        raise OutboxError("lease_seconds") from None

    return replace(
        message,
        state="claimed",
        phase="pre_data",
        revision=message.revision + 1,
        attempt_no=message.attempt_no + 1,
        updated_at=now,
        claim_owner=owner,
        claim_token=claim_token,
        lease_until=lease_until,
        last_code=None,
        human_action=None,
        human_actor=None,
        human_note=None,
        human_decided_at=None,
    )


def renew_claim(
    message: OutboxMessage,
    *,
    owner: str,
    claim_token: str,
    now: datetime,
    lease_seconds: int,
) -> OutboxMessage:
    now = _aware(now)
    _owned(message, owner=owner, claim_token=claim_token)
    _need(message.lease_until is not None and now < message.lease_until, "claim_expired")
    _need(type(lease_seconds) is int and lease_seconds > 0, "lease_seconds")
    try:
        lease_until = now + timedelta(seconds=lease_seconds)
    except OverflowError:
        raise OutboxError("lease_seconds") from None

    return replace(
        message,
        revision=message.revision + 1,
        updated_at=now,
        lease_until=lease_until,
    )


def mark_data_started(
    message: OutboxMessage,
    *,
    owner: str,
    claim_token: str,
    now: datetime,
) -> OutboxMessage:
    """Persist this BEFORE SMTP DATA/body transmission begins."""
    now = _aware(now)
    _owned(message, owner=owner, claim_token=claim_token)
    _need(message.lease_until is not None and now < message.lease_until, "claim_expired")
    _need(message.phase == "pre_data", "data_already_started")
    return replace(
        message,
        phase="data",
        revision=message.revision + 1,
        updated_at=now,
    )


def finish_attempt(
    message: OutboxMessage,
    *,
    owner: str,
    claim_token: str,
    outcome: TransportOutcome,
    now: datetime,
) -> OutboxMessage:
    """Finalize only against the same persisted claim token/revision."""
    now = _aware(now)
    _owned(message, owner=owner, claim_token=claim_token)
    _need(isinstance(outcome, TransportOutcome), "transport_outcome")
    if outcome.kind in {"accepted", "unknown"}:
        _need(message.phase == "data", "outcome_without_data")

    if outcome.kind == "accepted":
        return _clear_claim(
            message,
            state="sent",
            revision=message.revision + 1,
            updated_at=now,
            last_code=outcome.code,
        )

    if outcome.kind == "unknown":
        return _clear_claim(
            message,
            state="unknown",
            revision=message.revision + 1,
            updated_at=now,
            last_code=outcome.code,
        )

    # Definitive/safe non-acceptance. Retry is allowed only when transport
    # explicitly classified it retryable before/without ambiguous acceptance.
    return _clear_claim(
        message,
        state="ready" if outcome.retryable else "failed",
        revision=message.revision + 1,
        updated_at=now,
        last_code=outcome.code,
    )


def recover_expired_claim(
    message: OutboxMessage,
    *,
    now: datetime,
) -> OutboxMessage:
    """Lease recovery.

    pre_data => safely ready again.
    data => unknown; never automatically retransmit.
    """
    now = _aware(now)
    _need(message.state == "claimed", "not_claimed")
    _need(
        message.lease_until is not None and now >= message.lease_until,
        "claim_not_expired",
    )

    if message.phase == "data":
        return _clear_claim(
            message,
            state="unknown",
            revision=message.revision + 1,
            updated_at=now,
            last_code="lease_expired_after_data_started",
        )

    return _clear_claim(
        message,
        state="ready",
        revision=message.revision + 1,
        updated_at=now,
        last_code="lease_expired_before_data",
    )


def retry_decision(
    message: OutboxMessage,
    *,
    now: datetime,
) -> Decision:
    now = _aware(now)

    if message.state == "ready":
        return "send"

    if message.state == "unknown":
        return "human_required"

    if message.state in {"sent", "failed"}:
        return "stop"

    _need(
        message.state == "claimed" and message.lease_until is not None,
        "invalid_claim_state",
    )
    assert message.lease_until is not None
    if now < message.lease_until:
        return "wait"
    if message.phase == "data":
        return "human_required"
    return "recover_ready"


def resolve_unknown(
    message: OutboxMessage,
    *,
    action: HumanAction,
    actor: str,
    note: str,
    now: datetime,
) -> OutboxMessage:
    """Only explicit human resolution can leave UNKNOWN."""
    now = _aware(now)
    _need(message.state == "unknown", "not_unknown")
    _need(action in {"retry", "mark_sent", "mark_failed"}, "human_action")
    actor = _opaque(actor, "human_actor")
    _need(isinstance(note, str) and bool(note.strip()) and "\x00" not in note, "human_note")

    targets: dict[str, State] = {
        "retry": "ready",
        "mark_sent": "sent",
        "mark_failed": "failed",
    }
    target = targets[action]

    return replace(
        message,
        state=target,
        phase="idle",
        revision=message.revision + 1,
        updated_at=now,
        last_code=f"human:{action}",
        human_action=action,
        human_actor=actor,
        human_note=note,
        human_decided_at=now,
        claim_owner=None,
        claim_token=None,
        lease_until=None,
    )
