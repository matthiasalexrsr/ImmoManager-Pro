"""Dedicated PostgreSQL UUID schema only; independent sessions and exact claims."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

from sqlalchemy import func, select

from backend import auth
from backend.db.orm_models import PortfolioORM
from backend.db.outbox_models import OutboxCommandORM, OutboxEventORM, ensure_outbox_schema
from backend.services import outbox as service
from backend.services.email_service import EmailResult
from backend.tests.test_outbox_journal import command, decision, review
from backend.tests.test_private_server_concurrency import postgres_database  # noqa: F401 pytest fixture


def configured(engine, monkeypatch):
    with engine.begin() as db:
        ensure_outbox_schema(db)
        db.execute(PortfolioORM.__table__.insert(), dict(id="p", name="Synthetic"))
    monkeypatch.setattr(auth, "get_user_by_id", lambda _: dict(id="actor", role="buchhaltung", is_active=True,
        portfolio_access="selected", portfolio_ids=["p"]))
    monkeypatch.setattr(service.integration_manager, "_snapshot", lambda _: (True, dict(smtp_host="127.0.0.1",
        sender_email="owner@test.invalid", sender_name="Synthetic owner", smtp_use_tls=True)))


def race(factory, operation):
    barrier = Barrier(2)
    def run(_):
        with factory() as db:
            barrier.wait(timeout=20)
            return operation(SimpleNamespace(db=db))
    with ThreadPoolExecutor(2) as pool:
        return list(pool.map(run, range(2)))


def test_pg_independent_review_and_send_replay_have_one_transport(postgres_database, monkeypatch):  # noqa: F811
    engine, factory, *_ = postgres_database
    configured(engine, monkeypatch)
    messages = race(factory, lambda store: service.create_message(store, review(), "actor"))
    assert messages[0] == messages[1]
    calls = []
    def accepted(recipient, wire, *, config, before_data):
        before_data()
        calls.append(wire)
        return EmailResult("accepted", "smtp_accepted")
    monkeypatch.setattr(service.mail, "submit_prepared_email", accepted)
    results = race(factory, lambda store: service.send_message(store, messages[0]["id"], command(messages[0]), "actor"))
    assert {value["state"] for value in results} <= {"claimed", "sent"} and "sent" in {value["state"] for value in results}
    assert len(calls) == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(OutboxCommandORM)) == 1
        assert db.scalar(select(func.count()).select_from(OutboxEventORM)) == 4
        assert service.send_message(SimpleNamespace(db=db), messages[0]["id"], command(messages[0]), "actor")["state"] == "sent"
    assert len(calls) == 1 and engine.pool.checkedout() == 0


def test_pg_unknown_manual_retry_preserves_wire_and_append_only_history(postgres_database, monkeypatch):  # noqa: F811
    engine, factory, *_ = postgres_database
    configured(engine, monkeypatch)
    calls = []
    def unknown(recipient, wire, *, config, before_data):
        before_data()
        calls.append(wire)
        return EmailResult("unknown", "deadline_exceeded")
    monkeypatch.setattr(service.mail, "submit_prepared_email", unknown)
    with factory() as db:
        store = SimpleNamespace(db=db)
        first = service.create_message(store, review(), "actor")
        unclear = service.send_message(store, first["id"], command(first), "actor")
    with factory() as db:
        store = SimpleNamespace(db=db)
        assert service.get_message(store, first["id"], "actor")["state"] == "unknown"
        ready = service.decide(store, first["id"], decision(unclear), "actor")
        assert len(calls) == 1 and ready["state"] == "ready"
        service.send_message(store, first["id"], command(ready, "second-explicit-send"), "actor")
        assert service.list_events(store, first["id"], "actor")["total"] == 8
    assert calls[0] == calls[1] and engine.pool.checkedout() == 0
