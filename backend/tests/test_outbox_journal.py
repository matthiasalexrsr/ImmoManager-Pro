"""Real persisted SQLite sessions: no external SMTP, no automatic resend."""

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from backend import auth
from backend.db.credit_models import CreditReceiptORM  # noqa: F401 metadata registration
from backend.db.orm_models import Base, PortfolioORM
from backend.db.outbox_models import OutboxCommandORM, OutboxEventORM, OutboxMessageORM
from backend.outbox_models import OutboxCommand, OutboxCreate, OutboxDecision
from backend.services import outbox as service
from backend.services import outbox_state as state
from backend.services.data_transfer import TransferError, export_store_data, import_store_data
from backend.services.email_service import EmailResult
from backend.services.portfolio_scope import scope_context


def review(**changes):
    values = dict(portfolio_id="p", idempotency_key="synthetic-review", recipient="tenant@test.invalid",
        sender_address="owner@test.invalid", sender_name="Synthetic owner", subject="Synthetic Nachricht",
        body_text="Synthetic äöü\n<unsafe> is displayed as text", reviewed_by="Synthetic review", review_confirmed=True)
    values.update(changes)
    return OutboxCreate(**values)


def command(message, key="synthetic-send"):
    return OutboxCommand(idempotency_key=key, expected_revision=message["revision"], confirmed=True)


def decision(message, action="retry", key="synthetic-decision", note="Synthetic provider check\nDocumented decision"):
    return OutboxDecision(**command(message, key).model_dump(), action=action, note=note)


@pytest.fixture
def active(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'outbox.db'}", connect_args={"check_same_thread": False, "timeout": 20})
    @event.listens_for(engine, "connect")
    def configure(db, _):
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(engine)
    with engine.begin() as db:
        db.execute(PortfolioORM.__table__.insert(), [dict(id=value, name="Synthetic " + value) for value in ("p", "foreign")])
    users = {"actor": dict(id="actor", role="buchhaltung", is_active=True, portfolio_access="selected", portfolio_ids=["p"]),
             "other": dict(id="other", role="verwalter", is_active=True, portfolio_access="selected", portfolio_ids=["foreign"])}
    monkeypatch.setattr(auth, "get_user_by_id", lambda identifier: users.get(identifier))
    values = dict(smtp_host="127.0.0.1", smtp_port=587, smtp_use_tls=True, smtp_use_ssl=False,
        sender_email="owner@test.invalid", sender_name="Synthetic owner", smtp_timeout_seconds=2)
    enabled = [True]
    monkeypatch.setattr(service.integration_manager, "_snapshot", lambda _: (enabled[0], values.copy()))
    calls = []
    def accepted(recipient, wire, *, config, before_data):
        before_data()
        with Session(engine) as independent:
            persisted = independent.scalar(select(OutboxMessageORM))
            assert service.decode_state(persisted).phase == "data"  # Durable before GO.
        calls.append((recipient, wire, config))
        return EmailResult("accepted", "smtp_accepted")
    monkeypatch.setattr(service.mail, "submit_prepared_email", accepted)
    with Session(engine, autoflush=False) as db:
        yield SimpleNamespace(store=SimpleNamespace(db=db), engine=engine, users=users, values=values,
            enabled=enabled, calls=calls, accepted=accepted)
    engine.dispose()


def test_review_replay_and_snapshot_survive_new_session_and_replay_does_not_send(active):
    box = active
    first = service.create_message(box.store, review(), "actor")
    assert service.create_message(box.store, review(), "actor") == first
    with pytest.raises(HTTPException) as error:
        service.create_message(box.store, review(subject="Different content"), "actor")
    assert error.value.status_code == 409
    done = service.send_message(box.store, first["id"], command(first), "actor")
    assert done["state"] == "sent" and done["attempt_no"] == 1
    with Session(box.engine) as db:
        fresh = SimpleNamespace(db=db)
        assert service.send_message(fresh, first["id"], command(first), "actor") == done
        assert service.get_message(fresh, first["id"], "actor") == done
        events = service.list_events(fresh, first["id"], "actor")["items"]
        assert [(e["kind"], e["revision"]) for e in events] == [("transport_result", 3), ("data_checkpoint", 2), ("claim", 1), ("reviewed", 0)]
    assert len(box.calls) == 1
    wire = box.calls[0][1]
    assert hashlib.sha256(wire).hexdigest() == done["wire_sha256"]
    parsed = BytesParser(policy=policy.default).parsebytes(wire)
    assert parsed["Message-ID"] == first["message_id"]
    assert parsed.get_body(preferencelist=("plain",)).get_content().replace("\r\n", "\n").rstrip() == review().body_text
    assert "&lt;unsafe&gt;" in parsed.get_body(preferencelist=("html",)).get_content()
    assert not {"claim_token", "wire", "smtp_password"} & done.keys()


@pytest.mark.parametrize("change", [{"review_confirmed": False}, {"review_confirmed": "true"}, {"reviewed_by": " "}, {"body_text": ""}, {"idempotency_key": "bad\nreference"}, {"reviewed_by": "bad\ud800text"}])
def test_unreviewed_content_is_rejected(change):
    with pytest.raises(ValidationError):
        review(**change)


@pytest.mark.parametrize("change, code", [({"recipient": "name\r\nBcc: other@test.invalid"}, "invalid_content"),
    ({"subject": "bad\nheader"}, "invalid_content"), ({"body_text": "ä" * 700_000}, "message_too_large"),
    ({"sender_address": "wrong@test.invalid"}, "sender_changed")])
def test_invalid_or_oversize_review_preserves_draft_without_journal(active, change, code):
    with pytest.raises(HTTPException, match=code):
        service.create_message(active.store, review(**change), "actor")
    assert active.store.db.scalar(select(func.count()).select_from(OutboxMessageORM)) == 0
    assert active.calls == []


def test_unknown_requires_documented_manual_decision_and_second_explicit_send(active, monkeypatch):
    first = service.create_message(active.store, review(), "actor")
    def lost_reply(recipient, wire, *, config, before_data):
        before_data()
        active.calls.append(wire)
        return EmailResult("unknown", "deadline_exceeded")
    monkeypatch.setattr(service.mail, "submit_prepared_email", lost_reply)
    unclear = service.send_message(active.store, first["id"], command(first), "actor")
    assert unclear["state"] == "unknown"
    with pytest.raises(HTTPException) as error:
        service.send_message(active.store, first["id"], command(unclear, "forbidden-repeat"), "actor")
    assert error.value.status_code == 409 and len(active.calls) == 1
    with pytest.raises(ValidationError):
        decision(unclear, note=" ")
    ready = service.decide(active.store, first["id"], decision(unclear), "actor")
    assert ready["state"] == "ready" and len(active.calls) == 1
    assert service.decide(active.store, first["id"], decision(unclear), "actor") == ready
    monkeypatch.setattr(service.mail, "submit_prepared_email", active.accepted)
    done = service.send_message(active.store, first["id"], command(ready, "explicit-second-send"), "actor")
    assert done["state"] == "sent" and done["attempt_no"] == 2
    assert active.calls[0] == active.calls[1][1]  # Exact original MIME / Date / Message-ID.
    events = service.list_events(active.store, first["id"], "actor")["items"]
    assert len(events) == 8 and next(e for e in events if e["kind"] == "decision")["note"] == decision(unclear).note


@pytest.mark.parametrize("action, target", [("mark_sent", "sent"), ("mark_failed", "failed")])
def test_human_resolution_is_journaled_without_transport(active, action, target):
    first = service.create_message(active.store, review(), "actor")
    _, claimed = service.claim_message(active.store, first["id"], command(first), "actor")
    identifier, token, captured = claimed
    service.mark_data(active.store, first["id"], "actor", token, captured, service.configuration()[1])
    unclear = service.finish_owned(active.store, first["id"], "actor", token, identifier, state.TransportOutcome("unknown", "lost_reply"))
    result = service.decide(active.store, first["id"], decision(unclear, action), "actor")
    assert result["state"] == target and result["human_actor"] == "actor" and active.calls == []
    assert service.list_events(active.store, first["id"], "actor")["items"][0]["note"] == decision(unclear).note


@pytest.mark.parametrize("data_started, target", [(False, "ready"), (True, "unknown")])
def test_expired_claim_is_only_recovered_by_explicit_action_and_restored_db_has_same_safety(active, monkeypatch, tmp_path, data_started, target):
    first = service.create_message(active.store, review(), "actor")
    _, claimed = service.claim_message(active.store, first["id"], command(first), "actor")
    _, token, captured = claimed
    if data_started:
        service.mark_data(active.store, first["id"], "actor", token, captured, service.configuration()[1])
    now = service.utcnow() + timedelta(seconds=100)
    monkeypatch.setattr(service, "utcnow", lambda: now)
    before = service.get_message(active.store, first["id"], "actor")
    assert before["state"] == "claimed" and active.calls == []  # Reading is never recovery/send.
    original_path = active.engine.url.database
    restored_path = tmp_path / "restored-synthetic.db"
    with sqlite3.connect(original_path) as original, sqlite3.connect(restored_path) as restored:
        original.backup(restored)
    restored_engine = create_engine(f"sqlite:///{restored_path}")
    try:
        with Session(restored_engine) as db:
            restored = SimpleNamespace(db=db)
            assert service.get_message(restored, first["id"], "actor") == before
            after = service.decide(restored, first["id"], command(before, "explicit-recovery"), "actor", recover=True)
            assert after["state"] == target and active.calls == []
            assert service.get_message(active.store, first["id"], "actor")["state"] == "claimed"
    finally:
        restored_engine.dispose()


def test_exact_claim_token_phase_and_revision_protect_completion(active):
    first = service.create_message(active.store, review(), "actor")
    _, claimed = service.claim_message(active.store, first["id"], command(first), "actor")
    identifier, token, _ = claimed
    for wrong_token, outcome in [("foreign-token", state.TransportOutcome("safe_failure", "failed")),
        (token, state.TransportOutcome("accepted", "smtp_accepted"))]:
        with pytest.raises(HTTPException):
            service.finish_owned(active.store, first["id"], "actor", wrong_token, identifier, outcome)
    assert service.get_message(active.store, first["id"], "actor")["phase"] == "pre_data"
    with pytest.raises(HTTPException) as error:
        service.decide(active.store, first["id"], decision(first), "actor")
    assert error.value.status_code == 412


def test_scope_revoked_before_data_never_releases_data_and_records_safe_failure(active, monkeypatch):
    first = service.create_message(active.store, review(), "actor")
    go = []
    def revoke(recipient, wire, *, config, before_data):
        active.users["actor"]["portfolio_ids"] = []
        try:
            before_data()
        except HTTPException:
            return EmailResult("not_sent", "data_not_authorized")
        go.append(True)
        return EmailResult("accepted", "smtp_accepted")
    monkeypatch.setattr(service.mail, "submit_prepared_email", revoke)
    with pytest.raises(HTTPException) as error:
        service.send_message(active.store, first["id"], command(first), "actor")
    assert error.value.status_code == 403 and not go
    with Session(active.engine) as db, scope_context(None):
        persisted = service.decode_state(db.get(OutboxMessageORM, first["id"]))
        assert persisted.state == "failed" and persisted.last_code == "data_not_authorized"
        assert db.scalar(select(func.count()).select_from(OutboxEventORM)) == 3


def test_scope_revoked_after_data_preserves_exact_actual_result_without_more_transport(active, monkeypatch):
    first = service.create_message(active.store, review(), "actor")
    def revoke_after_data(recipient, wire, *, config, before_data):
        before_data()
        active.calls.append(wire)
        active.users["actor"]["portfolio_ids"] = []
        return EmailResult("accepted", "smtp_accepted")
    monkeypatch.setattr(service.mail, "submit_prepared_email", revoke_after_data)
    with pytest.raises(HTTPException) as error:
        service.send_message(active.store, first["id"], command(first), "actor")
    assert error.value.status_code == 403
    with Session(active.engine) as db, scope_context(None):
        assert service.decode_state(db.get(OutboxMessageORM, first["id"])).state == "sent"
        result_event = db.scalar(select(OutboxEventORM).where(OutboxEventORM.kind == "transport_result"))
        assert result_event.actor_id == "actor" and result_event.code == "smtp_accepted"
    with pytest.raises(HTTPException):
        service.send_message(active.store, first["id"], command(first), "actor")
    assert len(active.calls) == 1


def test_foreign_portfolio_readonly_and_disabled_smtp_cannot_send(active):
    first = service.create_message(active.store, review(), "actor")
    with pytest.raises(HTTPException) as error:
        service.get_message(active.store, first["id"], "other")
    assert error.value.status_code == 404
    active.users["actor"]["role"] = "readonly"
    assert service.get_message(active.store, first["id"], "actor")["state"] == "ready"
    with pytest.raises(HTTPException) as error:
        service.send_message(active.store, first["id"], command(first), "actor")
    assert error.value.status_code == 403
    active.users["actor"]["role"] = "buchhaltung"
    active.enabled[0] = False
    with pytest.raises(HTTPException, match="smtp_disabled"):
        service.send_message(active.store, first["id"], command(first), "actor")
    assert active.calls == [] and service.get_message(active.store, first["id"], "actor")["revision"] == 0


def test_independent_sqlite_sessions_review_and_claim_exactly_once(active):
    barrier = Barrier(2)
    def review_race(_):
        with Session(active.engine, autoflush=False) as db:
            barrier.wait(timeout=20)
            return service.create_message(SimpleNamespace(db=db), review(), "actor")
    with ThreadPoolExecutor(2) as threads:
        reviews = list(threads.map(review_race, range(2)))
    assert reviews[0] == reviews[1]
    def send_race(_):
        with Session(active.engine, autoflush=False) as db:
            barrier.wait(timeout=20)
            return service.send_message(SimpleNamespace(db=db), reviews[0]["id"], command(reviews[0]), "actor")
    with ThreadPoolExecutor(2) as threads:
        results = list(threads.map(send_race, range(2)))
    assert {result["state"] for result in results} <= {"claimed", "sent"} and "sent" in {result["state"] for result in results}
    assert len(active.calls) == 1
    with Session(active.engine) as db:
        assert db.scalar(select(func.count()).select_from(OutboxMessageORM)) == 1
        assert db.scalar(select(func.count()).select_from(OutboxCommandORM)) == 1
        assert db.scalar(select(func.count()).select_from(OutboxEventORM)) == 4


def test_caller_disconnect_after_data_is_unknown_not_automatic_resend(active, monkeypatch):
    first = service.create_message(active.store, review(), "actor")
    def interrupted(recipient, wire, *, config, before_data):
        before_data()
        raise KeyboardInterrupt("Synthetic disconnected caller")
    monkeypatch.setattr(service.mail, "submit_prepared_email", interrupted)
    with pytest.raises(KeyboardInterrupt):
        service.send_message(active.store, first["id"], command(first), "actor")
    persisted = service.get_message(active.store, first["id"], "actor")
    assert persisted["state"] == "unknown" and persisted["last_code"] == "caller_interrupted"
    assert service.send_message(active.store, first["id"], command(first), "actor") == persisted


def test_partial_json_restore_refuses_outbox_before_mutation(active):
    first = service.create_message(active.store, review(), "actor")
    from backend.repositories.sql_store import SQLAlchemyStore
    store = SQLAlchemyStore(active.store.db)
    snapshot = export_store_data(store, "synthetic-test")
    with pytest.raises(TransferError, match="outbox_messages"):
        import_store_data(store, snapshot, replace_existing=True)
    assert service.get_message(active.store, first["id"], "actor")["snapshot"] == first["snapshot"]


def test_memory_backend_fails_closed_before_claim():
    with pytest.raises(HTTPException) as error:
        service.create_message(object(), review(), "actor")
    assert error.value.status_code == 503


def test_transport_configuration_change_before_data_cannot_submit_a_body(active, monkeypatch):
    first = service.create_message(active.store, review(), "actor")
    def config_changes(recipient, wire, *, config, before_data):
        active.values["smtp_port"] = 588
        try:
            before_data()
        except HTTPException:
            return EmailResult("not_sent", "data_not_authorized")
        raise AssertionError("Changed transport must not release DATA")
    monkeypatch.setattr(service.mail, "submit_prepared_email", config_changes)
    with pytest.raises(HTTPException, match="transport_changed"):
        service.send_message(active.store, first["id"], command(first), "actor")
    assert service.get_message(active.store, first["id"], "actor")["state"] == "failed" and active.calls == []


def test_two_distinct_claim_commands_share_one_revision_and_one_attempt(active):
    first = service.create_message(active.store, review(), "actor")
    barrier = Barrier(2)
    def claim_race(index):
        with Session(active.engine, autoflush=False) as db:
            barrier.wait(timeout=20)
            try:
                return service.claim_message(SimpleNamespace(db=db), first["id"], command(first, f"different-{index}"), "actor")[0]["state"]
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(claim_race, range(2)))
    assert sorted(map(str, results)) == ["412", "claimed"]
    persisted = service.get_message(active.store, first["id"], "actor")
    assert persisted["attempt_no"] == 1 and persisted["revision"] == 1 and active.calls == []
