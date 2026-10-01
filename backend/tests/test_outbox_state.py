# test_outbox_state_draft.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock, Thread

import pytest

from backend.services.outbox_state import (
    OutboxError,
    OutboxMessage,
    TransportOutcome,
    claim,
    finish_attempt,
    mark_data_started,
    message_id_for,
    new_message,
    recover_expired_claim,
    renew_claim,
    resolve_unknown,
    retry_decision,
)

SECRET = b"x" * 32
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def fresh() -> OutboxMessage:
    return new_message(
        idempotency_scope="installation-1",
        idempotency_key="logical-mail-1",
        message_id_secret=SECRET,
        now=T0,
    )


def claimed(*, owner="worker-a", token="claim-a", lease=30) -> OutboxMessage:
    return claim(
        fresh(),
        owner=owner,
        claim_token=token,
        now=T0,
        lease_seconds=lease,
    )


def data_started(*, lease=30) -> OutboxMessage:
    return mark_data_started(
        claimed(lease=lease),
        owner="worker-a",
        claim_token="claim-a",
        now=T0 + timedelta(seconds=1),
    )


def unknown_message() -> OutboxMessage:
    return finish_attempt(
        data_started(),
        owner="worker-a",
        claim_token="claim-a",
        outcome=TransportOutcome("unknown", "data_timeout"),
        now=T0 + timedelta(seconds=2),
    )


class CasBox:
    """Tiny test-only persistence model: UPDATE ... WHERE revision=:expected."""

    def __init__(self, value: OutboxMessage):
        self.value = value
        self._lock = Lock()

    def read(self) -> OutboxMessage:
        with self._lock:
            return self.value

    def commit(self, expected_revision: int, new_value: OutboxMessage) -> bool:
        with self._lock:
            if self.value.revision != expected_revision:
                return False
            assert new_value.revision > expected_revision
            self.value = new_value
            return True


# 1
def test_message_id_is_deterministic_for_same_logical_message():
    first = message_id_for(
        secret=SECRET,
        idempotency_scope="scope",
        idempotency_key="key",
    )
    second = message_id_for(
        secret=SECRET,
        idempotency_scope="scope",
        idempotency_key="key",
    )
    assert first == second
    assert first.startswith("<immo-")
    assert first.endswith("@outbox.invalid>")


# 2
def test_message_id_changes_for_scope_key_and_secret():
    baseline = message_id_for(
        secret=SECRET,
        idempotency_scope="scope",
        idempotency_key="key",
    )
    assert baseline != message_id_for(
        secret=SECRET,
        idempotency_scope="other",
        idempotency_key="key",
    )
    assert baseline != message_id_for(
        secret=SECRET,
        idempotency_scope="scope",
        idempotency_key="other",
    )
    assert baseline != message_id_for(
        secret=b"y" * 32,
        idempotency_scope="scope",
        idempotency_key="key",
    )


# 3
def test_new_message_is_ready_and_sendable():
    item = fresh()
    assert item.state == "ready"
    assert item.phase == "idle"
    assert item.revision == 0
    assert item.attempt_no == 0
    assert item.claim_owner is None
    assert retry_decision(item, now=T0) == "send"


# 4
def test_claim_increments_attempt_and_revision_and_sets_lease():
    item = claimed(lease=45)
    assert item.state == "claimed"
    assert item.phase == "pre_data"
    assert item.attempt_no == 1
    assert item.revision == 1
    assert item.claim_owner == "worker-a"
    assert item.claim_token == "claim-a"
    assert item.lease_until == T0 + timedelta(seconds=45)


# 5
def test_direct_second_claim_of_claimed_state_is_rejected():
    item = claimed()
    with pytest.raises(OutboxError, match="not_ready"):
        claim(
            item,
            owner="worker-b",
            claim_token="claim-b",
            now=T0 + timedelta(seconds=1),
            lease_seconds=30,
        )


# 6
def test_two_competing_claims_only_one_can_commit_via_revision_cas():
    box = CasBox(fresh())
    snapshot = box.read()
    barrier = Barrier(2)
    results = []

    def worker(owner, token):
        proposal = claim(
            snapshot,
            owner=owner,
            claim_token=token,
            now=T0,
            lease_seconds=30,
        )
        barrier.wait(timeout=3)
        results.append(box.commit(snapshot.revision, proposal))

    first = Thread(target=worker, args=("worker-a", "claim-a"))
    second = Thread(target=worker, args=("worker-b", "claim-b"))
    first.start()
    second.start()
    first.join(timeout=3)
    second.join(timeout=3)

    assert not first.is_alive()
    assert not second.is_alive()
    assert sorted(results) == [False, True]
    assert box.read().state == "claimed"
    assert box.read().revision == 1
    assert box.read().claim_owner in {"worker-a", "worker-b"}


# 7
def test_stale_revision_cannot_overwrite_newer_claim():
    box = CasBox(fresh())
    stale = box.read()
    first = claim(
        stale,
        owner="worker-a",
        claim_token="claim-a",
        now=T0,
        lease_seconds=30,
    )
    assert box.commit(stale.revision, first)

    stale_second = claim(
        stale,
        owner="worker-b",
        claim_token="claim-b",
        now=T0,
        lease_seconds=30,
    )
    assert box.commit(stale.revision, stale_second) is False
    assert box.read().claim_owner == "worker-a"


# 8
def test_claim_renewal_requires_owner_token_and_unexpired_lease():
    item = claimed()
    with pytest.raises(OutboxError, match="claim_not_owned"):
        renew_claim(
            item,
            owner="worker-b",
            claim_token="claim-a",
            now=T0 + timedelta(seconds=1),
            lease_seconds=30,
        )

    renewed = renew_claim(
        item,
        owner="worker-a",
        claim_token="claim-a",
        now=T0 + timedelta(seconds=1),
        lease_seconds=60,
    )
    assert renewed.revision == item.revision + 1
    assert renewed.lease_until == T0 + timedelta(seconds=61)


# 9
def test_pre_data_expired_lease_is_safe_to_recover_ready():
    item = recover_expired_claim(
        claimed(lease=5),
        now=T0 + timedelta(seconds=5),
    )
    assert item.state == "ready"
    assert item.phase == "idle"
    assert item.claim_owner is None
    assert item.last_code == "lease_expired_before_data"
    assert retry_decision(item, now=T0 + timedelta(seconds=6)) == "send"


# 10
def test_unexpired_pre_data_claim_waits_instead_of_replaying():
    item = claimed(lease=30)
    assert retry_decision(
        item,
        now=T0 + timedelta(seconds=29),
    ) == "wait"


# 11
def test_expired_pre_data_claim_requires_recovery_transition_first():
    item = claimed(lease=5)
    assert retry_decision(
        item,
        now=T0 + timedelta(seconds=5),
    ) == "recover_ready"
    assert item.state == "claimed"


# 12
def test_mark_data_started_is_persistable_distinct_revision():
    item = claimed()
    changed = mark_data_started(
        item,
        owner="worker-a",
        claim_token="claim-a",
        now=T0 + timedelta(seconds=1),
    )
    assert changed.state == "claimed"
    assert changed.phase == "data"
    assert changed.revision == item.revision + 1


# 13
def test_data_phase_expired_lease_becomes_unknown_not_ready():
    item = recover_expired_claim(
        data_started(lease=5),
        now=T0 + timedelta(seconds=5),
    )
    assert item.state == "unknown"
    assert item.phase == "idle"
    assert item.last_code == "lease_expired_after_data_started"
    assert item.claim_owner is None


# 14
def test_data_lease_unknown_never_gets_automatic_replay():
    item = recover_expired_claim(
        data_started(lease=5),
        now=T0 + timedelta(hours=1),
    )
    assert item.state == "unknown"

    for later in (
        T0 + timedelta(hours=1),
        T0 + timedelta(days=1),
        T0 + timedelta(days=30),
    ):
        assert retry_decision(item, now=later) == "human_required"

    with pytest.raises(OutboxError, match="not_ready"):
        claim(
            item,
            owner="worker-b",
            claim_token="new-claim",
            now=T0 + timedelta(days=30),
            lease_seconds=30,
        )


# 15
def test_transport_unknown_after_data_is_human_required():
    item = finish_attempt(
        data_started(),
        owner="worker-a",
        claim_token="claim-a",
        outcome=TransportOutcome("unknown", "data_timeout"),
        now=T0 + timedelta(seconds=2),
    )
    assert item.state == "unknown"
    assert item.last_code == "data_timeout"
    assert retry_decision(item, now=T0 + timedelta(hours=5)) == "human_required"


# 16
def test_retryable_safe_failure_before_acceptance_returns_ready():
    item = finish_attempt(
        claimed(),
        owner="worker-a",
        claim_token="claim-a",
        outcome=TransportOutcome(
            "safe_failure",
            "temporary_connect_failure",
            retryable=True,
        ),
        now=T0 + timedelta(seconds=2),
    )
    assert item.state == "ready"
    assert item.last_code == "temporary_connect_failure"
    assert retry_decision(item, now=T0 + timedelta(seconds=3)) == "send"


# 17
def test_permanent_safe_failure_stops():
    item = finish_attempt(
        claimed(),
        owner="worker-a",
        claim_token="claim-a",
        outcome=TransportOutcome(
            "safe_failure",
            "recipient_rejected",
            retryable=False,
        ),
        now=T0 + timedelta(seconds=2),
    )
    assert item.state == "failed"
    assert retry_decision(item, now=T0 + timedelta(days=1)) == "stop"


# 18
def test_accepted_result_becomes_sent_and_never_retries():
    item = finish_attempt(
        data_started(),
        owner="worker-a",
        claim_token="claim-a",
        outcome=TransportOutcome("accepted", "smtp_accepted"),
        now=T0 + timedelta(seconds=2),
    )
    assert item.state == "sent"
    assert item.claim_owner is None
    assert item.last_code == "smtp_accepted"
    assert retry_decision(item, now=T0 + timedelta(days=1)) == "stop"


# 19
@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("retry", "ready"),
        ("mark_sent", "sent"),
        ("mark_failed", "failed"),
    ],
)
def test_unknown_requires_explicit_human_resolution(action, expected):
    item = resolve_unknown(
        unknown_message(),
        action=action,
        actor="owner-user-1",
        note="Synthetic reviewed outcome.",
        now=T0 + timedelta(minutes=20),
    )
    assert item.state == expected
    assert item.human_action == action
    assert item.human_actor == "owner-user-1"
    assert item.human_decided_at == T0 + timedelta(minutes=20)
    assert item.claim_owner is None


# 20
def test_stale_claim_token_cannot_finalize_and_unknown_cannot_autoretry():
    item = data_started()

    with pytest.raises(OutboxError, match="claim_not_owned"):
        finish_attempt(
            item,
            owner="worker-a",
            claim_token="stale-token",
            outcome=TransportOutcome("accepted", "smtp_accepted"),
            now=T0 + timedelta(seconds=2),
        )

    with pytest.raises(
        OutboxError,
        match="ambiguous_outcome_cannot_autoretry",
    ):
        TransportOutcome(
            "unknown",
            "data_timeout",
            retryable=True,
        )

    assert item.state == "claimed"
    assert item.phase == "data"


@pytest.mark.parametrize("kind", ["accepted", "unknown"])
def test_outcome_requires_durable_data_checkpoint(kind):
    message = new_message(idempotency_scope="portfolio", idempotency_key="reference", message_id_secret=b"x" * 32, now=T0)
    claimed = claim(message, owner="worker", claim_token="token", now=T0, lease_seconds=90)
    with pytest.raises(OutboxError, match="outcome_without_data"):
        finish_attempt(claimed, owner="worker", claim_token="token", now=T0, outcome=TransportOutcome(kind, "synthetic"))
