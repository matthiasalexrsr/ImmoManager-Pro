"""Genuine authenticated routes and validated page/query contracts."""
import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.routers import bookings
from backend.storage import InMemoryStore
from backend.tests.test_booking_pages import insert_rows, row


@pytest.fixture
def installation(monkeypatch):
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    active = InMemoryStore()
    insert_rows(active, [row(n) for n in range(35)])
    monkeypatch.setattr(bookings, "store", active)
    with TestClient(app) as client:
        yield client


def credentials(role="readonly"):
    user = auth.register_user(role, f"{role}@example.invalid", "Synthetic", "Strong123", role)
    return {"Authorization": "Bearer " + auth.create_access_token(user.id)}


def test_page_and_export_require_authentication_and_allow_approved_reader(installation):
    headers = credentials()
    for path in ("/api/v1/bookings/page", "/api/v1/bookings/export.csv"):
        assert installation.get(path).status_code == 401
        assert installation.get(path, headers=headers).status_code == 200


def test_typed_page_and_cursor_failure_are_recoverable_without_wrong_retry(installation):
    headers = credentials()
    first = installation.get("/api/v1/bookings/page", params={"page_size": 2}, headers=headers)
    assert first.status_code == 200
    value = first.json()
    assert set(value) == {"items", "next_cursor", "has_more"}
    assert len(value["items"]) == 2 and value["has_more"] is True
    invalid = installation.get("/api/v1/bookings/page", params={"page_size": 3, "cursor": value["next_cursor"]}, headers=headers)
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "cursor_filter_mismatch"
    assert invalid.json()["error"]["details"][0]["clear_code"] == "cursor_filter_mismatch"
    assert installation.get("/api/v1/bookings/page", params={"page_size": 3}, headers=headers).status_code == 200


@pytest.mark.parametrize("params", [{"sort_by": "amount"}, {"search": "x" * 201},
    {"date_from": "2026-10-01", "date_to": "2026-01-01"}, {"status": "invalid"},
    {"account_id": "a\n"}, {"page_size": 0}, {"order": "DROP TABLE bookings"}])
def test_invalid_http_filters_are_rejected_before_query(installation, params):
    assert installation.get("/api/v1/bookings/page", params=params, headers=credentials()).status_code == 422


def test_export_reuses_filters_and_rejects_cursor_or_other_unknown_params(installation):
    headers = credentials()
    response = installation.get("/api/v1/bookings/export.csv", params={"account_id": "account-1", "view": "income"}, headers=headers)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert len(response.content.decode("utf-8-sig").splitlines()) == 18
    assert installation.get("/api/v1/bookings/export.csv", params={"cursor": "garbage"}, headers=headers).status_code == 422
