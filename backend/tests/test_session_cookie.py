"""The browser app's refresh token lives in an HttpOnly cookie; API clients keep it in the body."""

from http.cookies import SimpleCookie

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import auth
from backend.routers.auth import router as auth_router

APP = {"X-Token-Transport": "cookie"}
CREDENTIALS = {"username": "reader", "password": "Secret123"}


@pytest.fixture
def client():
    auth.clear_users()
    auth.register_user("reader", "reader@example.com", "Reader", "Secret123", "readonly")
    mini = FastAPI()
    mini.include_router(auth_router, prefix="/api/v1")
    with TestClient(mini, base_url="https://testserver") as browser:
        yield browser
    auth.clear_users()


def refresh_cookie(response):
    cookies = [SimpleCookie(header) for header in response.headers.get_list("set-cookie")]
    return next((cookie["immo_refresh"] for cookie in cookies if "immo_refresh" in cookie), None)


def test_the_app_gets_its_refresh_token_only_as_a_strict_httponly_cookie(client):
    response = client.post("/api/v1/auth/login", json=CREDENTIALS, headers=APP)
    assert response.status_code == 200
    assert response.json()["access_token"] and response.json()["refresh_token"] is None
    cookie = refresh_cookie(response)
    assert cookie is not None and cookie.value
    assert cookie["httponly"] and cookie["secure"] and cookie["samesite"].lower() == "strict"
    assert cookie["path"] == "/api/v1/auth"                                  # sent to the auth endpoints only
    assert response.headers["cache-control"] == "private, no-store"


def test_the_cookie_renews_and_rotates_and_the_old_one_is_refused(client):
    first = refresh_cookie(client.post("/api/v1/auth/login", json=CREDENTIALS, headers=APP)).value
    renewed = client.post("/api/v1/auth/refresh", json={}, headers=APP)
    assert renewed.status_code == 200, renewed.text
    assert renewed.json()["access_token"] and renewed.json()["refresh_token"] is None
    second = refresh_cookie(renewed).value
    assert second and second != first
    replay = client.post("/api/v1/auth/refresh", json={}, headers=APP, cookies={"immo_refresh": first})
    assert replay.status_code == 401                                         # a used refresh token never works again


def test_without_the_header_the_cookie_does_not_renew_anything(client):
    client.post("/api/v1/auth/login", json=CREDENTIALS, headers=APP)
    response = client.post("/api/v1/auth/refresh", json={})                  # e.g. a form posted from another site
    assert response.status_code == 401
    assert refresh_cookie(response) is None


def test_api_clients_keep_the_token_in_the_body_and_an_old_app_session_moves_into_the_cookie(client):
    login = client.post("/api/v1/auth/login", json=CREDENTIALS)
    body_token = login.json()["refresh_token"]
    assert body_token and refresh_cookie(login) is None
    again = client.post("/api/v1/auth/refresh", json={"refresh_token": body_token})
    assert again.status_code == 200 and again.json()["refresh_token"]
    moved = client.post("/api/v1/auth/refresh", json={"refresh_token": again.json()["refresh_token"]}, headers=APP)
    assert moved.status_code == 200 and moved.json()["refresh_token"] is None  # the stored token of an older app version
    assert refresh_cookie(moved).value


def test_logout_revokes_and_clears_the_cookie(client):
    token = refresh_cookie(client.post("/api/v1/auth/login", json=CREDENTIALS, headers=APP)).value
    out = client.post("/api/v1/auth/logout", json={}, headers=APP)
    assert out.status_code == 200
    cleared = refresh_cookie(out)
    assert cleared is not None and cleared.value == ""
    again = client.post("/api/v1/auth/refresh", json={}, headers=APP, cookies={"immo_refresh": token})
    assert again.status_code == 401


def test_many_failed_sign_ins_from_one_address_are_stopped_across_user_names(client):
    for number in range(auth.MAX_FAILED_LOGINS_PER_ADDRESS):
        assert client.post("/api/v1/auth/login", json={"username": f"guess{number}", "password": "Wrong1234x"}).status_code == 401
    blocked = client.post("/api/v1/auth/login", json=CREDENTIALS)
    assert blocked.status_code == 429                                        # even the right password waits now
    assert "dieser Adresse" in blocked.json()["detail"]
