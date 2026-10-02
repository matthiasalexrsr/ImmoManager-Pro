"""Authenticated HTTP boundaries and independent SQL/Memory snapshot races."""

import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from zipfile import ZipFile

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import auth
from backend.db.tax_models import AnnualTaxProjectionORM, AnnualTaxSourceORM
from backend.models import AccountCreate, CategoryCreate, PortfolioCreate, PropertyCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import annual_tax
from backend.services import annual_tax_storage as service
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.storage import NotFoundError
from backend.tests.test_annual_tax_projection import booking, preflight_command, profile_command, save_command
from backend.tests.test_annual_tax_projection import tax_store as tax_store  # noqa: F401 fixture


@pytest.fixture
def tax_http(tax_store, monkeypatch):
    store, *_ = tax_store
    monkeypatch.setattr(annual_tax, "store", store)
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    app = FastAPI()
    app.include_router(annual_tax.router, prefix="/api/v1", dependencies=[Depends(auth.require_auth)])

    @app.exception_handler(NotFoundError)
    async def missing(_, exception):
        return JSONResponse(status_code=404, content={"detail": str(exception)})

    with TestClient(PortfolioScopeMiddleware(app)) as client:
        yield client


def headers(role, portfolio_id):
    user = auth.register_user(role, role + "@example.test", "Synthetic tax reviewer", "Synthetic tax passphrase 123", role,
        portfolio_access="selected", portfolio_ids=[portfolio_id])
    return user, {"Authorization": "Bearer " + auth.create_access_token(user.id)}


@pytest.mark.parametrize("role", ["eigentuemer", "verwalter", "buchhaltung", "techniker", "readonly"])
def test_http_finance_capability_and_verified_download(tax_store, tax_http, role):
    store, _, portfolio, *_ = tax_store
    booking(tax_store, 12.34)
    client = tax_http
    _, token = headers(role, portfolio.id)
    url = "/api/v1/reports/annual-tax"
    assert client.get(url + "/options", params={"portfolio_id": portfolio.id}).status_code == 401
    version = service.create_profile(store, profile_command(tax_store), "owner")
    command = preflight_command(version)
    snapshot = service.create_projection(store, save_command(command, service.preflight(store, command)), "owner")
    assert client.get(url + "/profiles", params={"portfolio_id": portfolio.id}, headers=token).json()["total"] == 1
    denied = role in {"readonly", "techniker"}
    profile = client.post(url + "/profiles", json=profile_command(tax_store, idempotency_key="http").model_dump(mode="json"), headers=token)
    preview = client.post(url + "/preflight", json=command.model_dump(mode="json"), headers=token)
    assert profile.status_code == (403 if denied else 201), profile.text
    assert preview.status_code == (403 if denied else 200), preview.text
    file = client.get(url + f"/projections/{snapshot['id']}/download", headers=token)
    assert file.status_code == 200, file.text
    assert file.headers["x-content-sha256"] == hashlib.sha256(file.content).hexdigest()
    with ZipFile(io.BytesIO(file.content)) as archive:
        assert len(archive.read("sources.jsonl").splitlines()) == 1
        assert b"1234" in archive.read("cash-evidence.csv")


def test_old_token_two_http_sessions_cannot_read_or_reference_foreign_or_revoked_tax_sources(tax_store, tax_http):
    store, _, portfolio, properties, accounts, categories = tax_store
    own = booking(tax_store, 100)
    foreign = store.create_portfolio(PortfolioCreate(name="Foreign private portfolio"))
    foreign_account = store.create_account(AccountCreate(portfolio_id=foreign.id, name="Foreign", account_type="bank"))
    foreign_category = store.create_category(CategoryCreate(portfolio_id=foreign.id, name="Foreign", category_type="income"))
    foreign_property = store.create_property(PropertyCreate(portfolio_id=foreign.id, name="Foreign", property_type="residential"))
    user, token = headers("buchhaltung", portfolio.id)
    path = "/api/v1/reports/annual-tax"
    version = service.create_profile(store, profile_command(tax_store), "owner")
    command = preflight_command(version)
    snapshot = service.create_projection(store, save_command(command, service.preflight(store, command)), "owner")
    second = TestClient(tax_http.app)
    try:
        assert second.get(path + f"/projections/{snapshot['id']}", headers=token).status_code == 200
        assert tax_http.get(path + "/options", params={"portfolio_id": foreign.id}, headers=token).status_code == 404
        for changed in (dict(account_id=foreign_account.id), dict(category_id=foreign_category.id)):
            rule = dict(account_id=accounts[0].id, category_id=categories[0].id, treatment="income", form_line="Reviewed line", reason="Explicit") | changed
            invalid = profile_command(tax_store, rules=[rule])
            assert tax_http.post(path + "/profiles", headers=token, json=invalid.model_dump(mode="json")).status_code == 404
        invalid = preflight_command(version, overrides=[dict(booking_id=own.id, reason="Foreign property bypass",
            parts=[dict(property_id=foreign_property.id, amount_cents="10000", treatment="income", form_line="Line", reason="Explicit")])])
        assert tax_http.post(path + "/preflight", headers=token, json=invalid.model_dump(mode="json")).status_code == 404
        auth.update_user(user.id, {"portfolio_access": "selected", "portfolio_ids": []})
        for suffix in (f"/projections/{snapshot['id']}", f"/projections/{snapshot['id']}/download", "/profiles?portfolio_id=" + portfolio.id):
            response = second.get(path + suffix, headers=token)
            assert response.status_code == 404, response.text
            assert "content-disposition" not in response.headers
    finally:
        second.close()


def test_captured_scope_revocation_before_publication_rolls_back(tax_store, monkeypatch):
    store, _, portfolio, *_ = tax_store
    booking(tax_store, 100)
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    user, _ = headers("buchhaltung", portfolio.id)
    version = service.create_profile(store, profile_command(tax_store), "owner")
    command = preflight_command(version)
    checked = service.preflight(store, command)
    original = service.compile_projection
    def revoke(*args, **kwargs):
        compiled = original(*args, **kwargs)
        auth.update_user(user.id, {"portfolio_access": "selected", "portfolio_ids": []})
        return compiled
    monkeypatch.setattr(service, "compile_projection", revoke)
    with scope_context(scope_from_user(auth.get_user_by_id(user.id))), pytest.raises(HTTPException) as error:
        service.create_projection(store, save_command(command, checked), user.id)
    assert error.value.status_code == 403
    assert service.list_projections(store, portfolio.id)["total"] == 0
    if hasattr(store, "db"):
        assert store.db.scalar(select(func.count()).select_from(AnnualTaxSourceORM)) == 0


@pytest.mark.parametrize("same_idempotency", [True, False])
def test_independent_writers_cannot_create_duplicate_annual_obligations(tax_store, monkeypatch, same_idempotency):
    store, engine, portfolio, *_ = tax_store
    booking(tax_store, 100)
    version = service.create_profile(store, profile_command(tax_store), "owner")
    command = preflight_command(version)
    checked = service.preflight(store, command)
    barrier = Barrier(2)
    original = service.compile_projection
    def simultaneous(*args, **kwargs):
        compiled = original(*args, **kwargs)
        barrier.wait(timeout=20)
        return compiled
    monkeypatch.setattr(service, "compile_projection", simultaneous)
    def save(index):
        db = Session(engine) if hasattr(store, "db") else None
        try:
            target = SQLAlchemyStore(db) if db is not None else store
            saved = service.create_projection(target, save_command(command, checked, idempotency_key="replay" if same_idempotency else str(index)), "owner")
            return 201, saved["id"]
        except HTTPException as error:
            return error.status_code, None
        finally:
            if db is not None:
                db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(save, range(2)))
    assert sorted(status for status, _ in result) == ([201, 201] if same_idempotency else [201, 409])
    assert len({identifier for _, identifier in result if identifier}) == 1
    assert service.list_projections(store, portfolio.id)["total"] == 1
    if hasattr(store, "db"):
        assert store.db.scalar(select(func.count()).select_from(AnnualTaxProjectionORM)) == 1
        assert store.db.scalar(select(func.count()).select_from(AnnualTaxSourceORM)) == 1
