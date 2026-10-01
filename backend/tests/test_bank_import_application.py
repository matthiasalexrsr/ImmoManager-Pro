"""Application integration: preservation failures stay repairable before any mutation."""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend import auth
from backend.exceptions import register_exception_handlers
from backend.models import PortfolioCreate
from backend.routers import accounts, admin, data_exchange, portfolios
from backend.routers.bank_imports import router as bank_router
from backend.services.bank_import import BankImportError, get_import
from backend.services.data_transfer import _staged_memory, import_store_data
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.services.portfolio_scope import scope_context
from backend.tests.test_bank_imports_http import (
    bank_http,  # noqa: F401 fixture
    upload,
)


@pytest.fixture
def application(bank_http, monkeypatch, tmp_path):  # noqa: F811
    _, store, owner, finance, _, _, bank_accounts, _, _ = bank_http
    monkeypatch.setattr(accounts, "store", store)
    monkeypatch.setattr(admin, "store", store)
    monkeypatch.setattr(portfolios, "store", store)
    app = FastAPI()
    register_exception_handlers(app)
    dependencies = [Depends(auth.require_auth)]
    for router in (accounts.router, admin.router, data_exchange.router, portfolios.router, bank_router):
        app.include_router(router, prefix="/api/v1", dependencies=dependencies)

    @app.post("/api/v1/test-business-backup", dependencies=dependencies)
    def backup():
        return admin._create_json_backup(tmp_path / "business-backups")

    with TestClient(PortfolioScopeMiddleware(app)) as client:
        response = upload(client, bank_accounts[0].id, owner)
        assert response.status_code == 201
        yield client, store, owner, finance, bank_accounts, response.json(), tmp_path


@pytest.mark.parametrize("path", ["/admin/export", "/data/export", "/test-business-backup"])
def test_business_subset_cannot_masquerade_as_full_bank_backup(application, path):
    client, store, owner, _, _, job, directory = application
    response = client.request("POST" if path == "/test-business-backup" else "GET", "/api/v1" + path, headers=owner)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "BANK_IMPORT_HISTORY_PRESENT"
    assert error["recovery"] == "preserve_history_or_full_recovery"
    assert error["request_id"]
    assert not (directory / "business-backups").exists()
    with scope_context(None):
        assert get_import(store, job["id"])["source_sha256"] == job["source_sha256"]


def test_account_deletion_is_scoped_before_preservation_guard_and_keeps_source(application):
    client, store, owner, finance, bank_accounts, job, _ = application
    foreign = client.delete(f"/api/v1/accounts/{bank_accounts[1].id}", headers=finance)
    assert foreign.status_code == 404
    assert "BANK_ACCOUNT_IMPORT_HISTORY" not in foreign.text
    response = client.delete(f"/api/v1/accounts/{bank_accounts[0].id}", headers=owner)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BANK_ACCOUNT_IMPORT_HISTORY"
    with scope_context(None):
        assert store.get_account(bank_accounts[0].id).id == bank_accounts[0].id
        assert get_import(store, job["id"])["source_sha256"] == job["source_sha256"]


def test_ordinary_reset_refuses_before_touching_bank_source_or_account(application):
    _, store, _, _, bank_accounts, job, _ = application
    with scope_context(None), pytest.raises(BankImportError) as refusal:
        store.clear_all()
    assert refusal.value.code == "BANK_IMPORT_HISTORY_PRESENT"
    with scope_context(None):
        assert store.get_account(bank_accounts[0].id).id == bank_accounts[0].id
        assert get_import(store, job["id"])["source_sha256"] == job["source_sha256"]


def test_portfolio_cascade_is_repairable_and_additive_business_merge_keeps_bank_history(application):
    client, store, owner, _, bank_accounts, job, _ = application
    response = client.delete(f"/api/v1/portfolios/{bank_accounts[0].portfolio_id}", headers=owner)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BANK_PORTFOLIO_IMPORT_HISTORY"
    with scope_context(None):
        before = {row.id for row in store.list_portfolios()}
        result = import_store_data(store, {"portfolios": [{"id": "synthetic-new", "name": "Added business portfolio"}]}, replace_existing=False)
        assert result["imported"]["portfolios"] == 1
        assert len(store.list_portfolios()) == len(before) + 1
        assert get_import(store, job["id"])["source_sha256"] == job["source_sha256"]
        with pytest.raises(BankImportError):
            import_store_data(store, {"portfolios": []}, replace_existing=True)
        assert store.get_account(bank_accounts[0].id).id == bank_accounts[0].id


def test_memory_business_staging_retains_engine_and_independent_rollback_comparison(application):
    _, store, _, _, _, job, _ = application
    if hasattr(store, "db"):
        pytest.skip("Memory engine-copy integration; SQL uses an independent transaction")
    engine = store._bank_import_engine
    with scope_context(None):
        before = {row.id for row in store.list_portfolios()}
        with pytest.raises(RuntimeError, match="synthetic rollback"):
            with _staged_memory(store) as staged:
                staged.create_portfolio(PortfolioCreate(name="Unpublished synthetic portfolio"))
                raise RuntimeError("synthetic rollback")
        assert {row.id for row in store.list_portfolios()} == before
        with _staged_memory(store) as staged:
            created = staged.create_portfolio(PortfolioCreate(name="Committed synthetic portfolio"))
        assert store.get_portfolio(created.id).name == "Committed synthetic portfolio"
        assert store._bank_import_engine is engine
        assert get_import(store, job["id"])["source_sha256"] == job["source_sha256"]
