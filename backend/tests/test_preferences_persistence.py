"""Actual account isolation, validation, rollback and concurrent SQL updates."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.app import app
from backend.db.orm_models import Base, UserPreferencesORM
from backend.services.preferences import PreferencesInput, read_preferences, write_preferences


@pytest.fixture
def preference_database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'preferences.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr("backend.routers.auth._get_preferences_session", factory)
    owner = auth.register_user("owner", "owner@example.com", "Synthetic Owner", "Password123", "eigentuemer")
    viewer = auth.register_user("viewer", "viewer@example.com", "Synthetic Viewer", "Password123", "readonly")
    yield factory, owner, viewer
    engine.dispose()


def test_readonly_can_store_own_preferences_without_changing_another_account(preference_database):
    factory, owner, viewer = preference_database
    with TestClient(app) as client:
        assert client.get("/api/v1/auth/users/me/preferences").status_code == 401
        headers = {"Authorization": "Bearer " + auth.create_access_token(viewer.id)}
        response = client.put("/api/v1/auth/users/me/preferences", headers=headers,
                              json={"theme": "dark", "locale": "es-ES", "user_id": owner.id})
        assert response.status_code == 200
        assert client.get("/api/v1/auth/users/me/preferences", headers=headers).json()["theme"] == "dark"
        assert client.post("/api/v1/portfolios", headers=headers, json={"name": "Forbidden"}).status_code == 403
    assert read_preferences(owner.id, factory())["theme"] == "light"
    assert read_preferences(viewer.id, factory())["locale"] == "es-ES"


@pytest.mark.parametrize("payload", [
    {"theme": None}, {"theme": "invalid"}, {"locale": "invalid"},
    {"items_per_page": 1001}, {"default_due_day": 29}, {"email_notifications": True},
])
def test_invalid_preferences_are_rejected_before_persistence(preference_database, payload):
    factory, owner, _ = preference_database
    with TestClient(app) as client:
        response = client.put("/api/v1/auth/users/me/preferences", json=payload,
                              headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)})
        assert response.status_code == 422
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(UserPreferencesORM)) == 0


def test_failed_commit_reports_failure_and_rolls_back_the_actual_database(preference_database, monkeypatch):
    factory, owner, _ = preference_database
    session = factory()
    def fail():
        raise RuntimeError("synthetic commit failure")
    monkeypatch.setattr(session, "commit", fail)
    with pytest.raises(HTTPException) as error:
        write_preferences(owner.id, PreferencesInput(theme="dark"), session)
    assert error.value.status_code == 503
    assert read_preferences(owner.id, factory())["theme"] == "light"
    with factory() as check:
        assert check.scalar(select(func.count()).select_from(UserPreferencesORM)) == 0


def test_concurrent_first_updates_preserve_both_choices_and_one_sql_row(preference_database):
    factory, owner, _ = preference_database
    barrier = Barrier(2)
    def save(payload):
        barrier.wait(timeout=5)
        return write_preferences(owner.id, PreferencesInput(**payload), factory())
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(save, [{"theme": "dark"}, {"sidebar_collapsed": True}]))
    saved = read_preferences(owner.id, factory())
    assert saved["theme"] == "dark" and saved["sidebar_collapsed"] is True
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(UserPreferencesORM)) == 1
