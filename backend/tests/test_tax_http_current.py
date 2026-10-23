"""Real routes and current token/scope contracts for retained tax exports."""
import hashlib

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend import auth
from backend.routers import annual_tax, datev
from backend.services import annual_tax_storage as annual
from backend.services import datev_export as service
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.storage import NotFoundError
from backend.tests.test_annual_tax_projection import booking, preflight_command, profile_command
from backend.tests.test_annual_tax_projection import tax_store as tax_store
from backend.tests.test_tax_current_contracts import datev_profile, datev_request


@pytest.fixture
def client(tax_store, monkeypatch):
    monkeypatch.setattr(datev, "store", tax_store[0])
    monkeypatch.setattr(annual_tax, "store", tax_store[0])
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    app = FastAPI()
    for router in (datev.router, annual_tax.router):
        app.include_router(router, prefix="/api/v1", dependencies=[Depends(auth.require_auth)])

    @app.exception_handler(NotFoundError)
    async def missing(_, error):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    with TestClient(PortfolioScopeMiddleware(app)) as result:
        yield result


def token(portfolio, role="buchhaltung"):
    user = auth.register_user(role, role + "@synthetic.test", "Synthetic reviewer", "Synthetic tax passphrase 123", role,
        portfolio_access="selected", portfolio_ids=[portfolio.id])
    return user, {"Authorization": "Bearer " + auth.create_access_token(user.id)}


def test_datev_real_scoped_routes_replay_download_and_revocation(tax_store, client):
    store, _, portfolio, *_ = tax_store
    booking(tax_store, 10.01, payment_text="Miete äöü")
    user, headers = token(portfolio)
    root = "/api/v1/reports/datev"
    assert client.get(root + "/profiles", params={"portfolio_id": portfolio.id}).status_code == 401
    result = client.post(root + "/profiles", json=datev_profile(tax_store).model_dump(mode="json"), headers=headers)
    assert result.status_code == 201, result.text
    command = datev_request(result.json()).model_dump(mode="json")
    result = client.post(root + "/preview", json=command, headers=headers)
    assert result.status_code == 201, result.text
    receipt = result.json()
    assert client.post(root + "/preview", json=command, headers=headers).json() == receipt
    downloaded = client.get(root + f"/exports/{receipt['id']}/download", headers=headers)
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.content).hexdigest() == receipt["sha256"]
    assert service.list_exports(store, portfolio.id)["total"] == 1
    auth.update_user(user.id, {"portfolio_access": "selected", "portfolio_ids": []})
    denied = client.get(root + f"/exports/{receipt['id']}/download", headers=headers)
    assert denied.status_code == 404 and "content-disposition" not in denied.headers
    assert client.post(root + "/preview", json=command, headers=headers).status_code == 404


def test_datev_reader_cannot_create_profiles_or_exports(tax_store, client):
    store, _, portfolio, *_ = tax_store
    version = service.create_profile(store, datev_profile(tax_store), "internal")
    _, headers = token(portfolio, "readonly")
    root = "/api/v1/reports/datev"
    assert client.post(root + "/profiles", json=datev_profile(tax_store).model_dump(mode="json"), headers=headers).status_code == 403
    assert client.post(root + "/preview", json=datev_request(version).model_dump(mode="json"), headers=headers).status_code == 403


def test_annual_missing_source_pages_have_complete_counts_and_scope(tax_store, client):
    store, _, portfolio, *_ = tax_store
    for i in range(23):
        booking(tax_store, "0.01", payment_text=f"Quelle {i}", category=2)
    version = annual.create_profile(store, profile_command(tax_store), "internal")
    user, headers = token(portfolio)
    command = preflight_command(version).model_dump(mode="json")
    root = "/api/v1/reports/annual-tax"
    checked = client.post(root + "/preflight", json=command, headers=headers)
    assert checked.status_code == 200 and not checked.json()["ready"]
    first = client.post(root + "/source-page?offset=0&limit=20", json=command, headers=headers).json()
    last = client.post(root + "/source-page?offset=20&limit=20", json=command, headers=headers).json()
    assert first["total"] == last["total"] == 23 and len(first["items"]) == 20 and len(last["items"]) == 3
    assert first["preview_hash"] == last["preview_hash"] == checked.json()["preview_hash"]
    records = first["items"] + last["items"]
    assert len({item["booking"]["id"] for item in records}) == 23
    assert sum(int(item["booking"]["amount_cents"]) for item in records) == 23
    assert all(item["classification_state"] == "needs_review" for item in records)
    auth.update_user(user.id, {"portfolio_access": "selected", "portfolio_ids": []})
    assert client.post(root + "/source-page?offset=20&limit=20", json=command, headers=headers).status_code == 404
