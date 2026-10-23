"""An old edit token stays stale when the clock stalls or moves backwards."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import auth, storage
from backend.app import app
from backend.dependencies import store
from backend.repositories import base


@pytest.fixture(autouse=True)
def _clean():
    auth.clear_users()
    store.clear_all()
    yield
    auth.clear_users()
    store.clear_all()


@pytest.mark.parametrize("method", ["PUT", "PATCH"])
@pytest.mark.parametrize("clock_shift", [timedelta(0), timedelta(days=-1)], ids=["same_tick", "clock_rollback"])
def test_edit_tokens_advance_when_clock_does_not(monkeypatch, method, clock_shift):
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    client = TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(owner.id)}"})
    created = client.post("/api/v1/portfolios", json={"name": "Before"})
    assert created.status_code == 201, created.text
    initial = created.json()
    prior = datetime.fromisoformat(initial["updated_at"]).replace(tzinfo=timezone.utc)
    frozen = prior + clock_shift

    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz is not None else frozen.replace(tzinfo=None)

    monkeypatch.setattr(storage, "datetime", FrozenClock)
    monkeypatch.setattr(base, "datetime", FrozenClock)
    path = f"/api/v1/portfolios/{initial['id']}"
    first = client.request(method, path, json={"name": "First edit", "updated_at": initial["updated_at"]})
    assert first.status_code == 200, first.text
    first_token = datetime.fromisoformat(first.json()["updated_at"]).replace(tzinfo=timezone.utc)
    assert first_token > prior + timedelta(milliseconds=1)
    stale = client.request(method, path, json={"name": "Outdated edit", "updated_at": initial["updated_at"]})
    assert stale.status_code == 409, stale.text
    # Browser date values may retain milliseconds instead of all six fractional digits.
    current = client.request(method, path, json={
        "name": "Current edit", "updated_at": first_token.isoformat(timespec="milliseconds")})
    assert current.status_code == 200, current.text
    result = current.json()
    assert result["name"] == "Current edit" and result["created_at"] == initial["created_at"]
    assert datetime.fromisoformat(result["updated_at"]).replace(tzinfo=timezone.utc) > first_token
