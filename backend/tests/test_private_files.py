import os
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.plugins.runtime import AuthenticatedPlugin
from backend.services import file_storage
from backend.static_access import PrivateStaticFiles, frontend_file, frontend_response


def test_default_storage_uses_the_configured_installation_upload_directory(tmp_path):
    uploads = tmp_path / "installation-uploads"
    result = subprocess.run(
        [sys.executable, "-c", "from backend.services.file_storage import get_file_storage; from backend.paths import get_uploads_dir; assert get_file_storage().base_dir == get_uploads_dir(); print(get_file_storage().base_dir)"],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "UPLOADS_DIR": str(uploads), "DATA_DIR": str(tmp_path), "PYTHONUTF8": "1"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert str(uploads) in result.stdout
    assert uploads.is_dir()


@pytest.fixture
def private_files(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    storage = file_storage.LocalStorage(str(tmp_path / "uploads"))
    monkeypatch.setattr(file_storage, "_storage", storage)
    storage.base_dir.joinpath("private.txt").write_text("Private installation file", encoding="utf-8")
    uploads_mount = next(route for route in app.routes if getattr(route, "name", None) == "uploads")
    monkeypatch.setattr(uploads_mount, "app", AuthenticatedPlugin(PrivateStaticFiles(directory=storage.base_dir)))
    client = TestClient(app)
    yield client, storage


@pytest.mark.parametrize("role", ["eigentuemer", "readonly"])
def test_uploads_and_download_require_valid_authentication_and_allow_readonly(private_files, role):
    client, _ = private_files
    paths = ["/uploads/private.txt", "/api/v1/files/download?key=private.txt"]
    user = auth.register_user(role, f"{role}@example.com", role, "Strong123", role)
    headers = {"Authorization": f"Bearer {auth.create_access_token(user.id)}"}
    for path in paths:
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 401
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        assert response.text == "Private installation file"
    direct = client.get(paths[0], headers=headers)
    assert direct.headers["cache-control"] == "private, no-store"
    assert direct.headers["content-security-policy"].startswith("sandbox;")
    assert direct.headers["x-content-type-options"] == "nosniff"
    assert client.head(paths[0], headers=headers).status_code == 200
    auth.update_user(user.id, {"is_active": False})
    assert client.get(paths[0], headers=headers).status_code == 403


def test_uploads_do_not_follow_outside_symlinks(private_files, tmp_path):
    client, storage = private_files
    secret = tmp_path / "outside.txt"
    secret.write_text("Must not be served", encoding="utf-8")
    create_symlink(storage.base_dir / "linked.txt", secret)
    user = auth.register_user("reader", "reader@example.com", "Reader", "Strong123", "readonly")
    headers = {"Authorization": f"Bearer {auth.create_access_token(user.id)}"}
    assert client.get("/uploads/linked.txt", headers=headers).status_code == 404
    assert client.get("/api/v1/files/download?key=linked.txt", headers=headers).status_code == 404
    assert client.get("/api/v1/files/download?key=documents", headers=headers).status_code == 404


def test_protected_pdf_download_returns_attachment_with_pdf_mime_and_original_bytes(private_files):
    client, storage = private_files
    content = b"%PDF-1.4\nPrivate PDF bytes"
    storage.save("documents/verified.pdf", BytesIO(content), content_type="application/pdf")
    user = auth.register_user("pdfreader", "pdfreader@example.com", "Reader", "Strong123", "readonly")
    response = client.get("/api/v1/files/download?key=documents%2Fverified.pdf", headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"})
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="verified.pdf"'
    assert response.headers["x-content-type-options"] == "nosniff"


def create_symlink(link: Path, target: Path):
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"This operating system does not allow creating symlinks: {exc}")


@pytest.fixture
def frontend_client(tmp_path):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("Frontend", encoding="utf-8")
    (root / "public.txt").write_text("Public asset", encoding="utf-8")
    (tmp_path / "private.txt").write_text("Private data", encoding="utf-8")
    frontend = FastAPI()

    @frontend.get("/{full_path:path}")
    def spa(full_path: str):
        return frontend_response(root, full_path)

    return TestClient(frontend), root


@pytest.mark.parametrize("escaped_path", ["../private.txt", "..\\private.txt", "C:\\private.txt", "C:/private.txt", "/private.txt", "\\\\server\\share\\private.txt"])
def test_frontend_rejects_parent_absolute_drive_and_backslash_paths(frontend_client, escaped_path):
    _, root = frontend_client
    with pytest.raises(HTTPException) as exc:
        frontend_file(root, escaped_path)
    assert exc.value.status_code == 404


@pytest.mark.parametrize("path", ["/..%5cprivate.txt", "/%2e%2e%2fprivate.txt", "/C:%5cprivate.txt", "/C:%2fprivate.txt", "/%5c%5cserver%5cshare%5cprivate.txt", "/%2fprivate.txt"])
def test_frontend_http_rejects_encoded_escapes(frontend_client, path):
    client, _ = frontend_client
    response = client.get(path)
    assert response.status_code == 404
    assert "Private data" not in response.text


def test_frontend_serves_assets_and_spa_without_following_private_symlinks(frontend_client):
    client, root = frontend_client
    assert client.get("/public.txt").text == "Public asset"
    assert client.get("/dashboard").text == "Frontend"
    create_symlink(root / "linked.txt", root.parent / "private.txt")
    assert client.get("/linked.txt").status_code == 404
    (root / "index.html").unlink()
    create_symlink(root / "index.html", root.parent / "private.txt")
    assert client.get("/dashboard").status_code == 404
