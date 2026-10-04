"""Complete contacts with explicit portfolio grants and bounded legacy compatibility."""

import csv
import io
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import event, update

from backend import auth
from backend.db.orm_models import ContactORM
from backend.models import Contact, ContactCreate, PortfolioCreate
from backend.routers import contact_inventory as router
from backend.routers import contacts as legacy
from backend.services import contact_inventory as service
from backend.services.contact_inventory import ContactInventoryQuery as Query
from backend.services.contact_inventory_export import csv_chunks
from backend.services.portfolio_scope import scope_context
from backend.tests.test_contract_workspace import active as active
from backend.tests.test_contract_workspace import install_actor
from backend.tests.test_portfolio_access_http import access_http as access_http


def add_contacts(store, rows):
    if hasattr(store, "db"):
        store.db.execute(ContactORM.__table__.insert(), [row.model_dump() for row in rows])
        store.db.commit()
    else:
        store.__dict__["contacts"].update({row.id: row for row in rows})


def contacts(store, count=10002):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for start in range(0, count, 500):
        add_contacts(store, [Contact(id=f"contact-{n:06d}", contact_type="supplier", company_name=f"Kontakt {n:06d}",
            email=f"synthetic-{n}@example.test" if n % 2 else None, mobile="0123" if n % 2 else None,
            city="Kassel" if n % 2 else None, notes="PRIVATE LONG NOTE", iban="PRIVATE-BANK-DETAIL", bic="PRIVATE-BIC",
            created_at=stamp, updated_at=stamp) for n in range(start, min(count, start + 500))])


def test_full_source_and_legacy_offset_without_materializing_all_contacts(active, monkeypatch):
    contacts(active)
    def forbidden(*args, **kwargs):
        raise AssertionError("No global list")
    monkeypatch.setattr(active, "list_contacts", forbidden)
    monkeypatch.setattr(active, "_list_paginated", forbidden)
    monkeypatch.setattr(legacy, "store", active)
    for number in (100, 1000, 10000):
        page = service.contact_inventory_page(active, Query(search=f"Kontakt {number:06d}", page_size=1))
        assert [row.id for row in page.items] == [f"contact-{number:06d}"]
        assert not {"iban", "bic", "notes", "tax_id"}.intersection(page.items[0].model_dump())
    result = service.contact_inventory_summary(active, Query(contact_type="supplier"))
    assert result == dict(total=10002, tenant=0, owner=0, supplier=10002, manager=0, no_email=5001, no_phone=5001)
    old = legacy.list_contacts(skip=10000, limit=2, contact_type="supplier", sort_by="company_name", sort_order="asc")
    assert len(old) == 2 and old[0].id == "contact-010000" and old[0].notes == "PRIVATE LONG NOTE"
    text = b"".join(csv_chunks(active, Query(), chunk_size=1000)).decode("utf-8-sig")
    assert "PRIVATE" not in text
    rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    assert len(rows) == len({row["id"] for row in rows}) == 10002


@pytest.mark.parametrize("sort,direction", [("city", "asc"), ("city", "desc"), ("display_name", "desc"), ("updated_at", "asc")])
def test_stable_cursor_nulls_and_binding(active, sort, direction):
    contacts(active, 7)
    seen, cursor, first = [], None, None
    while True:
        page = service.contact_inventory_page(active, Query(sort_by=sort, sort_order=direction, page_size=2, cursor=cursor))
        seen.extend(row.id for row in page.items)
        if not page.has_more:
            break
        cursor = page.next_cursor
        first = first or cursor
    assert len(seen) == len(set(seen)) == 7
    if sort == "city":
        assert set(seen[-4:]) == {f"contact-{n:06d}" for n in (0, 2, 4, 6)}
    with pytest.raises(HTTPException) as error:
        service.contact_inventory_page(active, Query(sort_by=sort, sort_order=direction, page_size=2, cursor=first, view="no_email"))
    assert error.value.status_code == 422


def test_names_empty_fields_and_unicode_search(active):
    add_contacts(active, [Contact(id="person", company_name="  ", first_name=" Anna ", last_name=" Müller ", phone=" ", email=""),
                         Contact(id="empty", first_name=" ", company_name=None, mobile="  "),
                         Contact(id="company", company_name=" Betrieb ", first_name="Ignored", mobile="123")])
    page = service.contact_inventory_page(active, Query(search="ANNA MÜLLER"))
    assert [row.display_name for row in page.items] == ["Anna Müller"]
    assert service.contact_inventory_summary(active, Query(view="unnamed"))["total"] == 1
    assert service.contact_inventory_summary(active, Query(view="no_phone"))["total"] == 2
    assert service.contact_inventory_summary(active, Query(view="no_email"))["total"] == 3


def test_explicit_contact_grants_and_export_revocation(active, monkeypatch):
    contacts(active, 1)
    portfolio = active.create_portfolio(PortfolioCreate(name="Granted"))
    scope, user = install_actor(monkeypatch, [portfolio.id])
    with scope_context(scope):
        first = active.create_contact(ContactCreate(company_name="Allowed one"))
        active.create_contact(ContactCreate(company_name="Allowed two"))
        assert service.contact_inventory_summary(active, Query())["total"] == 2
        chunks = csv_chunks(active, Query(), chunk_size=1)
        try:
            chunk = next(chunks)
            assert first.id.encode() in chunk and b"Kontakt 000000" not in chunk
            user["portfolio_ids"] = []
            with pytest.raises(HTTPException):
                next(chunks)
        finally:
            chunks.close()


def test_sql_metadata_and_legacy_no_autoflush(active, monkeypatch):
    if not hasattr(active, "db"):
        pytest.skip("SQL-only identity map assertion")
    contacts(active, 3)
    pending = active.db.get(ContactORM, "contact-000000")
    pending.company_name = "Unflushed edit"
    statements = []
    def capture(_conn, _cursor, sql, *_):
        statements.append(sql)
    engine = active.db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        page = service.contact_inventory_page(active, Query(page_size=1))
        monkeypatch.setattr(legacy, "store", active)
        result = legacy.list_contacts(skip=0, limit=1, contact_type=None, sort_by="company_name", sort_order="asc")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 2 and all("LIMIT" in sql.upper() for sql in statements)
    assert "notes" not in statements[0] and "iban" not in statements[0]
    assert page.items[0].company_name != pending.company_name and result[0].company_name != pending.company_name
    assert pending in active.db.dirty
    active.db.rollback()


def test_contact_export_concurrent_change(active):
    if not hasattr(active, "db"):
        pytest.skip("SQL snapshot and independent writer")
    contacts(active, 3)
    engine = active.db.get_bind()
    if engine.dialect.name == "sqlite":
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    chunks = csv_chunks(active, Query(), chunk_size=1)
    try:
        next(chunks)
        with engine.begin() as writer:
            writer.execute(update(ContactORM.__table__).where(ContactORM.id == "contact-000001").values(company_name="Changed"))
        with pytest.raises(HTTPException) as error:
            next(chunks)
        assert error.value.status_code == 409
    finally:
        chunks.close()


@pytest.mark.parametrize("operation", ["page", "summary"])
def test_http_private_metadata_final_access_and_legacy(access_http, monkeypatch, operation):
    client, _, owner, member, actor, *_ = access_http
    path = "/api/v1/contacts/inventory/" + operation
    assert client.get(path).status_code == 401
    response = client.get(path, headers=member)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    assert isinstance(client.get("/api/v1/contacts", headers=owner).json(), list)
    original = getattr(router, "contact_inventory_" + operation)
    def revoke(*args):
        result = original(*args)
        auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
        return result
    monkeypatch.setattr(router, "contact_inventory_" + operation, revoke)
    assert client.get(path, headers=member).status_code == 403
