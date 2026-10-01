"""Real JWT/portfolio middleware, additive bootstrap and complete Alembic chain."""

import pytest
from alembic import command as migration
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from backend import auth, dependencies
from backend.db.contract_wizard_models import WIZARD_MODELS, ensure_contract_wizard_schema
from backend.routers import contract_wizard, files
from backend.services import contract_wizard as service
from backend.services.contract_wizard_types import DraftCreate
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.tests import test_billing_migration_guards as migration_tests
from backend.tests.test_contract_wizard_workflow import active as active
from backend.tests.test_contract_wizard_workflow import data, prepare, publish

migration_database = migration_tests.migration_database


@pytest.mark.parametrize("role", ["verwalter", "readonly", "buchhaltung"])
def test_actual_authenticated_scoped_http_rejects_readonly_and_foreign_without_partial_objects(active, monkeypatch, role):
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    monkeypatch.setattr(auth, "get_user_by_id", auth._user_store.get_by_id)
    monkeypatch.setattr(dependencies, "store", active.store)
    user = auth.register_user("wizard-member", "member@example.test", "Synthetic", "Strong123", role,
        portfolio_access="selected", portfolio_ids=[active.p.id])
    headers = {"Authorization": "Bearer " + auth.create_access_token(user.id)}
    app = FastAPI()
    app.include_router(contract_wizard.router, prefix="/api/v1")
    app.include_router(files.router, prefix="/api/v1", dependencies=[Depends(auth.require_auth)])
    base = "/api/v1/contract-wizard"
    request = DraftCreate(idempotency_key="create-http", data=data(active)).model_dump(mode="json")
    with TestClient(PortfolioScopeMiddleware(app)) as client:
        assert client.post(base + "/drafts", json=request).status_code == 401
        assert client.get(base + "/choices/units?property_id=" + active.other.id, headers=headers).status_code == 404
        response = client.post(base + "/drafts", json=request, headers=headers)
        if role != "verwalter":
            assert response.status_code == 403 and active.store.list_contracts() == []
            return
        assert response.status_code == 201, response.text
        first = response.json()
        assert client.post(base + "/drafts", json=request, headers=headers).json() == first
        assert client.get(base + "/drafts", headers=headers).json()["items"][0]["id"] == first["id"]
        reviewed = client.post(base + "/drafts/" + first["id"] + "/review", headers=headers,
            json={"idempotency_key": "review-http", "expected_revision": first["revision"]}).json()
        large_request = DraftCreate(idempotency_key="capacity-http", data=data(active,
            deposit_amount="1E+1000", contract_number="Capacity-http")).model_dump(mode="json")
        large = client.post(base + "/drafts", headers=headers, json=large_request).json()
        capacity = client.post(base + "/drafts/" + large["id"] + "/review", headers=headers,
            json={"idempotency_key": "capacity-review", "expected_revision": large["revision"]})
        assert capacity.status_code == 422 and "NUMERIC(12,2)" in capacity.json()["detail"]
        assert client.get(base + "/drafts/" + large["id"], headers=headers).json()["state"] == "draft"
        response = client.post(base + "/drafts/" + first["id"] + "/publish", headers=headers,
            json=publish(reviewed).model_dump(mode="json"))
        assert response.status_code == 200, response.text
        pdf = client.get("/api/v1/files/download?key=contract-wizard/" + first["id"] + ".pdf", headers=headers)
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
        assert client.get("/api/v1/files/download?key=contract-wizard/arbitrary.pdf", headers=headers).status_code == 404
        assert client.get(base + "/drafts/" + first["id"] + "/pdf").status_code == 401
        auth._user_store.update(user.id, {"portfolio_access": "selected", "portfolio_ids": []})
        assert client.get(base + "/drafts/" + first["id"] + "/pdf", headers=headers).status_code == 404


def test_fresh_complete_alembic_head_matches_all_wizard_columns_and_repeatable_bootstrap(migration_database):
    config, path = migration_database
    directory = ScriptDirectory.from_config(config)
    assert directory.get_revision("v1a2b3c4d5e6").down_revision == "u1a2b3c4d5e6"
    migration.upgrade(config, "v1a2b3c4d5e6")
    engine = create_engine("sqlite:///" + path.as_posix())
    try:
        schema = inspect(engine)
        for model in WIZARD_MODELS:
            assert {c["name"] for c in schema.get_columns(model.__tablename__)} == set(model.__table__.c.keys())
            assert schema.get_foreign_keys(model.__tablename__)
        before = migration_tests._structure(path)
        with engine.begin() as connection:
            ensure_contract_wizard_schema(connection)
            ensure_contract_wizard_schema(connection)
        assert migration_tests._structure(path) == before
        migration.downgrade(config, "u1a2b3c4d5e6")
        migration.upgrade(config, "v1a2b3c4d5e6")
        assert migration_tests._structure(path) == before
    finally:
        engine.dispose()


def test_populated_downgrade_refuses_before_ddl(active, monkeypatch):
    if active.engine is None:
        pytest.skip("SQL-only retained schema evidence")
    from alembic import op

    from backend.db.migrations.versions import v1a2b3c4d5e6_reviewed_contract_workflow as version
    prepare(active)
    with active.engine.begin() as connection:
        monkeypatch.setattr(op, "get_bind", lambda: connection)
        with pytest.raises(RuntimeError, match="would erase"):
            version.downgrade()
        assert set(version.TABLES) <= set(inspect(connection).get_table_names())


def test_missing_local_attachment_preserves_review_and_adjustable_file_budget(active, monkeypatch):
    from datetime import date

    from backend.config import settings
    from backend.models import DocumentCreate
    from backend.storage import ValidationError
    document = active.store.create_document(DocumentCreate(property_id=active.property.id, title="Missing",
        document_type="other", document_date=date(2026, 10, 1), file_url="/uploads/missing.bin"))
    row = service.create_draft(active.store, DraftCreate(idempotency_key="missing", data=data(active, attachment_ids=[document.id])), "actor")
    operation = {"idempotency_key": "review-missing", "expected_revision": row["revision"]}
    from backend.services.contract_wizard_types import RevisionCommand
    with pytest.raises(ValidationError, match="nicht verfügbar"):
        service.review_draft(active.store, row["id"], RevisionCommand(**operation), "actor")
    payload = b"synthetic attachment"
    (active.storage.base_dir / "missing.bin").write_bytes(payload)
    monkeypatch.setattr(settings, "max_upload_size_bytes", len(payload) - 1)
    with pytest.raises(ValidationError, match="Budget anpassen"):
        service.review_draft(active.store, row["id"], RevisionCommand(**operation), "actor")
    assert service.get_draft(active.store, row["id"], "actor") == row
    monkeypatch.setattr(settings, "max_upload_size_bytes", len(payload))
    assert service.review_draft(active.store, row["id"], RevisionCommand(**operation), "actor")["state"] == "reviewed"
