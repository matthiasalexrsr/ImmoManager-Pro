from __future__ import annotations

import io
from contextlib import nullcontext
from datetime import date, datetime
from pathlib import Path
from threading import Event, Thread

import anyio
import pytest
from sqlalchemy import insert, select, update
from starlette.requests import ClientDisconnect

from backend import auth, dependencies
from backend.db.orm_models import CalendarEventORM, PropertyORM, UnitORM
from backend.models import (
    CalendarEvent,
    CalendarEventCreate,
    PortfolioCreate,
    PropertyCreate,
    UnitCreate,
)
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import calendar as calendar_router
from backend.routers import datev
from backend.services import calendar_ical
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.tests.test_calendar_ical_export import calendar_env as calendar_env  # noqa: F401
from backend.tests.test_private_server_concurrency import postgres_database as postgres_database  # noqa: F401


def _headers(user):
    return {"Authorization": "Bearer " + auth.create_access_token(user.id)}


def _actor_scope(user):
    record = auth.get_user_by_id(user.id)
    assert record is not None
    return scope_from_user(record)


def _bulk_events(env, count: int, *, invalid_last: bool = False) -> None:
    prop = env["own_property"]
    now = datetime(2026, 1, 1, 12, 0)
    rows = []
    for index in range(count):
        rows.append(
            {
                "id": f"bulk-{index:08d}",
                "title": f"Synthetic calendar row {index}",
                "event_type": "bulk",
                "event_date": date(2027, 1, 1),
                "event_time": None,
                "location": None,
                "participants": None,
                "property_id": prop.id,
                "unit_id": None,
                "description": None,
                "created_at": now,
                "updated_at": now,
            }
        )
    if invalid_last:
        rows.append(
            {
                "id": "zzzz-late-invalid",
                "title": "Synthetic invalid late event",
                "event_type": "bulk",
                "event_date": date(2027, 12, 31),
                "event_time": "25:61",
                "location": None,
                "participants": None,
                "property_id": prop.id,
                "unit_id": None,
                "description": None,
                "created_at": now,
                "updated_at": now,
            }
        )

    store = env["store"]
    if hasattr(store, "db"):
        store.db.execute(insert(CalendarEventORM), rows)
        store.db.commit()
        return
    raw = object.__getattribute__(store, "__dict__")["calendar_events"]
    for row in rows:
        raw[row["id"]] = CalendarEvent.model_validate(row)


def _file_event_count(path: Path) -> int:
    with path.open("rb") as source:
        return sum(line == b"BEGIN:VEVENT\r\n" for line in source)


def test_large_export_uses_bounded_batches_and_private_file(calendar_env, tmp_path, monkeypatch):
    env = calendar_env
    spool = tmp_path / "spool"
    spool.mkdir()
    _bulk_events(env, 5001)
    monkeypatch.setattr(calendar_ical, "ICAL_BATCH_SIZE", 137)

    with scope_context(_actor_scope(env["reader"])):
        compiled, _ = calendar_ical.prepare_calendar_download(
            env["store"], env["own"].id, parent=spool
        )
    directory = compiled.path.parent
    try:
        assert compiled.manifest["events"] == 5003
        assert compiled.manifest["size"] == compiled.path.stat().st_size
        assert _file_event_count(compiled.path) == 5003
        assert directory.parent == spool
        assert directory.exists()
    finally:
        compiled.close()
    assert list(spool.iterdir()) == []


def test_sql_source_change_during_export_stays_on_one_snapshot(calendar_env, monkeypatch):
    env = calendar_env
    if env["backend"] != "sqlite":
        pytest.skip("Requires the real SQLite WAL snapshot")
    monkeypatch.setattr(calendar_ical, "ICAL_BATCH_SIZE", 1)
    original = calendar_ical._event_lines
    changed = False

    def mutate_after_snapshot(event, zone):
        nonlocal changed
        if not changed:
            changed = True
            with env["engine"].begin() as writer:
                writer.execute(
                    update(CalendarEventORM)
                    .where(CalendarEventORM.id == env["all_day"].id)
                    .values(title="Changed after snapshot")
                )
                writer.execute(
                    insert(CalendarEventORM).values(
                        id="inserted-after-snapshot",
                        title="Inserted after snapshot",
                        event_type="late",
                        event_date=date(2026, 6, 17),
                        event_time=None,
                        property_id=env["own_property"].id,
                        created_at=datetime(2026, 1, 1, 12, 0),
                        updated_at=datetime(2026, 1, 1, 12, 0),
                    )
                )
        yield from original(event, zone)

    monkeypatch.setattr(calendar_ical, "_event_lines", mutate_after_snapshot)
    response = env["client"].get(
        "/api/v1/calendar/export.ics",
        params={"portfolio_id": env["own"].id},
        headers=_headers(env["reader"]),
    )
    assert response.status_code == 200, response.text
    text_value = response.content.decode("utf-8")
    assert "SUMMARY:Ganztägig" in text_value
    assert "Changed after snapshot" not in text_value
    assert "Inserted after snapshot" not in text_value
    with env["engine"].connect() as live:
        assert live.scalar(
            select(CalendarEventORM.title).where(CalendarEventORM.id == env["all_day"].id)
        ) == "Changed after snapshot"
        assert live.scalar(
            select(CalendarEventORM.id).where(CalendarEventORM.id == "inserted-after-snapshot")
        ) == "inserted-after-snapshot"


@pytest.mark.parametrize("move_kind", ["event", "property", "unit"])
def test_sql_scope_move_after_private_compile_is_denied_before_response(
    calendar_env, monkeypatch, move_kind
):
    env = calendar_env
    if env["backend"] != "sqlite":
        pytest.skip("Requires a separate SQLite WAL writer")

    unit = None
    if move_kind == "unit":
        with scope_context(None):
            unit = env["store"].create_unit(
                UnitCreate(
                    property_id=env["own_property"].id,
                    label="Synthetic scoped unit",
                    unit_type="apartment",
                )
            )
            env["store"].create_calendar_event(
                CalendarEventCreate(
                    title="Unit-scoped event",
                    event_type="scope-test",
                    event_date=date(2026, 6, 19),
                    unit_id=unit.id,
                )
            )

    original_prepare = calendar_ical.prepare_calendar_download

    def compile_then_move(store, portfolio_id, **kwargs):
        compiled, captured = original_prepare(store, portfolio_id, **kwargs)
        with env["engine"].begin() as writer:
            if move_kind == "event":
                writer.execute(
                    update(CalendarEventORM)
                    .where(CalendarEventORM.id == env["timed"].id)
                    .values(property_id=env["foreign_property"].id)
                )
            elif move_kind == "property":
                writer.execute(
                    update(PropertyORM)
                    .where(PropertyORM.id == env["own_property"].id)
                    .values(portfolio_id=env["foreign"].id)
                )
            else:
                assert unit is not None
                writer.execute(
                    update(UnitORM)
                    .where(UnitORM.id == unit.id)
                    .values(property_id=env["foreign_property"].id)
                )
        return compiled, captured

    monkeypatch.setattr(calendar_router, "prepare_calendar_download", compile_then_move)
    response = env["client"].get(
        "/api/v1/calendar/export.ics",
        params={"portfolio_id": env["own"].id},
        headers=_headers(env["reader"]),
    )
    assert response.status_code == 403
    assert "content-disposition" not in response.headers
    assert b"BEGIN:VCALENDAR" not in response.content


def test_memory_export_holds_one_lock_snapshot(calendar_env, tmp_path, monkeypatch):
    env = calendar_env
    if env["backend"] != "memory":
        pytest.skip("Requires the in-memory reference backend")
    spool = tmp_path / "spool"
    spool.mkdir()
    monkeypatch.setattr(calendar_ical, "ICAL_BATCH_SIZE", 1)
    original = calendar_ical._event_lines
    started = Event()
    finished = Event()
    thread: Thread | None = None

    def writer():
        env["store"].create_calendar_event(
            CalendarEventCreate(
                title="Created during memory export",
                event_type="concurrent",
                event_date=date(2026, 6, 18),
                property_id=env["own_property"].id,
            )
        )
        finished.set()

    def mutate(event, zone):
        nonlocal thread
        if thread is None:
            thread = Thread(target=writer)
            thread.start()
            started.set()
            assert not finished.wait(0.05)
        yield from original(event, zone)

    monkeypatch.setattr(calendar_ical, "_event_lines", mutate)
    with scope_context(_actor_scope(env["reader"])):
        compiled, _ = calendar_ical.prepare_calendar_download(
            env["store"], env["own"].id, parent=spool
        )
    try:
        assert started.is_set()
        assert "SUMMARY:Ganztägig" in compiled.path.read_text(encoding="utf-8")
        assert "Created during memory export" not in compiled.path.read_text(encoding="utf-8")
    finally:
        compiled.close()
    assert thread is not None
    thread.join(timeout=2)
    assert not thread.is_alive() and finished.is_set()
    assert any(
        item.title == "Created during memory export"
        for item in env["store"].list_calendar_events()
    )
    assert list(spool.iterdir()) == []


def test_late_invalid_row_fails_before_publish_and_cleans_workspace(
    calendar_env, tmp_path, monkeypatch
):
    env = calendar_env
    spool = tmp_path / "spool"
    spool.mkdir()
    _bulk_events(env, 257, invalid_last=True)
    monkeypatch.setattr(calendar_ical, "ICAL_BATCH_SIZE", 31)

    with scope_context(_actor_scope(env["reader"])):
        with pytest.raises(calendar_ical.CalendarExportError) as error:
            calendar_ical.prepare_calendar_download(
                env["store"], env["own"].id, parent=spool
            )
    assert error.value.code == "invalid_event_time"
    assert list(spool.iterdir()) == []

    response = env["client"].get(
        "/api/v1/calendar/export.ics",
        params={"portfolio_id": env["own"].id},
        headers=_headers(env["reader"]),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_event_time"
    assert "content-disposition" not in response.headers
    assert b"BEGIN:VCALENDAR" not in response.content


@pytest.mark.parametrize("fail_on_body", [False, True])
def test_disconnect_removes_owned_private_workspace(calendar_env, tmp_path, fail_on_body):
    env = calendar_env
    spool = tmp_path / "spool"
    spool.mkdir()
    with scope_context(_actor_scope(env["reader"])):
        compiled, captured = calendar_ical.prepare_calendar_download(
            env["store"], env["own"].id, parent=spool
        )
    directory = compiled.path.parent
    response = datev.PrivateDownloadResponse(
        compiled,
        captured,
        media_type="text/calendar",
        headers={"Content-Length": str(compiled.manifest["size"])},
    )

    async def disconnected():
        async def send(message):
            assert directory.exists()
            target = "http.response.body" if fail_on_body else "http.response.start"
            if message["type"] == target:
                raise OSError("Synthetic closed calendar connection")

        async def receive():
            return {"type": "http.disconnect"}

        await response(
            {"type": "http", "asgi": {"spec_version": "2.4"}},
            receive,
            send,
        )

    with pytest.raises((OSError, ClientDisconnect)):
        anyio.run(disconnected)
    assert not directory.exists()
    assert list(spool.iterdir()) == []


def test_postgresql_repeatable_read_calendar_snapshot(postgres_database, monkeypatch, tmp_path):
    engine, factory, _, _ = postgres_database
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    monkeypatch.setattr(auth, "_token_blacklist", set())
    monkeypatch.setattr(auth, "_blacklist_expiry", {})

    with factory() as db:
        store = SQLAlchemyStore(db)
        # Selected grants must resolve against this actual test database, not
        # the process-global development store used by unrelated tests.
        monkeypatch.setattr(dependencies, "store", store)
        with scope_context(None):
            portfolio = store.create_portfolio(
                PortfolioCreate(name="Synthetic PG calendar", timezone="UTC")
            )
            prop = store.create_property(
                PropertyCreate(
                    portfolio_id=portfolio.id,
                    name="Synthetic PG property",
                    property_type="residential",
                )
            )
            first = store.create_calendar_event(
                CalendarEventCreate(
                    title="PG first",
                    event_type="test",
                    event_date=date(2026, 1, 1),
                    property_id=prop.id,
                )
            )
            second = store.create_calendar_event(
                CalendarEventCreate(
                    title="PG second before",
                    event_type="test",
                    event_date=date(2026, 1, 2),
                    property_id=prop.id,
                )
            )
            reader = auth.register_user(
                "pg-calendar-reader",
                "pg-calendar-reader@example.test",
                "Synthetic",
                "Synthetic passphrase123!",
                "readonly",
                portfolio_access="selected",
                portfolio_ids=[portfolio.id],
            )

        monkeypatch.setattr(calendar_ical, "ICAL_BATCH_SIZE", 1)
        original = calendar_ical._event_lines
        changed = False

        def mutate(event, zone):
            nonlocal changed
            if not changed and event.id == first.id:
                changed = True
                with engine.begin() as writer:
                    writer.execute(
                        update(CalendarEventORM)
                        .where(CalendarEventORM.id == second.id)
                        .values(title="PG second changed")
                    )
            yield from original(event, zone)

        monkeypatch.setattr(calendar_ical, "_event_lines", mutate)
        with scope_context(_actor_scope(reader)):
            compiled, _ = calendar_ical.prepare_calendar_download(
                store, portfolio.id, parent=tmp_path
            )
        try:
            payload = compiled.path.read_text(encoding="utf-8")
            assert "SUMMARY:PG second before" in payload
            assert "PG second changed" not in payload
        finally:
            compiled.close()

    assert list(tmp_path.iterdir()) == []


def _response_with_final_guard(env, compiled, captured):
    body_guard = calendar_ical.calendar_chunk_scope_guard(
        env["store"], compiled, captured
    )
    return datev.PrivateDownloadResponse(
        compiled,
        captured,
        before_start=lambda: calendar_ical.revalidate_calendar_download(
            env["store"], compiled, captured
        ),
        before_chunk=body_guard,
        media_type="text/calendar",
        headers={"Content-Length": str(compiled.manifest["size"])},
    )


def _run_before_start_failure(response, directory):
    sent = []

    async def invoke():
        async def send(message):
            sent.append(message)

        async def receive():
            return {"type": "http.disconnect"}

        await response(
            {"type": "http", "asgi": {"spec_version": "2.4"}},
            receive,
            send,
        )

    with pytest.raises(Exception) as error:
        anyio.run(invoke)
    assert getattr(error.value, "status_code", None) == 403
    assert sent == []
    assert not directory.exists()


def test_source_move_after_compile_before_response_start_sends_no_headers(
    calendar_env, tmp_path
):
    env = calendar_env
    if env["backend"] != "sqlite":
        pytest.skip("Requires a separate SQLite relationship writer")
    spool = tmp_path / "spool"
    spool.mkdir()

    with scope_context(_actor_scope(env["reader"])):
        compiled, captured = calendar_ical.prepare_calendar_download(
            env["store"], env["own"].id, parent=spool
        )
    directory = compiled.path.parent
    with env["engine"].begin() as writer:
        writer.execute(
            update(CalendarEventORM)
            .where(CalendarEventORM.id == env["timed"].id)
            .values(property_id=env["foreign_property"].id)
        )

    _run_before_start_failure(
        _response_with_final_guard(env, compiled, captured),
        directory,
    )
    assert list(spool.iterdir()) == []


def test_grant_change_after_compile_before_response_start_sends_no_headers(
    calendar_env, tmp_path
):
    env = calendar_env
    spool = tmp_path / "spool"
    spool.mkdir()

    with scope_context(_actor_scope(env["reader"])):
        compiled, captured = calendar_ical.prepare_calendar_download(
            env["store"], env["own"].id, parent=spool
        )
    directory = compiled.path.parent
    auth.update_user(
        env["reader"].id,
        {"portfolio_access": "selected", "portfolio_ids": []},
        actor_id=env["owner"].id,
    )

    _run_before_start_failure(
        _response_with_final_guard(env, compiled, captured),
        directory,
    )
    assert list(spool.iterdir()) == []


@pytest.mark.parametrize("change_kind", ["source", "grant"])
def test_change_between_body_blocks_truncates_download_and_cleans_private_state(
    calendar_env, tmp_path, change_kind
):
    env = calendar_env
    if env["backend"] != "sqlite":
        pytest.skip("Requires SQLite WAL and a separate writer")
    spool = tmp_path / "spool"
    spool.mkdir()

    # One event deliberately spans multiple 1 MiB response blocks so the
    # same event relationship must be rechecked before the second block.
    with env["engine"].begin() as writer:
        writer.execute(
            update(CalendarEventORM)
            .where(CalendarEventORM.id == env["timed"].id)
            .values(description="A" * 1_300_000)
        )

    with scope_context(_actor_scope(env["reader"])):
        compiled, captured = calendar_ical.prepare_calendar_download(
            env["store"], env["own"].id, parent=spool
        )
    assert compiled.manifest["size"] > 1024 * 1024
    directory = compiled.path.parent
    response = _response_with_final_guard(env, compiled, captured)

    sent: list[tuple[str, int, bool | None]] = []
    changed = False

    async def invoke():
        async def send(message):
            nonlocal changed
            body = message.get("body", b"")
            sent.append(
                (
                    message["type"],
                    len(body),
                    message.get("more_body"),
                )
            )
            if (
                message["type"] == "http.response.body"
                and body
                and not changed
            ):
                changed = True
                if change_kind == "source":
                    with env["engine"].begin() as writer:
                        writer.execute(
                            update(CalendarEventORM)
                            .where(CalendarEventORM.id == env["timed"].id)
                            .values(property_id=env["foreign_property"].id)
                        )
                else:
                    auth.update_user(
                        env["reader"].id,
                        {
                            "portfolio_access": "selected",
                            "portfolio_ids": [],
                        },
                        actor_id=env["owner"].id,
                    )

        async def receive():
            return {"type": "http.disconnect"}

        await response(
            {"type": "http", "asgi": {"spec_version": "2.4"}},
            receive,
            send,
        )

    with pytest.raises(Exception) as error:
        anyio.run(invoke)
    assert getattr(error.value, "status_code", None) == 403
    assert changed is True
    assert sent[0][0] == "http.response.start"
    body_messages = [item for item in sent if item[0] == "http.response.body"]
    assert len(body_messages) == 1
    assert body_messages[0][1] == 1024 * 1024
    assert body_messages[0][2] is True
    assert body_messages[0][1] < compiled.manifest["size"]
    assert not directory.exists()
    assert list(spool.iterdir()) == []


def test_chunk_range_index_is_read_linearly_not_rescanned(tmp_path, monkeypatch):
    index = tmp_path / "event-ranges.jsonl"
    index.write_bytes(
        b'[100,200,"a"]\n'
        b'[200,300,"b"]\n'
        b'[300,400,"c"]\n'
    )

    decoded = 0
    original = calendar_ical._decode_index_record

    def counting_decode(raw):
        nonlocal decoded
        decoded += 1
        return original(raw)

    monkeypatch.setattr(calendar_ical, "_decode_index_record", counting_decode)
    monkeypatch.setattr(calendar_ical, "_check_live_batch", lambda *args: None)

    guard = calendar_ical.CalendarChunkScopeGuard(
        object(), "p", index, None
    )
    try:
        guard(0, 150)
        guard(150, 250)
        guard(250, 350)
        guard(350, 450)
    finally:
        guard.close()

    assert decoded == 3


def test_postgresql_scope_move_between_body_blocks_is_blocked(
    postgres_database, monkeypatch, tmp_path
):
    engine, factory, _, _ = postgres_database
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    monkeypatch.setattr(auth, "_token_blacklist", set())
    monkeypatch.setattr(auth, "_blacklist_expiry", {})

    with factory() as db:
        store = SQLAlchemyStore(db)
        monkeypatch.setattr(dependencies, "store", store)
        with scope_context(None):
            own = store.create_portfolio(
                PortfolioCreate(name="PG own", timezone="UTC")
            )
            foreign = store.create_portfolio(
                PortfolioCreate(name="PG foreign", timezone="UTC")
            )
            own_property = store.create_property(
                PropertyCreate(
                    portfolio_id=own.id,
                    name="PG own property",
                    property_type="residential",
                )
            )
            foreign_property = store.create_property(
                PropertyCreate(
                    portfolio_id=foreign.id,
                    name="PG foreign property",
                    property_type="residential",
                )
            )
            target = store.create_calendar_event(
                CalendarEventCreate(
                    title="PG spanning event",
                    event_type="scope-test",
                    event_date=date(2026, 2, 1),
                    property_id=own_property.id,
                    description="P" * 1_300_000,
                )
            )
            reader = auth.register_user(
                "pg-calendar-body-reader",
                "pg-calendar-body-reader@example.test",
                "Synthetic",
                "Synthetic passphrase123!",
                "readonly",
                portfolio_access="selected",
                portfolio_ids=[own.id],
            )

        with scope_context(_actor_scope(reader)):
            compiled, captured = calendar_ical.prepare_calendar_download(
                store, own.id, parent=tmp_path
            )
        assert compiled.manifest["size"] > 1024 * 1024
        response = datev.PrivateDownloadResponse(
            compiled,
            captured,
            before_start=lambda: calendar_ical.revalidate_calendar_download(
                store, compiled, captured
            ),
            before_chunk=calendar_ical.calendar_chunk_scope_guard(
                store, compiled, captured
            ),
            media_type="text/calendar",
            headers={"Content-Length": str(compiled.manifest["size"])},
        )
        sent = []
        changed = False

        async def invoke():
            async def send(message):
                nonlocal changed
                body = message.get("body", b"")
                sent.append(
                    (
                        message["type"],
                        len(body),
                        message.get("more_body"),
                    )
                )
                if (
                    message["type"] == "http.response.body"
                    and body
                    and not changed
                ):
                    changed = True
                    with engine.begin() as writer:
                        writer.execute(
                            update(CalendarEventORM)
                            .where(CalendarEventORM.id == target.id)
                            .values(property_id=foreign_property.id)
                        )

            async def receive():
                return {"type": "http.disconnect"}

            await response(
                {"type": "http", "asgi": {"spec_version": "2.4"}},
                receive,
                send,
            )

        with pytest.raises(Exception) as error:
            anyio.run(invoke)
        assert getattr(error.value, "status_code", None) == 403
        assert changed is True
        body_messages = [
            item for item in sent if item[0] == "http.response.body"
        ]
        assert len(body_messages) == 1
        assert body_messages[0][1] == 1024 * 1024
        assert body_messages[0][2] is True

    assert list(tmp_path.iterdir()) == []


def test_before_chunk_failure_prevents_next_private_file_read(monkeypatch):
    block = 1024 * 1024

    class TrackingPath:
        def __init__(self):
            self.read_sizes = []

        def open(self, mode):
            assert mode == "rb"
            owner = self

            class Source:
                def __enter__(self):
                    self.handle = io.BytesIO(b"A" * (block * 2))
                    return self

                def __exit__(self, *_args):
                    self.handle.close()

                def read(self, size):
                    owner.read_sizes.append(size)
                    return self.handle.read(size)

            return Source()

    class Compiled:
        def __init__(self):
            self.path = TrackingPath()
            self.manifest = {"size": block * 2}
            self.closed = False

        def close(self):
            self.closed = True

    class Helpers:
        @staticmethod
        def scope_context(_captured):
            return nullcontext()

        @staticmethod
        def refresh_scope(_captured):
            return None

    compiled = Compiled()
    monkeypatch.setattr(datev.service, "scope_helpers", lambda: Helpers)

    guard_calls = []

    def before_chunk(start, end):
        guard_calls.append((start, end))
        if start:
            from fastapi import HTTPException

            raise HTTPException(403, "Synthetic relationship move")

    async def consume():
        chunks = []
        with pytest.raises(Exception) as error:
            async for chunk in datev.download_chunks(
                compiled,
                object(),
                before_chunk=before_chunk,
            ):
                chunks.append(chunk)
        assert getattr(error.value, "status_code", None) == 403
        return chunks

    chunks = anyio.run(consume)
    assert [len(chunk) for chunk in chunks] == [block]
    assert guard_calls == [(0, block), (block, block * 2)]
    assert compiled.path.read_sizes == [block]
    assert compiled.closed is True
