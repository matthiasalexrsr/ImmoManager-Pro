from __future__ import annotations

import hashlib
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from backend import auth, dependencies
from backend.db.orm_models import Base
from backend.models import CalendarEventCreate, PortfolioCreate, PropertyCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import calendar as calendar_router
from backend.services import calendar_ical
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.services.portfolio_scope import scope_context
from backend.storage import InMemoryStore


def _headers(user):
    return {"Authorization": "Bearer " + auth.create_access_token(user.id)}


def _unfold(raw: bytes) -> list[str]:
    text_value = raw.decode("utf-8")
    logical: list[str] = []
    for line in text_value.split("\r\n"):
        if not line:
            continue
        if line.startswith((" ", "\t")) and logical:
            logical[-1] += line[1:]
        else:
            logical.append(line)
    return logical


@pytest.fixture(params=["memory", "sqlite"])
def calendar_env(request, tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + (tmp_path / "calendar.sqlite").as_posix(),
        connect_args={"check_same_thread": False},
        hide_parameters=True,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = Session(engine)
    store = InMemoryStore() if request.param == "memory" else SQLAlchemyStore(db)

    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    monkeypatch.setattr(auth, "_token_blacklist", set())
    monkeypatch.setattr(auth, "_blacklist_expiry", {})
    monkeypatch.setattr(calendar_router, "store", store)
    monkeypatch.setattr(dependencies, "store", store)

    with scope_context(None):
        own = store.create_portfolio(
            PortfolioCreate(name="Haus Ä 😊", timezone="Europe/Berlin")
        )
        foreign = store.create_portfolio(
            PortfolioCreate(name="Fremd", timezone="UTC")
        )
        own_property = store.create_property(
            PropertyCreate(
                portfolio_id=own.id,
                name="Eigen",
                property_type="residential",
            )
        )
        foreign_property = store.create_property(
            PropertyCreate(
                portfolio_id=foreign.id,
                name="Fremd",
                property_type="residential",
            )
        )
        timed = store.create_calendar_event(
            CalendarEventCreate(
                title="Übergabe 😊, Küche; lang " + "Ä😊" * 50,
                event_type="handover,internal",
                event_date=date(2026, 6, 15),
                event_time="09:30",
                location="Straße 1, Hof; links\\rechts\n2. Etage",
                participants="Mieter; Verwaltung, Hausmeister",
                property_id=own_property.id,
                description="Zeile eins\nZeile zwei, mit Semikolon; und \\.",
            )
        )
        all_day = store.create_calendar_event(
            CalendarEventCreate(
                title="Ganztägig",
                event_type="deadline",
                event_date=date(2026, 6, 16),
                property_id=own_property.id,
            )
        )
        hidden = store.create_calendar_event(
            CalendarEventCreate(
                title="Fremdes Ereignis",
                event_type="private",
                event_date=date(2026, 6, 17),
                property_id=foreign_property.id,
            )
        )
        owner = auth.register_user(
            "calendar-owner",
            "calendar-owner@example.test",
            "Synthetic owner",
            "Synthetic passphrase123!",
            "eigentuemer",
        )
        reader = auth.register_user(
            "calendar-reader",
            "calendar-reader@example.test",
            "Synthetic reader",
            "Synthetic passphrase123!",
            "readonly",
            portfolio_access="selected",
            portfolio_ids=[own.id],
        )

    app = FastAPI()
    app.include_router(calendar_router.router, prefix="/api/v1")
    with TestClient(PortfolioScopeMiddleware(app)) as client:
        yield {
            "store": store,
            "own": own,
            "foreign": foreign,
            "own_property": own_property,
            "foreign_property": foreign_property,
            "timed": timed,
            "all_day": all_day,
            "hidden": hidden,
            "owner": owner,
            "reader": reader,
            "client": client,
            "backend": request.param,
            "engine": engine,
        }

    db.close()
    engine.dispose()


def test_authenticated_scoped_download_is_stable_and_rfc_safe(calendar_env):
    env = calendar_env
    client = env["client"]
    url = "/api/v1/calendar/export.ics"

    assert client.get(url, params={"portfolio_id": env["own"].id}).status_code == 401
    first = client.get(
        url,
        params={"portfolio_id": env["own"].id},
        headers=_headers(env["reader"]),
    )
    second = client.get(
        url,
        params={"portfolio_id": env["own"].id},
        headers=_headers(env["reader"]),
    )
    owner_view = client.get(
        url,
        params={"portfolio_id": env["own"].id},
        headers=_headers(env["owner"]),
    )

    assert first.status_code == 200, first.text
    assert first.content == second.content
    assert owner_view.status_code == 200
    assert "Fremdes Ereignis" not in owner_view.content.decode("utf-8")
    assert first.headers["content-type"] == "text/calendar; charset=utf-8"
    assert first.headers["content-disposition"] == 'attachment; filename="immomanager-calendar.ics"'
    assert first.headers["cache-control"] == "private, no-store"
    assert first.headers["x-content-type-options"] == "nosniff"
    assert int(first.headers["content-length"]) == len(first.content)
    assert first.headers["x-content-sha256"] == hashlib.sha256(first.content).hexdigest()

    logical = _unfold(first.content)
    body = "\n".join(logical)
    assert "BEGIN:VCALENDAR" in body and "END:VCALENDAR" in body
    assert "VERSION:2.0" in body
    assert "METHOD:" not in body
    assert "ATTENDEE" not in body and "ORGANIZER" not in body
    assert "X-IMMOMANAGER-SOURCE-TZID:Europe/Berlin" in body
    assert f"UID:{calendar_ical._stable_uid(env['timed'].id)}" in body
    assert "DTSTART:20260615T073000Z" in body
    assert "DTSTART;VALUE=DATE:20260616" in body
    assert "Fremdes Ereignis" not in body
    assert "SUMMARY:Übergabe 😊\\, Küche\\; lang " in body
    assert "LOCATION:Straße 1\\, Hof\\; links\\\\rechts\\n2. Etage" in body
    assert "DESCRIPTION:Zeile eins\\nZeile zwei\\, mit Semikolon\\; und \\\\." in body
    assert "X-IMMOMANAGER-PARTICIPANTS:Mieter\\; Verwaltung\\, Hausmeister" in body

    physical = [line for line in first.content.split(b"\r\n") if line]
    assert all(len(line) <= 75 for line in physical)
    assert any(line.startswith(b" ") for line in physical)
    first.content.decode("utf-8")


def test_foreign_portfolio_is_hidden_for_scoped_reader(calendar_env):
    response = calendar_env["client"].get(
        "/api/v1/calendar/export.ics",
        params={"portfolio_id": calendar_env["foreign"].id},
        headers=_headers(calendar_env["reader"]),
    )
    assert response.status_code == 404
    assert "Fremdes Ereignis" not in response.text
    assert "content-disposition" not in response.headers


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("event_time", "25:61", "invalid_event_time"),
        ("event_time", "02:30", "nonexistent_local_time"),
    ],
)
def test_invalid_event_time_returns_422(calendar_env, field, value, code):
    env = calendar_env
    store = env["store"]
    target = env["timed"]
    if field == "event_time" and value == "02:30":
        new_date = date(2026, 3, 29)
    else:
        new_date = target.event_date

    if hasattr(store, "db"):
        store.db.execute(
            text("UPDATE calendar_events SET event_time=:clock, event_date=:day WHERE id=:id"),
            {"clock": value, "day": new_date.isoformat(), "id": target.id},
        )
        store.db.commit()
    else:
        raw = object.__getattribute__(store, "__dict__")["calendar_events"]
        raw[target.id] = target.model_copy(update={"event_time": value, "event_date": new_date})

    response = env["client"].get(
        "/api/v1/calendar/export.ics",
        params={"portfolio_id": env["own"].id},
        headers=_headers(env["reader"]),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert "content-disposition" not in response.headers


def test_invalid_portfolio_timezone_returns_422(calendar_env):
    env = calendar_env
    store = env["store"]
    if hasattr(store, "db"):
        store.db.execute(
            text("UPDATE portfolios SET timezone='Mars/Olympus' WHERE id=:id"),
            {"id": env["own"].id},
        )
        store.db.commit()
    else:
        raw = object.__getattribute__(store, "__dict__")["portfolios"]
        raw[env["own"].id] = raw[env["own"].id].model_copy(
            update={"timezone": "Mars/Olympus"}
        )

    response = env["client"].get(
        "/api/v1/calendar/export.ics",
        params={"portfolio_id": env["own"].id},
        headers=_headers(env["reader"]),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_timezone"


def test_rights_lost_before_publish_returns_no_calendar(calendar_env, monkeypatch):
    env = calendar_env
    original = calendar_ical.refresh_scope
    calls = 0

    def revoke_on_second_check(scope):
        nonlocal calls
        calls += 1
        if calls == 2:
            auth.update_user(
                env["reader"].id,
                {"portfolio_access": "selected", "portfolio_ids": []},
                actor_id=env["owner"].id,
            )
        return original(scope)

    monkeypatch.setattr(calendar_ical, "refresh_scope", revoke_on_second_check)
    response = env["client"].get(
        "/api/v1/calendar/export.ics",
        params={"portfolio_id": env["own"].id},
        headers=_headers(env["reader"]),
    )
    assert response.status_code == 403
    assert b"BEGIN:VCALENDAR" not in response.content
    assert "content-disposition" not in response.headers
