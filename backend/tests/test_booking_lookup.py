"""Genuine bounded choices and exact selected references without full lists."""
import pytest
from sqlalchemy import event

from backend import models
from backend.routers import bookings
from backend.services.booking_lookup import REFERENCES, BookingLookupQuery, booking_choices
from backend.services.booking_query import BookingQueryError
from backend.tests.test_booking_pages import bookings_store  # noqa: F401
from backend.tests.test_booking_pages_http import credentials, installation  # noqa: F401

READ_TYPES = dict(accounts=models.Account, categories=models.Category, properties=models.Property, units=models.Unit, tenants=models.Tenant)


def references(active, kind, count=37):
    model, label = REFERENCES[kind]
    defaults = {"accounts": dict(portfolio_id="portfolio", account_type="bank"),
        "categories": dict(portfolio_id="portfolio", category_type="income"),
        "properties": dict(portfolio_id="portfolio", property_type="residential"),
        "units": dict(property_id="property-0", unit_type="apartment"), "tenants": {}}[kind]
    rows = [dict(id=f"choice-{n:05d}", **defaults, **{label: f"Choice {n} 100%_literal"}) for n in range(count)]
    if hasattr(active, "db"):
        active.db.execute(model.__table__.insert(), rows)
        active.db.commit()
    else:
        getattr(active, kind).update({value["id"]: READ_TYPES[kind](**value) for value in rows})


@pytest.mark.parametrize("kind", list(REFERENCES))
def test_all_reference_kinds_search_page_and_retain_selected_outside_page(bookings_store, kind):  # noqa: F811
    references(bookings_store, kind)
    query = BookingLookupQuery(page_size=7, selected_id="choice-00000", search="100%_literal")
    first = booking_choices(bookings_store, kind, query)
    assert len(first.items) == 7 and first.has_more
    assert first.selected.id == "choice-00000" and first.selected.id not in {item.id for item in first.items}
    seen = []
    while True:
        page = booking_choices(bookings_store, kind, query)
        seen.extend(item.id for item in page.items)
        if not page.has_more:
            break
        query = query.model_copy(update={"cursor": page.next_cursor})
    assert seen == [f"choice-{n:05d}" for n in reversed(range(37))]


def test_lookup_cursor_cannot_be_reused_for_another_kind_filter_or_size(bookings_store):  # noqa: F811
    references(bookings_store, "accounts")
    query = BookingLookupQuery(page_size=7)
    cursor = booking_choices(bookings_store, "accounts", query).next_cursor
    for kind, changes in [("tenants", {}), ("accounts", {"search": "Choice"}), ("accounts", {"page_size": 8})]:
        with pytest.raises(BookingQueryError) as error:
            booking_choices(bookings_store, kind, query.model_copy(update={"cursor": cursor, **changes}))
        assert error.value.clear_code == "cursor_filter_mismatch"
    with pytest.raises(BookingQueryError) as error:
        booking_choices(bookings_store, "accounts", query.model_copy(update={"cursor": cursor + "a"}))
    assert error.value.clear_code == "cursor_invalid"


def test_large_lookup_fetches_only_page_and_selected_without_count(bookings_store):  # noqa: F811
    references(bookings_store, "accounts", 1103)
    calls = []
    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            calls.append((statement, parameters))
    engine = bookings_store.db.get_bind() if hasattr(bookings_store, "db") else None
    if engine:
        event.listen(engine, "before_cursor_execute", capture)
    try:
        page = booking_choices(bookings_store, "accounts", BookingLookupQuery(page_size=25, selected_id="choice-00000"))
    finally:
        if engine:
            event.remove(engine, "before_cursor_execute", capture)
    assert len(page.items) == 25 and page.selected.id == "choice-00000"
    assert page.has_more
    if engine:
        assert len(calls) == 2 and all("COUNT" not in sql for sql, _ in calls)
        assert "LIMIT" in calls[0][0] and calls[0][1][-2:] == (26, 0)
        assert "WHERE" in calls[1][0] and calls[1][1] == ("choice-00000",)


def test_lookup_route_requires_auth_and_accepts_reader_and_rejects_unknown_kind(installation):  # noqa: F811
    path = "/api/v1/bookings/lookup/accounts"
    assert installation.get(path).status_code == 401
    headers = credentials()
    response = installation.get(path, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"items": [], "selected": None, "next_cursor": None, "has_more": False}
    for params in ({"search": "x" * 201}, {"selected_id": "a\n"}, {"page_size": 0}, {"table": "users"}):
        assert installation.get(path, headers=headers, params=params).status_code == 422
    assert installation.get("/api/v1/bookings/lookup/users", headers=headers).status_code == 422


def test_legacy_http_date_filter_retains_matches_after_ten_thousand(installation):  # noqa: F811
    from datetime import date

    from backend.tests.test_booking_pages import insert_rows, row
    insert_rows(bookings.store, [row(n, booking_date=date(2006, 1, 1)) for n in range(35, 10036)])
    insert_rows(bookings.store, [row(10036, booking_date=date(2046, 1, 15))])
    response = installation.get("/api/v1/bookings", headers=credentials(), params={
        "date_from": "2046-01-01", "date_to": "2046-12-31", "limit": 1, "sort_by": "id"})
    assert response.status_code == 200
    assert [value["id"] for value in response.json()] == ["booking-00010036"]
