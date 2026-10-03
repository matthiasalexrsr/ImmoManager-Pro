"""Real complete source pages, literal searches and current portfolio rights."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from backend import auth
from backend.db.orm_models import PropertyORM
from backend.models import ContactCreate, LeadCreate, PortfolioCreate, Property, PropertyCreate
from backend.services import global_search
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.tests.test_contract_workspace import active as active
from backend.tests.test_portfolio_access_http import access_http as access_http


def inventory(store, count, *, name="Findable", prefix="source"):
    portfolio = store.create_portfolio(PortfolioCreate(name="Synthetic search " + prefix))
    stamp = datetime.now(timezone.utc)
    rows = [{**PropertyCreate(portfolio_id=portfolio.id, name=f"{name} {index:05d}",
                             property_type="residential", city="Saarbrücken").model_dump(),
             "id": f"{prefix}-{index:06d}", "created_at": stamp, "updated_at": stamp}
            for index in range(count)]
    if hasattr(store, "db"):
        store.db.execute(PropertyORM.__table__.insert(), rows)
        store.db.commit()
    else:
        store.__dict__["properties"].update({row["id"]: Property.model_validate(row) for row in rows})
    return portfolio, rows


def test_complete_search_reaches_100_1000_and_10000_without_stock_lists(active, monkeypatch):
    _, rows = inventory(active, 10_001)
    for source in global_search.SOURCES:
        method = "list_" + source.collection
        if hasattr(active, method):
            monkeypatch.setattr(active, method, lambda *_args, **_kwargs: pytest.fail("Full stock list loaded"))
    points = []
    seen = []
    cursor = None
    while True:
        result = global_search.page(active, "findable", after=cursor, limit=500)
        assert len(result["results"]) <= 500
        seen.extend(row["id"] for row in result["results"])
        points.append(result["has_more"])
        cursor = result["next_after"]
        if not result["has_more"]:
            assert cursor is None
            break
        assert cursor
    expected = [row["id"] for row in reversed(rows)]
    assert seen == expected
    assert len(set(seen)) == 10_001
    for index in (99, 100, 999, 1000, 9999, 10000):
        assert seen[index] == expected[index]
    assert all(points[:-1]) and points[-1] is False


def test_real_contact_lead_address_unicode_and_literal_wildcard_fields(active):
    _, rows = inventory(active, 1, name="Straße %_\\", prefix="literal")
    prop = active.get_property(rows[0]["id"])
    assert global_search.page(active, "STRASSE %_\\")["results"][0]["id"] == prop.id
    assert global_search.page(active, "Saarbrücken")["results"][0]["id"] == prop.id
    contact = active.create_contact(ContactCreate(first_name="Zoë", last_name="Nachname",
                                                company_name="Suchfirma", email="contact@example.invalid"))
    lead = active.create_lead(LeadCreate(full_name="Interessent Müller", email="lead@example.invalid"))
    assert global_search.page(active, "Zoë Nachname")["results"][0]["id"] == contact.id
    assert global_search.page(active, "Suchfirma")["results"][0]["display"] == "Zoë Nachname Suchfirma"
    assert global_search.page(active, "Interessent Müller")["results"][0]["id"] == lead.id


def test_cursor_is_bound_to_query_size_actor_scope_and_fresh_rights(active, monkeypatch):
    portfolio, _ = inventory(active, 3)
    user = {"id": "searcher", "role": "verwalter", "is_active": True,
            "portfolio_access": "selected", "portfolio_ids": [portfolio.id]}
    monkeypatch.setattr(auth, "get_user_by_id", lambda _id: user.copy())
    captured = scope_from_user(user)
    with scope_context(captured):
        cursor = global_search.page(active, "Findable", limit=1)["next_after"]
        for term, size, point in (("different", 1, cursor), ("Findable", 2, cursor), ("Findable", 1, cursor + "x")):
            with pytest.raises(HTTPException) as failure:
                global_search.page(active, term, limit=size, after=point)
            assert failure.value.status_code == 422
        user["portfolio_ids"] = []
        with pytest.raises(HTTPException) as revoked:
            global_search.page(active, "Findable", limit=1, after=cursor)
        assert revoked.value.status_code == 403
    with scope_context(scope_from_user(user)):
        assert global_search.page(active, "Findable")["results"] == []
        with pytest.raises(HTTPException) as wrong_scope:
            global_search.page(active, "Findable", limit=1, after=cursor)
        assert wrong_scope.value.status_code == 422


def test_sql_source_failure_is_an_error_instead_of_an_empty_search(active):
    if not hasattr(active, "db"):
        return
    inventory(active, 1)

    def fail(_connection, _cursor, statement, *_args):
        if "FROM properties" in statement:
            raise RuntimeError("Synthetic unavailable property source")

    engine = active.db.get_bind()
    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="unavailable property source"):
            global_search.page(active, "Findable")
    finally:
        event.remove(engine, "before_cursor_execute", fail)


def test_actual_http_keyword_pages_keep_portfolio_boundary(access_http):
    client, store, _, headers, _, portfolios, *_ = access_http
    _, rows = inventory(store, 101, name="SearchHTTP")
    # The new source is initially foreign to the signed member's scope.
    assert client.get("/api/v1/search/page", params={"q": "SearchHTTP"}, headers=headers).json()["results"] == []
    for row in rows:
        if hasattr(store, "db"):
            store.db.execute(PropertyORM.__table__.update().where(PropertyORM.id == row["id"]).values(portfolio_id=portfolios[0].id))
        else:
            store.__dict__["properties"][row["id"]] = Property.model_validate({**row, "portfolio_id": portfolios[0].id})
    if hasattr(store, "db"):
        store.db.commit()
    seen = []
    cursor = None
    while True:
        response = client.get("/api/v1/search/page", params={"q": "SearchHTTP", "limit": 25,
                                                            **({"after": cursor} if cursor else {})}, headers=headers)
        assert response.status_code == 200, response.text
        page = response.json()
        seen.extend(value["id"] for value in page["results"])
        cursor = page["next_after"]
        if not page["has_more"]:
            break
    assert len(seen) == len(set(seen)) == 101
