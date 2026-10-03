"""Real server execution of private Unicode/search/user-choice boundaries."""

import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import scoped_session, sessionmaker

from backend import auth, dependencies
from backend.app import app
from backend.models import PortfolioCreate, PropertyCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.portfolio_scope import scope_context
from backend.tests.test_contract_lifecycle_postgres import postgres as _postgres
from backend.tests.test_workflow_references import PREFIX, insert_properties

postgres = _postgres
original_get_user_by_id = auth.get_user_by_id


@pytest.fixture
def postgres_http(postgres, monkeypatch):
    factory = sessionmaker(bind=postgres.engine)
    registry = scoped_session(factory, scopefunc=dependencies.session_scope_key)
    store = SQLAlchemyStore(registry)
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    monkeypatch.setattr(auth, "get_user_by_id", original_get_user_by_id)
    monkeypatch.setattr(dependencies, "store", store)
    monkeypatch.setattr(dependencies, "_scoped_session", registry)
    for name, module in tuple(sys.modules.items()):
        if name.startswith("backend.routers") and hasattr(module, "store"):
            monkeypatch.setattr(module, "store", store)
    with scope_context(None):
        other_portfolio = store.create_portfolio(PortfolioCreate(name="Other private portfolio"))
        other_property = store.create_property(PropertyCreate(name="OTHER_PRIVATE_PROPERTY", property_type="residential", portfolio_id=other_portfolio.id))
        owner = auth.register_user("owner-pg-reference", "owner-pg-reference@example.test", "Owner", "StrongPass123!", "eigentuemer")
        actor = auth.register_user("manager-pg-reference", "manager-pg-reference@example.test", "Manager", "StrongPass123!", "verwalter",
                                  portfolio_access="selected", portfolio_ids=[postgres.p.id])
    headers = {"Authorization": "Bearer " + auth.create_access_token(actor.id)}
    owner_headers = {"Authorization": "Bearer " + auth.create_access_token(owner.id)}
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            yield client, store, headers, owner_headers, actor, other_portfolio, other_property
    finally:
        registry.remove()


def test_pg_late_unicode_literal_choice_is_bounded_and_scoped(postgres, postgres_http):
    client, store, headers, _, _, _, other_property = postgres_http
    with scope_context(None):
        insert_properties(store, postgres.property, 10003)
    statements = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and "FROM properties" in statement and "translate(" in statement:
            statements.append((statement, parameters))

    event.listen(postgres.engine, "before_cursor_execute", capture)
    try:
        result = client.get(PREFIX + "properties", headers=headers, params={"search": "STRASSE_% ÄLTESTE", "page_size": 7})
    finally:
        event.remove(postgres.engine, "before_cursor_execute", capture)
    assert result.status_code == 200, result.text
    assert [row["id"] for row in result.json()["items"]] == ["choice-00000"]
    assert result.json()["has_more"] is False
    assert len(statements) == 1 and "LIMIT" in statements[0][0] and "COUNT(" not in statements[0][0]
    assert other_property.id not in client.get(PREFIX + "properties", headers=headers).text


def test_pg_assignment_choice_never_exports_accounts_and_loses_revoked_candidates(postgres, postgres_http, monkeypatch):
    client, _, headers, owner_headers, _, other_portfolio, _ = postgres_http
    matching = auth.register_user("tech-pg-reference", "tech-pg-reference@example.test", "Straße_% Technician", "StrongPass123!", "techniker",
                                  portfolio_access="selected", portfolio_ids=[postgres.p.id])
    other = auth.register_user("other-tech-pg-reference", "other-tech-pg-reference@example.test", "Other", "StrongPass123!", "techniker",
                               portfolio_access="selected", portfolio_ids=[other_portfolio.id])
    monkeypatch.setattr(auth._user_store, "list_all", lambda: pytest.fail("unbounded account export"))
    params = {"property_id": postgres.property.id, "search": "STRASSE_%"}
    result = client.get(PREFIX + "users", headers=headers, params=params)
    assert result.status_code == 200, result.text
    assert result.json()["items"] == [{"id": matching.id, "full_name": matching.full_name, "role": matching.role}]
    assert other.id not in result.text and "example.test" not in result.text
    changed = client.patch(f"/api/v1/auth/users/{matching.id}", headers=owner_headers,
                           json={"portfolio_access": "selected", "portfolio_ids": [other_portfolio.id]})
    assert changed.status_code == 200, changed.text
    assert client.get(PREFIX + "users", headers=headers, params=params).json()["items"] == []
