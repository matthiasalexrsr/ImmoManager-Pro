"""Real HTTP credentials and database-backed accounts at publication boundaries."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend import auth, dependencies
from backend.routers import dashboard as router
from backend.services import auth_sessions
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.services.portfolio_scope import scope_context
from backend.tests.test_contract_workspace import active as active
from backend.tests.test_contract_workspace import seed


def client_for(store, portfolio_id, monkeypatch, *, mode="selected"):
    # Memory account assignment uses the central store, matching production's
    # shared account/router data source; SQL uses its own actual session.
    monkeypatch.setattr(dependencies, "store", store)
    accounts: auth.UserStore
    if hasattr(store, "db"):
        factory = sessionmaker(bind=store.db.get_bind())
        accounts = auth.SQLUserStore(factory)
    else:
        factory = None
        accounts = auth.InMemoryUserStore()
    monkeypatch.setattr(auth, "_user_store", accounts)
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    monkeypatch.setattr(auth, "get_user_by_id", accounts.get_by_id)
    monkeypatch.setattr(auth, "_token_blacklist", set())
    monkeypatch.setattr(auth, "_blacklist_expiry", {})
    accounts.create({"id": "dashboard-reader", "username": "dashboard-reader", "email": "reader@example.invalid",
        "full_name": "Synthetic Dashboard Reader", "hashed_password": "unused-synthetic-password-hash",
        "role": "readonly", "is_active": True, "portfolio_access": mode,
        "portfolio_ids": [portfolio_id] if mode == "selected" else []})
    tokens = auth_sessions.login_pair("dashboard-reader")
    monkeypatch.setattr(router, "store", store)
    app = FastAPI()
    app.include_router(router.router, prefix="/api/v1", dependencies=[Depends(auth.require_auth)])
    return TestClient(PortfolioScopeMiddleware(app)), accounts, tokens


@pytest.mark.parametrize("mode", ["selected", "all"])
@pytest.mark.parametrize("change", ["session", "role", "grants", "activation"])
def test_actual_credential_and_fresh_actor_are_checked_before_headers(active, monkeypatch, mode, change):
    contract, portfolio = seed(active)
    from backend.models import TaskCreate
    active.create_task(TaskCreate(title="PRIVATE-B1-HINT", property_id=contract.property_id))
    client, accounts, tokens = client_for(active, portfolio.id, monkeypatch, mode=mode)
    original = router.dashboard_summary

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        with scope_context(None):
            if change == "session":
                auth.revoke_token(tokens.access_token)
            elif change == "role":
                accounts.update("dashboard-reader", {"role": "verwalter"})
            elif change == "grants":
                accounts.update("dashboard-reader", {"portfolio_access": "selected", "portfolio_ids": []})
            else:
                accounts.update("dashboard-reader", {"is_active": False})
        return result

    monkeypatch.setattr(router, "dashboard_summary", changed)
    with client:
        response = client.get("/api/v1/dashboard/stats", headers={"Authorization": "Bearer " + tokens.access_token})
    assert response.status_code in {401, 403}, response.text
    assert "PRIVATE-B1-HINT" not in response.text
    assert "notification_count" not in response.text


def test_http_query_binding_bad_dates_and_real_same_family_rotation(active, monkeypatch):
    contract, portfolio = seed(active)
    from backend.models import TaskCreate
    for index in range(3):
        active.create_task(TaskCreate(title=f"Visible {index}", property_id=contract.property_id))
    client, _accounts, tokens = client_for(active, portfolio.id, monkeypatch)
    with client:
        assert client.get("/api/v1/dashboard/stats").status_code == 401
        headers = {"Authorization": "Bearer " + tokens.access_token}
        query = {"as_of": "2026-10-03", "preview_limit": 1}
        first = client.get("/api/v1/dashboard/stats", params=query, headers=headers)
        assert first.status_code == 200, first.text
        point = first.json()["work_hints"]["tasks"]["next_after"]
        assert point
        replacement = auth_sessions.rotate(tokens.refresh_token)
        continued = client.get("/api/v1/dashboard/stats", params=query | {"tasks_after": point},
            headers={"Authorization": "Bearer " + replacement.access_token})
        assert continued.status_code == 200, continued.text
        assert continued.json()["work_hints"]["tasks"]["total"] == 3
        for invalid in ({"preview_limit": 21}, {"as_of": "9999-12-31"},
                        {"preview_limit": 2, "tasks_after": point}, {"tasks_after": point + "x"}):
            response = client.get("/api/v1/dashboard/stats", params=query | invalid,
                headers={"Authorization": "Bearer " + replacement.access_token})
            assert response.status_code == 422, response.text
