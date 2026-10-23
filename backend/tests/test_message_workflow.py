"""Internal replies: complete keyset pages, scoped reads, CAS, replay and rollback."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from importlib import import_module
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, insert, inspect, text
from sqlalchemy.orm import Session

from backend import auth
from backend.app import app
from backend.db.orm_models import MessageORM
from backend.dependencies import store
from backend.models import Message, MessageThreadCreate, PortfolioCreate, PropertyCreate
from backend.services import business_qol as office
from backend.services import document_versions as archive
from backend.services.message_threads import MessageSubmission, message_page, send_message


@pytest.fixture(autouse=True)
def clean():
    if os.environ.get("IMMO_EXPECT_POSTGRES") == "true":
        assert hasattr(store, "db") and store.db.get_bind().dialect.name == "postgresql"
    auth.clear_users()
    store.clear_all()
    yield
    auth.clear_users()
    store.clear_all()


@pytest.fixture
def owner():
    return auth.register_user("message-owner", "messages@example.test", "Prüfkonto", "Secret123", "eigentuemer")


@pytest.fixture
def threads(owner):
    portfolio = store.create_portfolio(PortfolioCreate(name="Sichtbarer Bestand"))
    other = store.create_portfolio(PortfolioCreate(name="Fremder Bestand"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus A", property_type="residential"))
    foreign = store.create_property(PropertyCreate(portfolio_id=other.id, name="Haus B", property_type="residential"))
    a = store.create_message_thread(MessageThreadCreate(subject="Vorgang A", property_id=prop.id))
    b = store.create_message_thread(MessageThreadCreate(subject="Vorgang B", property_id=foreign.id))
    return a, b, portfolio


def command(thread, **changes):
    return MessageSubmission(thread_id=thread.id, body="Geprüfte Nachricht äöü €", sender_name="Nicht der echte Absender",
                             base_revision=thread.updated_at.isoformat(), idempotency_key=str(uuid4()), **changes)


def fill(thread, count=10057):
    stamp = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)
    values = [{"id": f"message-{index:06}", "thread_id": thread.id, "sender_name": "Synthetic",
               "body": f"Unabhängiger Inhalt {index}", "sent_at": stamp.replace(tzinfo=None)} for index in range(count)]
    if hasattr(store, "db"):
        store.db.execute(insert(MessageORM), values)
        store.db.commit()
    else:
        for value in values:
            store.messages[value["id"]] = Message(**value)
    return {value["id"]: value["body"] for value in values}


def test_more_than_ten_thousand_same_time_messages_use_complete_bounded_keysets(owner, threads):
    a, b, _portfolio = threads
    expected = fill(a)
    statements = []
    engine = store.db.get_bind() if hasattr(store, "db") else None
    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if "messages" in statement.lower() and statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    if engine:
        event.listen(engine, "before_cursor_execute", observe)
    try:
        found = {}
        cursor = None
        order = []
        while True:
            page = message_page(store, a.id, owner.id, cursor=cursor, limit=137)
            assert page["total"] == len(expected)
            assert len(page["items"]) <= 137
            for row in reversed(page["items"]):
                assert row.thread_id == a.id and row.id not in found
                found[row.id] = row.body
                order.append(row.id)
            if page["next_cursor"] is None:
                break
            assert page["next_cursor"] != cursor
            cursor = page["next_cursor"]
        assert found == expected
        assert order == sorted(expected, reverse=True)
        assert message_page(store, b.id, owner.id)["total"] == 0
        if engine:
            reads = [query for query in statements if "count(" not in query.lower()]
            assert reads and all("LIMIT" in query.upper() for query in reads)
            assert all("OFFSET" not in query.upper() or "LIMIT" in query.upper() for query in reads)
    finally:
        if engine:
            event.remove(engine, "before_cursor_execute", observe)


def test_cursor_is_bound_to_actor_and_thread_and_rejects_malformed_keys(owner, threads):
    a, b, _portfolio = threads
    fill(a, 3)
    page = message_page(store, a.id, owner.id, limit=1)
    assert page["next_cursor"]
    other = auth.register_user("second-owner", "second@example.test", "Zweiter Eigentümer", "Secret123", "eigentuemer")
    cases = [(b.id, owner.id, page["next_cursor"]), (a.id, other.id, page["next_cursor"]),
             (a.id, owner.id, "not-json"),
             (a.id, owner.id, office.cursor_encode(["message-page-v1", owner.id, a.id], ["invalid-date", "a"]))]
    for thread_id, user_id, cursor in cases:
        with pytest.raises(HTTPException) as error:
            message_page(store, thread_id, user_id, cursor=cursor, limit=1)
        assert error.value.status_code == 422


def test_hidden_thread_stays_404_before_cursor_validation(owner, threads):
    a, b, portfolio = threads
    fill(a, 2)
    user = auth.register_user("restricted", "restricted@example.test", "Verwalter", "Secret123", "verwalter")
    auth.update_user(user.id, {"portfolio_access": "selected", "portfolio_ids": [portfolio.id]})
    assert message_page(store, a.id, user.id)["total"] == 2
    with pytest.raises(HTTPException) as error:
        message_page(store, b.id, user.id, cursor="malformed")
    assert error.value.status_code == 404
    auth.update_user(user.id, {"portfolio_access": "selected", "portfolio_ids": []})
    withdrawn = auth.get_user_by_id(user.id)
    assert withdrawn is not None and withdrawn["portfolio_ids"] == []
    with pytest.raises(HTTPException) as error:
        message_page(store, a.id, user.id)
    assert error.value.status_code == 404


def test_page_endpoint_and_keyed_http_send_preserve_the_legacy_message_shape(owner, threads):
    a, _b, _portfolio = threads
    client = TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(owner.id)}"})
    body = command(a).model_dump(mode="json")
    first = client.post(f"/api/v1/messages/threads/{a.id}/messages", json=body)
    assert first.status_code == 201, first.text
    replay = client.post(f"/api/v1/messages/threads/{a.id}/messages", json=body)
    assert replay.status_code == 201, replay.text
    assert first.json() == replay.json()
    assert "idempotency_key" not in first.json() and "base_revision" not in first.json()
    result = client.get(f"/api/v1/messages/threads/{a.id}/page?limit=1")
    assert result.status_code == 200, result.text
    assert result.json()["items"] == [first.json()]
    assert result.json()["total"] == 1
    assert result.json()["thread"]["message_count"] == 1
    assert client.get(f"/api/v1/messages/threads/{a.id}/page?limit=0").status_code == 422
    assert client.get(f"/api/v1/messages/threads/{a.id}/page?limit=251").status_code == 422


def test_replay_is_one_message_one_count_and_preserves_real_author(owner, threads):
    a, _b, _portfolio = threads
    payload = command(a)
    first = send_message(store, a.id, payload, owner.id)
    second = send_message(store, a.id, payload, owner.id)
    assert first == second
    assert first.sender_name == owner.full_name
    assert len(store.list_messages(thread_id=a.id)) == 1
    assert store.get_message_thread(a.id).message_count == 1
    assert office.same_revision(store.get_message_thread(a.id).updated_at.isoformat(), a.updated_at.isoformat()) is False


def test_same_key_with_different_body_or_thread_conflicts_without_writing(owner, threads):
    a, b, _portfolio = threads
    payload = command(a)
    send_message(store, a.id, payload, owner.id)
    for changed in (payload.model_copy(update={"body": "Andere Nachricht"}),
                    payload.model_copy(update={"thread_id": b.id, "base_revision": b.updated_at.isoformat()})):
        with pytest.raises(HTTPException) as error:
            send_message(store, changed.thread_id, changed, owner.id)
        assert error.value.status_code == 409
    assert len(store.list_messages()) == 1
    assert store.get_message_thread(b.id).message_count == 0


def test_stale_revision_is_an_editable_conflict_and_no_second_message(owner, threads):
    a, _b, _portfolio = threads
    send_message(store, a.id, command(a), owner.id)
    with pytest.raises(HTTPException) as error:
        send_message(store, a.id, command(a), owner.id)
    assert error.value.status_code == 409
    assert len(store.list_messages()) == 1
    fresh = store.get_message_thread(a.id)
    send_message(store, a.id, command(fresh), owner.id)
    assert len(store.list_messages()) == 2


def test_receipt_failure_rolls_back_message_thread_and_command(owner, threads, monkeypatch):
    a, _b, _portfolio = threads
    payload = command(a)
    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic receipt failure")
    monkeypatch.setattr(office, "save_command", fail)
    with pytest.raises(RuntimeError, match="synthetic receipt failure"):
        send_message(store, a.id, payload, owner.id)
    assert store.list_messages(thread_id=a.id) == []
    actual = store.get_message_thread(a.id)
    assert actual.message_count == 0
    assert office.same_revision(actual.updated_at.isoformat(), a.updated_at.isoformat())


def test_replay_never_resurrects_a_deleted_message(owner, threads):
    a, _b, _portfolio = threads
    payload = command(a)
    saved = send_message(store, a.id, payload, owner.id)
    store.delete_message(saved.id)
    with pytest.raises(HTTPException) as error:
        send_message(store, a.id, payload, owner.id)
    assert error.value.status_code == 409
    assert not store.list_messages()


def test_reader_cannot_send_even_with_a_known_command_key(owner, threads):
    a, _b, _portfolio = threads
    reader = auth.register_user("reader", "reader@example.test", "Leser", "Secret123", "readonly")
    with pytest.raises(HTTPException) as error:
        send_message(store, a.id, command(a), reader.id)
    assert error.value.status_code == 403
    assert not store.list_messages()


def test_parallel_retries_and_independent_connections_create_exactly_once(owner, threads, monkeypatch):
    a, _b, _portfolio = threads
    payload = command(a)
    bind = store.db.get_bind() if hasattr(store, "db") else None
    is_pg = bind is not None and bind.dialect.name == "postgresql"
    barrier = Barrier(2)
    pids = []
    original = archive.begin_writer
    if is_pg:
        def begin(db):
            original(db)
            pids.append(db.scalar(text("select pg_backend_pid()")))
            barrier.wait(timeout=15)
        monkeypatch.setattr(archive, "begin_writer", begin)
    def execute(_index):
        if bind is None:
            return send_message(store, a.id, payload, owner.id).id
        from backend.repositories.sql_store import SQLAlchemyStore
        with Session(bind=bind) as connection:
            return send_message(SQLAlchemyStore(connection), a.id, payload, owner.id).id
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(execute, range(2)))
    assert ids[0] == ids[1]
    assert len(store.list_messages(thread_id=a.id)) == 1
    if is_pg:
        assert len(set(pids)) == 2, "The native test must own two independent database connections"


def test_message_index_migration_preserves_rows_and_is_adoptable(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'message-upgrade.db'}")
    module = import_module("backend.db.migrations.versions.c61e9a2f034b_message_keyset_index")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE messages (id TEXT PRIMARY KEY, thread_id TEXT, sent_at DATETIME, body TEXT)")
            connection.exec_driver_sql("INSERT INTO messages VALUES ('original', 'thread', '2026-10-15', 'Unverändertes Original äöü')")
            before = connection.exec_driver_sql("SELECT * FROM messages").all()
            with Operations.context(MigrationContext.configure(connection)):
                module.upgrade()
                module.upgrade()
            after = connection.exec_driver_sql("SELECT * FROM messages").all()
            assert before == after
            assert any(item["name"] == "ix_messages_thread_sent_id" and item["column_names"] == ["thread_id", "sent_at", "id"]
                       for item in inspect(connection).get_indexes("messages"))
            plan = connection.exec_driver_sql("EXPLAIN QUERY PLAN SELECT * FROM messages WHERE thread_id='thread' ORDER BY sent_at DESC,id DESC LIMIT 100").all()
            assert "ix_messages_thread_sent_id" in str(plan)
    finally:
        engine.dispose()
