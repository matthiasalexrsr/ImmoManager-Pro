"""Document metadata sources stay complete, scoped, bounded and truthful."""

import csv
import io
from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from backend import auth
from backend.db.orm_models import DocumentORM
from backend.models import Document
from backend.routers import document_inventory as router
from backend.services import document_inventory as service
from backend.services.document_inventory import DocumentInventoryQuery as Query
from backend.services.document_inventory_export import csv_chunks
from backend.services.portfolio_scope import scope_context
from backend.tests.test_contract_workspace import active as active
from backend.tests.test_contract_workspace import install_actor, seed
from backend.tests.test_portfolio_access_http import access_http as access_http


def add_documents(store, rows):
    if hasattr(store, "db"):
        store.db.execute(DocumentORM.__table__.insert(), [row.model_dump() for row in rows])
        store.db.commit()
    else:
        store.__dict__["documents"].update({row.id: row for row in rows})


def make_documents(store, count):
    contract, portfolio = seed(store)
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for start in range(0, count, 500):
        add_documents(store, [Document(id=f"document-{n:06d}", contract_id=contract.id, title=f"Dokument {n:06d}",
            document_type="Rechnung", document_date=date(2026, 1, 1) if n % 2 else None, file_url=f"/uploads/synthetic-{n}.pdf",
            ai_analyzed_at=stamp if n % 2 else None, ai_summary="Private full content must not be loaded in a list",
            created_at=stamp, updated_at=stamp) for n in range(start, min(count, start + 500))])
    return contract, portfolio


def test_full_sources_beyond_ten_thousand_with_inherited_names_and_no_large_fields(active, monkeypatch):
    contract, _ = make_documents(active, 10002)
    def forbidden(*args, **kwargs):
        raise AssertionError("No global lists")
    for method in ("list_documents", "list_contracts", "list_properties", "list_units", "_list_paginated"):
        monkeypatch.setattr(active, method, forbidden)
    for number in (100, 1000, 10000):
        page = service.document_inventory_page(active, Query(search=f"Dokument {number:06d}", property_id=contract.property_id, page_size=1))
        assert [row.id for row in page.items] == [f"document-{number:06d}"]
        assert page.items[0].property_name == "visible building"
        assert page.items[0].unit_label == "visible apartment"
        assert "ai_summary" not in page.items[0].model_dump()
    summary = service.document_inventory_summary(active, Query(unit_id=contract.unit_id, page_size=1))
    assert summary == dict(total=10002, with_file=10002, analyzed=5001, no_assignment=0)
    text = b"".join(csv_chunks(active, Query(contract_id=contract.id), chunk_size=1000)).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    assert len(rows) == len({row["id"] for row in rows}) == 10002
    assert rows[10000]["title"] == "Dokument 010000"
    assert "Private full content" not in text


@pytest.mark.parametrize("sort,direction", [("document_date", "asc"), ("document_date", "desc"), ("title", "asc"), ("updated_at", "desc")])
def test_dates_nulls_ties_and_bound_cursor(active, sort, direction):
    contract, _ = make_documents(active, 7)
    seen, cursor, first = [], None, None
    while True:
        page = service.document_inventory_page(active, Query(contract_id=contract.id, page_size=2, sort_by=sort, sort_order=direction, cursor=cursor))
        seen.extend(row.id for row in page.items)
        if not page.has_more:
            break
        cursor = page.next_cursor
        first = first or cursor
    assert len(seen) == len(set(seen)) == 7
    if sort == "document_date":
        assert set(seen[-4:]) == {f"document-{n:06d}" for n in (0, 2, 4, 6)}
    with pytest.raises(HTTPException) as error:
        service.document_inventory_page(active, Query(contract_id=contract.id, page_size=2, sort_by=sort, sort_order=direction, cursor=first, view="analyzed"))
    assert error.value.status_code == 422


def test_real_analysis_filters_and_dates(active):
    make_documents(active, 4)
    assert service.document_inventory_summary(active, Query(view="analyzed"))["total"] == 2
    assert service.document_inventory_summary(active, Query(view="not_analyzed"))["total"] == 2
    assert service.document_inventory_summary(active, Query(date_from="2026-01-01"))["total"] == 2
    assert service.document_inventory_summary(active, Query(view="no_assignment"))["total"] == 0
    assert service.document_inventory_summary(active, Query(search="No such title"))["total"] == 0
    with pytest.raises(ValueError):
        Query(date_from="2026-02-01", date_to="2026-01-01")


def test_scope_and_export_revocation(active, monkeypatch):
    contract, portfolio = make_documents(active, 3)
    hidden, _ = seed(active, "Hidden")
    add_documents(active, [Document(id="hidden-document", contract_id=hidden.id, title="Hidden document", file_url="/uploads/hidden")])
    scope, user = install_actor(monkeypatch, [portfolio.id])
    with scope_context(scope):
        assert service.document_inventory_summary(active, Query())["total"] == 3
        assert not service.document_inventory_page(active, Query(property_id=hidden.property_id)).items
        chunks = csv_chunks(active, Query(), chunk_size=1)
        assert contract.contract_number.encode() in next(chunks)
        user["portfolio_ids"] = []
        with pytest.raises(HTTPException):
            next(chunks)
        chunks.close()


def test_bounded_projection_ignores_pending_document_changes(active):
    if not hasattr(active, "db"):
        pytest.skip("SQL identity map only")
    make_documents(active, 4)
    row = active.db.get(DocumentORM, "document-000000")
    row.title = "Unflushed private edit"
    statements = []
    def capture(_conn, _cursor, sql, _params, _context, _many):
        statements.append(sql)
    engine = active.db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        page = service.document_inventory_page(active, Query(page_size=1))
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1 and "LIMIT" in statements[0].upper()
    assert "ai_summary" not in statements[0] and "ai_entities_json" not in statements[0]
    assert page.items[0].title != row.title and row in active.db.dirty
    active.db.rollback()


def test_http_routes_and_legacy_remain_available(access_http):
    client, _, owner, member, *_ = access_http
    for suffix in ("page", "summary", "export"):
        path = "/api/v1/documents/inventory/" + suffix
        assert client.get(path).status_code == 401
        response = client.get(path, headers=member)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
    assert isinstance(client.get("/api/v1/documents", headers=owner).json(), list)
    assert client.get("/api/v1/documents/inventory/page?cursor=bad", headers=member).status_code == 422


def test_http_last_fence_revokes_export_token(access_http, monkeypatch):
    client, _, _, member, *_ = access_http
    original = router.document_inventory_page
    def revoke(*args):
        result = original(*args)
        auth.revoke_token(member["Authorization"][7:])
        return result
    monkeypatch.setattr(router, "document_inventory_page", revoke)
    assert client.get("/api/v1/documents/inventory/page", headers=member).status_code == 401
