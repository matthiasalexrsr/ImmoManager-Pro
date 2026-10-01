"""Actual authenticated routes and complete-download failure cleanup."""

import io
from zipfile import ZipFile

import anyio
import pytest
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from backend import auth, dependencies
from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.routers import datev
from backend.services import datev_export as service
from backend.services import portfolio_scope
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.tests.test_datev_export import active as active  # noqa: F401 fixture
from backend.tests.test_datev_export import booking, command, insert, preview


def test_real_scoped_http_token_cannot_read_foreign_or_revoked_export(active, monkeypatch):
    store, engine = active
    monkeypatch.setattr(datev, "store", store)
    monkeypatch.setattr(dependencies, "store", store)
    monkeypatch.setattr(service, "scope_helpers", lambda: portfolio_scope)
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    insert(engine, [booking()])
    member = register_user("scoped-datev", "scoped@example.com", "Synthetic scoped", "Strong123",
        "buchhaltung", portfolio_access="selected", portfolio_ids=["p"])
    headers = {"Authorization": f"Bearer {create_access_token(member.id)}"}
    with TestClient(PortfolioScopeMiddleware(app)) as client:
        foreign = client.get("/api/v1/reports/datev/profiles?portfolio_id=foreign", headers=headers)
        assert foreign.status_code == 404
        saved = client.post("/api/v1/reports/datev/profiles", json=command().model_dump(mode="json"), headers=headers)
        assert saved.status_code == 201, saved.text
        created = client.post("/api/v1/reports/datev/preview", json=preview(saved.json()).model_dump(mode="json"), headers=headers)
        assert created.status_code == 201, created.text
        path = f"/api/v1/reports/datev/exports/{created.json()['id']}/download"
        assert client.get(path, headers=headers).status_code == 200
        auth.update_user(member.id, {"portfolio_access": "selected", "portfolio_ids": []})
        denied = client.get(path, headers=headers)
        assert denied.status_code == 404 and "content-disposition" not in denied.headers
        assert client.get("/api/v1/reports/datev/exports?portfolio_id=p", headers=headers).status_code == 404


@pytest.mark.parametrize("role", ["eigentuemer", "verwalter", "buchhaltung", "readonly", "techniker"])
def test_routes_require_auth_and_finance_writes_and_return_verified_complete_file(active, role, monkeypatch):
    store, engine = active
    monkeypatch.setattr(datev, "store", store)
    insert(engine, [booking()])
    clear_users()
    try:
        user = register_user("synthetic-datev", "datev@example.com", "Synthetic DATEV", "Strong123", role)
        headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
        with TestClient(app) as client:
            assert client.post("/api/v1/reports/datev/profiles", json=command().model_dump(mode="json")).status_code == 401
            response = client.post("/api/v1/reports/datev/profiles", json=command().model_dump(mode="json"), headers=headers)
            if role in {"readonly", "techniker"}:
                assert response.status_code == 403 and service.list_profiles(store, "p")["total"] == 0
                return
            assert response.status_code == 201, response.text
            version = response.json()
            assert version["actor_id"] == user.id
            result = client.post("/api/v1/reports/datev/preview", json=preview(version).model_dump(mode="json"), headers=headers)
            assert result.status_code == 201, result.text
            receipt = result.json()
            file = client.get(f"/api/v1/reports/datev/exports/{receipt['id']}/download", headers=headers)
            assert file.status_code == 200 and file.headers["content-type"] == "application/zip"
            assert len(file.content) == receipt["size"]
            assert file.headers["x-content-sha256"] == receipt["sha256"]
            with ZipFile(io.BytesIO(file.content)) as archive:
                assert len(archive.read(receipt["files"][0]["name"]).splitlines()) == 3
            assert client.get("/api/v1/reports/datev-export", headers=headers).status_code == 410
            assert client.get("/api/v1/reports/datev/exports/missing/download", headers=headers).status_code == 404
    finally:
        clear_users()


def test_error_very_late_in_build_is_an_error_response_not_a_zip(active, monkeypatch):
    store, engine = active
    monkeypatch.setattr(datev, "store", store)
    version = service.create_profile(store, command(), "actor")
    insert(engine, [booking(n) for n in range(1001)] + [{**booking(1001), "payment_text": "Invalid 🏠"}])
    clear_users()
    try:
        user = register_user("synthetic-datev", "datev@example.com", "Synthetic", "Strong123", "buchhaltung")
        with TestClient(app) as client:
            result = client.post("/api/v1/reports/datev/preview", json=preview(version).model_dump(mode="json"),
                                headers={"Authorization": f"Bearer {create_access_token(user.id)}"})
            assert result.status_code == 422 and "b-00001001" in result.text
            assert "content-disposition" not in result.headers and result.headers["content-type"] == "application/json"
            assert service.list_exports(store, "p")["total"] == 0
    finally:
        clear_users()


@pytest.mark.parametrize("fail_on_body", [False, True])
def test_disconnect_even_before_first_file_chunk_removes_owned_private_workspace(active, fail_on_body):
    store, engine = active
    version = service.create_profile(store, command(), "actor")
    insert(engine, [booking()])
    reference = service.create_preview(store, preview(version), "actor")
    compiled = service.prepare_saved_download(store, reference["id"])
    directory = compiled.path.parent
    response = datev.PrivateDownloadResponse(compiled, None, media_type="application/zip")
    async def disconnected():
        async def send(message):
            assert directory.exists()
            if message["type"] == ("http.response.body" if fail_on_body else "http.response.start"):
                raise OSError("Synthetic closed connection")
        async def receive():
            return {"type": "http.disconnect"}
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    with pytest.raises((OSError, ClientDisconnect)):
        anyio.run(disconnected)
    assert not directory.exists()
