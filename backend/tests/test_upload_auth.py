"""Private browser uploads share the existing access-token lifetime and revocation."""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend import auth
from backend.routers.auth import router as auth_router
from backend.services.upload_policy import UploadStaticFiles

COOKIE = "immo_upload_access"
PDF = b"%PDF-1.4\nprivate original bytes\n%%EOF"


@pytest.fixture
def browser(tmp_path):
    auth.clear_users()
    auth.register_user("reader", "reader@example.com", "Reader", "Secret123", "readonly")
    (tmp_path / "original.pdf").write_bytes(PDF)
    (tmp_path / "original_ocr.txt").write_text("Private OCR text", encoding="utf-8")
    (tmp_path / "photo.png").write_bytes(b"\x89PNG\r\nprivate")
    (tmp_path / "old.html").write_text("<script>private</script>", encoding="utf-8")
    mini = FastAPI()
    mini.include_router(auth_router, prefix="/api/v1")

    @mini.get("/api/v1/private", dependencies=[Depends(auth.require_auth)])
    def private():
        return {"ok": True}

    mini.mount("/uploads", UploadStaticFiles(directory=tmp_path), name="uploads")
    with TestClient(mini, base_url="https://testserver") as client:
        yield client
    auth.clear_users()


def login(browser):
    response = browser.post("/api/v1/auth/login", json={"username": "reader", "password": "Secret123"})
    assert response.status_code == 200
    return response


def private_headers(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert {part.strip().lower() for part in response.headers["vary"].split(",")} >= {"cookie", "authorization"}
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("path", ["original.pdf", "photo.png", "original_ocr.txt", "unknown.pdf"])
@pytest.mark.parametrize("method,headers", [("GET", {}), ("HEAD", {}), ("GET", {"Range": "bytes=0-7"})])
def test_anonymous_uploads_and_ocr_never_disclose_bytes_or_existence(browser, path, method, headers):
    response = browser.request(method, f"/uploads/{path}", headers=headers)
    assert response.status_code == 401
    private_headers(response)
    assert "content-range" not in response.headers
    assert PDF not in response.content
    assert b"Private OCR text" not in response.content


def test_login_cookie_preserves_pdf_range_head_images_and_ocr(browser):
    login(browser)
    assert browser.get("/uploads/original.pdf").content == PDF
    part = browser.get("/uploads/original.pdf", headers={"Range": "bytes=0-7"})
    assert part.status_code == 206
    assert part.content == PDF[:8]
    assert part.headers["content-range"] == f"bytes 0-7/{len(PDF)}"
    private_headers(part)
    head = browser.head("/uploads/original.pdf")
    assert head.status_code == 200
    assert head.content == b""
    assert int(head.headers["content-length"]) == len(PDF)
    assert browser.get("/uploads/photo.png").status_code == 200
    assert browser.get("/uploads/original_ocr.txt").text == "Private OCR text"


def test_cookie_is_host_path_limited_httponly_strict_and_expires_with_access_jwt(browser):
    response = login(browser)
    cookie = SimpleCookie(response.headers["set-cookie"])[COOKIE]
    assert cookie.value == response.json()["access_token"]
    assert cookie["path"] == "/uploads"
    assert cookie["httponly"] is True
    assert cookie["secure"] is True
    assert cookie["samesite"] == "strict"
    assert cookie["domain"] == ""
    assert parsedate_to_datetime(cookie["expires"]) == auth.decode_token(cookie.value).exp
    assert cookie["max-age"] == ""  # no second lifetime overriding the JWT deadline


def test_local_http_cookie_remains_usable_without_claiming_https(browser):
    browser.base_url = "http://testserver"
    response = login(browser)
    assert not SimpleCookie(response.headers["set-cookie"])[COOKIE]["secure"]
    assert browser.get("/uploads/original.pdf").content == PDF


def test_me_bootstraps_cookie_for_existing_bearer_session_before_app_content(browser):
    token = login(browser).json()["access_token"]
    browser.cookies.clear()
    response = browser.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert SimpleCookie(response.headers["set-cookie"])[COOKIE].value == token
    assert browser.get("/uploads/original.pdf").content == PDF


def test_refresh_replaces_cookie_with_exact_new_access_token(browser):
    old = login(browser).json()
    response = browser.post("/api/v1/auth/refresh", json={"refresh_token": old["refresh_token"]})
    assert response.status_code == 200
    new = response.json()["access_token"]
    assert new != old["access_token"]
    assert SimpleCookie(response.headers["set-cookie"])[COOKIE].value == new
    auth.revoke_token(old["access_token"])
    assert browser.get("/uploads/original.pdf").content == PDF


def test_cookie_never_authenticates_api_and_cannot_authorize_upload_writes(browser):
    token = login(browser).json()["access_token"]
    # Even a manually supplied cookie on an API path cannot become API auth.
    cookie = {"Cookie": f"{COOKIE}={token}"}
    assert browser.get("/api/v1/private", headers=cookie).status_code == 401
    assert browser.get("/api/v1/auth/me", headers=cookie).status_code == 401
    response = browser.post("/uploads/original.pdf", headers=cookie, content=b"overwrite")
    assert response.status_code == 405
    private_headers(response)
    assert browser.get("/uploads/original.pdf").content == PDF


@pytest.mark.parametrize("authorization", ["Bearer invalid", "Basic invalid", "Bearer "])
def test_explicit_invalid_authorization_cannot_fall_back_to_valid_cookie(browser, authorization):
    login(browser)
    response = browser.get("/uploads/original.pdf", headers={"Authorization": authorization})
    assert response.status_code == 401
    private_headers(response)


@pytest.mark.parametrize("state,expected", [("expired", 401), ("refresh", 401), ("revoked", 401), ("deleted", 401), ("inactive", 403)])
def test_upload_cookie_revalidates_token_and_current_user(browser, state, expected):
    tokens = login(browser).json()
    token = tokens["access_token"]
    identity = auth.decode_token(token).sub
    if state == "expired":
        token = jwt.encode({"sub": identity, "exp": datetime.now(timezone.utc) - timedelta(seconds=1), "type": "access"}, auth.SECRET_KEY, algorithm=auth.ALGORITHM)
    elif state == "refresh":
        token = tokens["refresh_token"]
    elif state == "revoked":
        auth.revoke_token(token)
    elif state == "deleted":
        auth.delete_user(identity)
    else:
        auth.update_user(identity, {"is_active": False})
    response = browser.get("/uploads/original.pdf", headers={"Cookie": f"{COOKIE}={token}"})
    assert response.status_code == expected
    private_headers(response)


def test_logout_deletes_cookie_and_rejects_its_replayed_access_token(browser):
    tokens = login(browser).json()
    response = browser.post("/api/v1/auth/logout", json=tokens)
    assert response.status_code == 200
    deleted = SimpleCookie(response.headers["set-cookie"])[COOKIE]
    assert deleted["path"] == "/uploads"
    assert deleted["max-age"] == "0"
    assert browser.get("/uploads/original.pdf").status_code == 401
    assert browser.get("/uploads/original.pdf", headers={"Cookie": f"{COOKIE}={tokens['access_token']}"}).status_code == 401


def test_logout_without_local_tokens_still_clears_browser_cookie(browser):
    login(browser)
    response = browser.post("/api/v1/auth/logout", json={})
    assert response.status_code == 200
    assert SimpleCookie(response.headers["set-cookie"])[COOKIE]["max-age"] == "0"
    assert browser.get("/uploads/original.pdf").status_code == 401


def test_valid_bearer_takes_precedence_over_invalid_cookie(browser):
    token = login(browser).json()["access_token"]
    response = browser.get("/uploads/original.pdf", headers={
        "Authorization": f"Bearer {token}", "Cookie": f"{COOKIE}=invalid",
    })
    assert response.content == PDF
    private_headers(response)


def test_conditional_request_cannot_reuse_file_after_revocation(browser):
    token = login(browser).json()["access_token"]
    first = browser.get("/uploads/original.pdf")
    headers = {"If-None-Match": first.headers["etag"]}
    conditional = browser.get("/uploads/original.pdf", headers=headers)
    assert conditional.status_code == 304
    private_headers(conditional)
    auth.revoke_token(token)
    rejected = browser.get("/uploads/original.pdf", headers=headers)
    assert rejected.status_code == 401
    private_headers(rejected)


def test_unexpected_upload_failure_is_private_without_disclosing_error(browser, monkeypatch):
    def unavailable(request):
        raise RuntimeError("private backend failure")

    monkeypatch.setattr("backend.services.upload_policy.require_upload_access", unavailable)
    with TestClient(browser.app, base_url="https://testserver", raise_server_exceptions=False) as client:
        response = client.get("/uploads/original.pdf")
    assert response.status_code == 500
    private_headers(response)
    assert b"private backend failure" not in response.content


def test_authenticated_bearer_keeps_legacy_files_private_and_sandboxed(browser):
    token = login(browser).json()["access_token"]
    browser.cookies.clear()
    headers = {"Authorization": f"Bearer {token}"}
    assert browser.get("/uploads/original.pdf", headers=headers).content == PDF
    html = browser.get("/uploads/old.html", headers=headers)
    assert html.status_code == 200
    assert html.headers["content-disposition"] == "attachment"
    assert html.headers["content-security-policy"] == "sandbox"
    private_headers(html)
    for path in ["/uploads/missing.pdf", "/uploads/%2e%2e/outside.pdf"]:
        missing = browser.get(path, headers=headers)
        assert missing.status_code == 404
        private_headers(missing)
    invalid_range = browser.get("/uploads/original.pdf", headers={**headers, "Range": "bytes=999999-"})
    assert invalid_range.status_code == 416
    private_headers(invalid_range)
    malformed_range = browser.get("/uploads/original.pdf", headers={**headers, "Range": "bytes=broken"})
    assert malformed_range.status_code == 400
    private_headers(malformed_range)
