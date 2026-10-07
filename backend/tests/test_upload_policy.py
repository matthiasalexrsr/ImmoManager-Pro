"""Uploads must not be able to act as web pages on the app's origin (stored XSS)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.services.upload_policy import UploadStaticFiles

ACTIVE_CONTENT = [("x.html", "text/html"), ("x.svg", "image/svg+xml"), ("x.xml", "application/xml")]
UPLOAD_ROUTES = [
    ("/api/v1/photos/upload?entity_type=property&entity_id=p1", {}),
    ("/api/v1/documents/import", {"data": {"title": "x"}}),
    ("/api/v1/files/upload", {}),
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    from backend.services import file_storage
    monkeypatch.setattr(file_storage, "get_file_storage", lambda: file_storage.LocalStorage(str(tmp_path)))
    for module in ("photos", "documents", "files"):
        monkeypatch.setattr(f"backend.routers.{module}.get_file_storage",
                            lambda: file_storage.LocalStorage(str(tmp_path)))
    clear_users()
    yield TestClient(app)
    clear_users()


@pytest.fixture
def headers():
    user = register_user("writer", "w@example.com", "W", "Secret123", "techniker")
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.mark.parametrize("route,extra", UPLOAD_ROUTES)
@pytest.mark.parametrize("name,content_type", ACTIVE_CONTENT)
def test_active_content_uploads_are_rejected(client, headers, route, extra, name, content_type):
    resp = client.post(route, headers=headers, files={"file": (name, b"<script>x</script>", content_type)}, **extra)
    assert resp.status_code == 415


def test_photos_accept_images_only(client, headers):
    route = UPLOAD_ROUTES[0][0]
    assert client.post(route, headers=headers, files={"file": ("a.jpg", b"img", "image/jpeg")}).status_code == 201
    assert client.post(route, headers=headers, files={"file": ("a.pdf", b"pdf", "application/pdf")}).status_code == 415


@pytest.mark.parametrize("name,content_type", [("a.pdf", "application/pdf"), ("a.docx", "application/msword")])
def test_documents_still_accept_office_and_pdf(client, headers, name, content_type):
    resp = client.post("/api/v1/files/upload", headers=headers, files={"file": (name, b"data", content_type)})
    assert resp.status_code == 200


def test_upload_size_limit_applies_to_photos(client, headers, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "max_upload_size_bytes", 10)
    resp = client.post(UPLOAD_ROUTES[0][0], headers=headers, files={"file": ("a.jpg", b"x" * 11, "image/jpeg")})
    assert resp.status_code == 413


@pytest.fixture
def uploads_client(tmp_path):
    clear_users()
    user = register_user("reader", "reader@example.com", "Reader", "Secret123", "readonly")
    (tmp_path / "old.html").write_text("<script>steal()</script>", encoding="utf-8")
    (tmp_path / "photo.png").write_bytes(b"\x89PNG")
    static = FastAPI()
    static.mount("/uploads", UploadStaticFiles(directory=tmp_path), name="uploads")
    with TestClient(static, headers={"Authorization": f"Bearer {create_access_token(user.id)}"}) as client:
        yield client
    clear_users()


def test_previously_stored_html_is_served_as_sandboxed_download(uploads_client):
    resp = uploads_client.get("/uploads/old.html")
    assert resp.headers["content-disposition"] == "attachment"
    assert resp.headers["content-security-policy"] == "sandbox"
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_images_still_render_inline(uploads_client):
    resp = uploads_client.get("/uploads/photo.png")
    assert resp.status_code == 200
    assert "content-disposition" not in resp.headers
    assert resp.headers["x-content-type-options"] == "nosniff"
