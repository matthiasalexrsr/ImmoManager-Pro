"""Real HTTP boundaries for the installation-wide legacy integration manager."""

import inspect

import pytest
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.routers import integrations
from backend.services.integrations.config_store import InMemoryIntegrationConfigStore
from backend.services.integrations.history_store import SQLIntegrationHistoryStore
from backend.services.integrations.manager import IntegrationManager
from backend.tests.test_integration_history_core import journal_engine
from backend.tests.test_portfolio_access_http import access_http as _access_http

access_http = _access_http


@pytest.fixture
def private_manager(monkeypatch, tmp_path, access_http):
    if isinstance(auth._user_store, auth.SQLUserStore):
        factory = auth._user_store._session_factory
        from backend.db.integration_history_schema import install_history_guards

        with factory() as session, session.get_bind().begin() as connection:
            install_history_guards(connection)
        manager = IntegrationManager(InMemoryIntegrationConfigStore(), history_store=SQLIntegrationHistoryStore(factory))
        manager.seed_defaults()
        monkeypatch.setattr(integrations, "integration_manager", manager)
        yield manager
        return
    with journal_engine(tmp_path, "sqlite") as engine:
        manager = IntegrationManager(InMemoryIntegrationConfigStore(), history_store=SQLIntegrationHistoryStore(sessionmaker(engine)))
        manager.seed_defaults()
        monkeypatch.setattr(integrations, "integration_manager", manager)
        yield manager


def test_selected_manager_cannot_read_global_other_portfolio_source(access_http, private_manager):
    client, _, owner, member, *_ = access_http
    assert client.patch("/api/v1/integrations/contract-wizard", headers=owner,
                        json={"enabled": True}).status_code == 200
    private_value = "SYNTHETIC_OTHER_PORTFOLIO_TENANT"
    assert client.post("/api/v1/integrations/contract-wizard/run", headers=owner,
                       json={"payload": {"tenant_name": private_value, "property_name": "Other property"}}).status_code == 200
    owner_history = client.get("/api/v1/integrations/contract-wizard/history", headers=owner)
    assert owner_history.status_code == 200
    assert private_value in owner_history.text
    forbidden = client.get("/api/v1/integrations/contract-wizard/history", headers=member)
    assert forbidden.status_code == 403
    assert private_value not in forbidden.text


@pytest.mark.parametrize("role", ["readonly", "buchhaltung", "techniker"])
def test_nonadministrative_roles_cannot_read_global_config_or_history(access_http, private_manager, role):
    client, _, owner, *_ = access_http
    actor = auth.register_user("limited", "limited@example.test", "Limited", "StrongPass123!", role)
    headers = {"Authorization": "Bearer " + auth.create_access_token(actor.id)}
    private_value = "SYNTHETIC_PROVIDER_ACCOUNT_PRIVATE"
    assert client.put("/api/v1/integrations/whatsapp/config", headers=owner,
                      json={"config": {"unknown_field": private_value}}).status_code == 200
    for suffix in ("", "/status", "/metrics", "/whatsapp", "/whatsapp/schema", "/whatsapp/history"):
        result = client.get("/api/v1/integrations" + suffix, headers=headers)
        assert result.status_code == 403, suffix
        assert private_value not in result.text


def test_same_token_loses_integration_read_after_role_and_grant_change(access_http, private_manager):
    client, _, owner, _, _, portfolios, *_ = access_http
    actor = auth.register_user("globaladmin", "globaladmin@example.test", "Admin", "StrongPass123!", "verwalter")
    headers = {"Authorization": "Bearer " + auth.create_access_token(actor.id)}
    allowed = client.get("/api/v1/integrations/status", headers=headers)
    assert allowed.status_code == 200
    assert allowed.headers.get("cache-control") == "private, no-store"
    assert "authorization" in {part.strip().lower() for part in allowed.headers.get("vary", "").split(",")}
    changed = client.patch(f"/api/v1/auth/users/{actor.id}", headers=owner,
                           json={"portfolio_access": "selected", "portfolio_ids": [portfolios[0].id]})
    assert changed.status_code == 200, changed.text
    assert client.get("/api/v1/integrations/status", headers=headers).status_code == 403
    assert client.patch(f"/api/v1/auth/users/{actor.id}", headers=owner,
                        json={"portfolio_access": "all", "portfolio_ids": []}).status_code == 200
    assert client.get("/api/v1/integrations/status", headers=headers).status_code == 200
    assert client.patch(f"/api/v1/auth/users/{actor.id}", headers=owner,
                        json={"role": "readonly"}).status_code == 200
    assert client.get("/api/v1/integrations/status", headers=headers).status_code == 403


def test_grant_change_between_middleware_and_dependency_is_denied(access_http, private_manager, monkeypatch):
    client, *_ = access_http
    actor = auth.register_user("racingadmin", "racingadmin@example.test", "Admin", "StrongPass123!", "verwalter")
    headers = {"Authorization": "Bearer " + auth.create_access_token(actor.id)}
    private_manager.update_config("whatsapp", {"unknown_field": "SYNTHETIC_PRIVATE_RACING_SOURCE"})
    original = auth.get_user_by_id
    changed = False

    def revoke_before_dependency(user_id):
        nonlocal changed
        frame = inspect.currentframe()
        caller = frame.f_back if frame else None
        if user_id == actor.id and not changed and caller and caller.f_code.co_name == "get_current_user":
            changed = True
            auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
        return original(user_id)

    monkeypatch.setattr(auth, "get_user_by_id", revoke_before_dependency)
    result = client.get("/api/v1/integrations/whatsapp", headers=headers)
    assert changed
    assert result.status_code == 403, result.text
    assert "SYNTHETIC_PRIVATE_RACING_SOURCE" not in result.text


@pytest.mark.parametrize("change", ["portfolio", "role", "token"])
def test_private_response_is_fenced_before_publication(access_http, private_manager, monkeypatch, change):
    client, *_ = access_http
    actor = auth.register_user("publicationadmin", "publicationadmin@example.test", "Admin", "StrongPass123!", "verwalter")
    token = auth.create_access_token(actor.id)
    headers = {"Authorization": "Bearer " + token}
    private_manager.update_config("whatsapp", {"unknown_field": "SYNTHETIC_PRIVATE_PUBLICATION_SOURCE"})
    original = private_manager.get_integration

    def revoke_after_materialization(integration_id):
        result = original(integration_id)
        if change == "portfolio":
            auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
        elif change == "role":
            auth.update_user(actor.id, {"role": "readonly"})
        else:
            auth.revoke_token(token)
        return result

    monkeypatch.setattr(private_manager, "get_integration", revoke_after_materialization)
    result = client.get("/api/v1/integrations/whatsapp", headers=headers)
    assert result.status_code == (401 if change == "token" else 403), result.text
    assert "SYNTHETIC_PRIVATE_PUBLICATION_SOURCE" not in result.text
