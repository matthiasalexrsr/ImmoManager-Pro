"""Actual PostgreSQL keyword completeness, Unicode and current SQL account scope."""

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from backend import auth
from backend.models import ContactCreate
from backend.services import global_search
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.tests.test_global_search_pages import inventory
from backend.tests.test_housing_confirmation_postgres import postgres_housing as postgres_housing


def test_postgres_search_reaches_10001_with_bounded_source_projections(postgres_housing):
    box = postgres_housing
    _, rows = inventory(box.store, 10_001, name="PG findable", prefix="pg-search")
    statements = []

    def observe(_connection, _cursor, statement, *_args):
        if "FROM properties" in statement and statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(box.engine, "before_cursor_execute", observe)
    try:
        seen, after = [], None
        while True:
            result = global_search.page(box.store, "pg findable", limit=500, after=after)
            seen.extend(row["id"] for row in result["results"])
            after = result["next_after"]
            if not result["has_more"]:
                break
        assert seen == [row["id"] for row in reversed(rows)]
        assert len(set(seen)) == 10_001
        assert len(statements) == 21
        assert all("LIMIT" in statement and statement.split("FROM properties", 1)[0].strip()
                   == "SELECT properties.city, properties.id, properties.name" for statement in statements)
    finally:
        event.remove(box.engine, "before_cursor_execute", observe)


def test_postgres_search_unicode_literals_and_cross_source_pages(postgres_housing):
    store = postgres_housing.store
    _, rows = inventory(store, 2, name="Straße %_\\", prefix="pg-literal")
    person = store.create_contact(ContactCreate(first_name="Straße", last_name="%_\\"))
    one = global_search.page(store, "STRASSE %_\\", limit=2)
    assert [row["id"] for row in one["results"]] == [row["id"] for row in reversed(rows)]
    assert one["has_more"] is True
    two = global_search.page(store, "STRASSE %_\\", limit=2, after=one["next_after"])
    assert [(row["entity_type"], row["id"]) for row in two["results"]] == [("contact", person.id)]
    assert two["has_more"] is False
    assert global_search.page(store, "Saarbrücken")["count"] == 3


def test_postgres_search_revoked_sql_account_cannot_replay_cursor(postgres_housing):
    box = postgres_housing
    portfolio, _ = inventory(box.store, 3, name="Rights", prefix="pg-rights")
    accounts = auth._user_store
    accounts.update("actor", {"portfolio_ids": [portfolio.id]})
    captured = scope_from_user(accounts.get_by_id("actor"))
    with scope_context(captured):
        first = global_search.page(box.store, "Rights", limit=1)
        assert first["has_more"]
        accounts.update("actor", {"portfolio_ids": []})
        with pytest.raises(HTTPException) as revoked:
            global_search.page(box.store, "Rights", limit=1, after=first["next_after"])
        assert revoked.value.status_code == 403
    with scope_context(scope_from_user(accounts.get_by_id("actor"))):
        assert global_search.page(box.store, "Rights")["results"] == []
        with pytest.raises(HTTPException) as foreign:
            global_search.page(box.store, "Rights", limit=1, after=first["next_after"])
        assert foreign.value.status_code == 422
