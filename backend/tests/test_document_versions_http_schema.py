"""Real JWT/scope middleware and fresh Alembic schema, without private data."""

import pytest
from alembic import command as migration
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from backend import auth, dependencies
from backend.db.document_version_models import DOCUMENT_VERSION_MODELS, ensure_document_version_schema
from backend.routers.document_versions import router
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.tests import test_billing_migration_guards as migration_tests
from backend.tests.test_document_versions import active as active

migration_database = migration_tests.migration_database


@pytest.mark.parametrize("role", ["verwalter", "readonly", "buchhaltung", "techniker"])
def test_actual_auth_scope_upload_download_and_revoked_rights(active, monkeypatch, role):
    box = active
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    monkeypatch.setattr(auth, "get_user_by_id", auth._user_store.get_by_id)
    monkeypatch.setattr(dependencies, "store", box.store)
    user = auth.register_user("version-member", "member@example.test", "Synthetic", "Strong123", role,
        portfolio_access="selected", portfolio_ids=[box.p.id])
    foreign = auth.register_user("version-foreign", "foreign@example.test", "Synthetic foreign", "Strong123", "verwalter",
        portfolio_access="selected", portfolio_ids=[box.foreign.id])
    headers = {"Authorization": "Bearer " + auth.create_access_token(user.id)}
    other = {"Authorization": "Bearer " + auth.create_access_token(foreign.id)}
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    base = "/api/v1/documents/" + box.document.id
    with TestClient(PortfolioScopeMiddleware(app)) as client:
        assert client.get(base + "/versions").status_code == 401
        assert client.get(base + "/versions", headers=other).status_code == 404
        history = client.get(base + "/versions", headers=headers).json()
        preview = client.get(base + "/version-source", headers=headers).json()
        payload = {"idempotency_key": "original-http", "expected_document_etag": history["document_etag"],
            "expected_head_id": None, "expected_sha256": preview["sha256"], "comment": "Reviewed original", "confirmed": True}
        response = client.post(base + "/versions/archive-original", json=payload, headers=headers)
        if role == "readonly":
            assert response.status_code == 403
            assert client.get(base + "/versions", headers=headers).json()["head"] is None
            return
        assert response.status_code == 201, response.text
        original = response.json()
        assert client.post(base + "/versions/archive-original", json=payload, headers=headers).json() == original
        download = client.get("/api/v1" + original["download_url"], headers=headers)
        assert download.status_code == 200 and download.content == box.content
        assert download.headers["x-content-sha256"] == preview["sha256"]
        assert "no-store" in download.headers["cache-control"]
        assert client.get("/api/v1" + original["download_url"], headers=other).status_code == 404
        import json
        payload.pop("expected_sha256")
        payload.update(idempotency_key="new-http", expected_head_id=original["id"], comment="New reviewed version")
        result = client.post(base + "/versions", headers=headers,
            data={"command": json.dumps(payload)}, files={"file": ("new.txt", b"New HTTP version", "text/plain")})
        assert result.status_code == 201, result.text
        assert result.json()["predecessor_id"] == original["id"]
        auth._user_store.update(user.id, {"portfolio_access": "selected", "portfolio_ids": []})
        assert client.get(base + "/versions", headers=headers).status_code == 404
        assert client.get("/api/v1" + original["download_url"], headers=headers).status_code == 404


def test_fresh_y1_schema_repeatable_bootstrap_empty_roundtrip_and_populated_guard(migration_database):
    config, path = migration_database
    directory = ScriptDirectory.from_config(config)
    assert directory.get_revision("y1a2b3c4d5e6").down_revision == "x1a2b3c4d5e6"
    migration.upgrade(config, "y1a2b3c4d5e6")
    engine = create_engine("sqlite:///" + path.as_posix())
    try:
        for model in DOCUMENT_VERSION_MODELS:
            assert {c["name"] for c in inspect(engine).get_columns(model.__tablename__)} == set(model.__table__.c.keys())
            assert inspect(engine).get_foreign_keys(model.__tablename__)
        before = migration_tests._structure(path)
        with engine.begin() as connection:
            ensure_document_version_schema(connection)
            ensure_document_version_schema(connection)
        assert migration_tests._structure(path) == before
        migration.downgrade(config, "x1a2b3c4d5e6")
        migration.upgrade(config, "y1a2b3c4d5e6")
        assert migration_tests._structure(path) == before
        # Owned synthetic corruption still cannot be erased by downgrade.
        with engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO document_versions (id,document_id,portfolio_id,property_id,number,actor_id,idempotency_key,"
                "request_sha256,operation,comment,filename,media_type,sha256,size_bytes,metadata_snapshot,created_at) VALUES "
                "('proof','synthetic-doc','synthetic-portfolio','synthetic-property',1,'actor','key','hash','archive_original','proof',"
                "'proof.txt','text/plain','hash',0,'{}','2026-10-01 00:00:00')")
        with pytest.raises(RuntimeError, match="Document originals exist"):
            migration.downgrade(config, "x1a2b3c4d5e6")
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT id FROM document_versions").scalar() == "proof"
    finally:
        engine.dispose()
