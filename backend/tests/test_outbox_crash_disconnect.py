"""Hard process termination and a real ASGI disconnected response keep journal evidence."""

import json
import multiprocessing as mp
import os
from datetime import timedelta
from types import SimpleNamespace

import anyio
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend import auth, dependencies
from backend.db.outbox_models import OutboxMessageORM
from backend.routers import outbox
from backend.services import outbox as service
from backend.services.email_service import EmailConfig, EmailResult
from backend.tests.test_outbox_journal import active as active
from backend.tests.test_outbox_journal import command, review


def crash_claim(database_url, message, data_started):
    """Child owns only a supplied synthetic database; no SMTP is invoked."""
    engine = create_engine(database_url)
    auth.get_user_by_id = lambda _: dict(id="actor", role="buchhaltung", is_active=True,
        portfolio_access="selected", portfolio_ids=["p"])
    config = EmailConfig(smtp_host="127.0.0.1", from_address="owner@test.invalid", from_name="Synthetic owner")
    service.configuration = lambda **_: (True, config)
    with Session(engine) as db:
        store = SimpleNamespace(db=db)
        _, claimed = service.claim_message(store, message["id"], command(message), "actor")
        if data_started:
            _, token, captured = claimed
            service.mark_data(store, message["id"], "actor", token, captured, config)
        os._exit(23)  # Intentional hard exit, without Session/finally cleanup.


@pytest.mark.parametrize("data_started, target", [(False, "ready"), (True, "unknown")])
def test_hard_crash_is_durable_and_explicit_recovery_never_sends(active, monkeypatch, data_started, target):
    first = service.create_message(active.store, review(), "actor")
    child = mp.get_context("spawn").Process(target=crash_claim, args=(str(active.engine.url), first, data_started))
    child.start()
    try:
        child.join(15)
        assert not child.is_alive() and child.exitcode == 23
    finally:
        if child.is_alive():
            child.kill()
            child.join(2)
        child.close()
    persisted = service.get_message(active.store, first["id"], "actor")
    assert persisted["state"] == "claimed" and persisted["phase"] == ("data" if data_started else "pre_data")
    now = service.utcnow() + timedelta(seconds=100)
    monkeypatch.setattr(service, "utcnow", lambda: now)
    recovered = service.decide(active.store, first["id"], command(persisted, "after-hard-crash"), "actor", recover=True)
    assert recovered["state"] == target and active.calls == []


def test_actual_asgi_response_disconnect_keeps_accepted_receipt_and_replay_never_resends(active, monkeypatch):
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    monkeypatch.setattr(auth, "get_user_by_id", auth._user_store.get_by_id)
    from backend.repositories.sql_store import SQLAlchemyStore
    monkeypatch.setattr(dependencies, "store", SQLAlchemyStore(active.store.db))
    monkeypatch.setattr(outbox, "store", active.store)
    user = auth.register_user("disconnected-outbox", "disconnect@example.test", "Synthetic", "Strong123", "buchhaltung",
        portfolio_access="selected", portfolio_ids=["p"])
    first = service.create_message(active.store, review(), user.id)
    app = FastAPI()
    app.include_router(outbox.router, prefix="/api/v1")
    payload = json.dumps(command(first).model_dump()).encode()
    path = "/api/v1/messages/outbox/" + first["id"] + "/send"
    async def disconnected():
        delivered = False
        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": payload, "more_body": False}
            return {"type": "http.disconnect"}
        async def send(message):
            if message["type"] == "http.response.start":
                raise OSError("Synthetic disconnected HTTP client")
        await app({"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "method": "POST",
            "path": path, "raw_path": path.encode(), "root_path": "", "query_string": b"", "http_version": "1.1",
            "scheme": "http", "server": ("synthetic", 80), "client": ("127.0.0.1", 12345),
            "headers": [(b"authorization", ("Bearer " + auth.create_access_token(user.id)).encode()),
                        (b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]}, receive, send)
    with pytest.raises(OSError, match="disconnected HTTP"):
        anyio.run(disconnected)
    with Session(active.engine) as db:
        persisted = service.decode_state(db.get(OutboxMessageORM, first["id"]))
        assert persisted.state == "sent" and persisted.last_code == "smtp_accepted"
        assert service.send_message(SimpleNamespace(db=db), first["id"], command(first), user.id)["state"] == "sent"
    assert len(active.calls) == 1


def test_checkpoint_database_failure_sends_no_data_and_rollback_preserves_safe_journal(active, monkeypatch):
    first = service.create_message(active.store, review(), "actor")
    original = service.commit
    def fail_checkpoint(db):
        db.rollback()
        raise RuntimeError("Synthetic storage unavailable at DATA checkpoint")
    def guarded(recipient, wire, *, config, before_data):
        try:
            before_data()
        except RuntimeError:
            monkeypatch.setattr(service, "commit", original)
            return EmailResult("not_sent", "data_not_authorized")
        raise AssertionError("DATA must never be released")
    monkeypatch.setattr(service.mail, "submit_prepared_email", guarded)
    monkeypatch.setattr(service, "commit", fail_checkpoint)
    with pytest.raises(Exception, match="outbox_checkpoint_failed"):
        service.send_message(active.store, first["id"], command(first), "actor")
    persisted = service.get_message(active.store, first["id"], "actor")
    assert persisted["state"] == "failed"
    assert [event["kind"] for event in service.list_events(active.store, first["id"], "actor")["items"]] == ["transport_result", "claim", "reviewed"]
    assert active.calls == []


def test_result_storage_failure_after_accepted_data_leaves_claim_for_explicit_unknown_recovery(active, monkeypatch):
    first = service.create_message(active.store, review(), "actor")
    original = service.commit
    calls = []
    def fail_result(db):
        db.rollback()
        raise HTTPException(503, "outbox_database_unavailable: synthetic result failure")
    def accepted_then_db_fails(recipient, wire, *, config, before_data):
        before_data()
        calls.append(wire)
        monkeypatch.setattr(service, "commit", fail_result)
        return EmailResult("accepted", "smtp_accepted")
    monkeypatch.setattr(service.mail, "submit_prepared_email", accepted_then_db_fails)
    with pytest.raises(HTTPException) as error:
        service.send_message(active.store, first["id"], command(first), "actor")
    assert error.value.status_code == 503
    monkeypatch.setattr(service, "commit", original)
    persisted = service.get_message(active.store, first["id"], "actor")
    assert persisted["state"] == "claimed" and persisted["phase"] == "data"
    assert service.send_message(active.store, first["id"], command(first), "actor") == persisted and len(calls) == 1
    now = service.utcnow() + timedelta(seconds=100)
    monkeypatch.setattr(service, "utcnow", lambda: now)
    unclear = service.decide(active.store, first["id"], command(persisted, "investigate-result-failure"), "actor", recover=True)
    assert unclear["state"] == "unknown" and len(calls) == 1
