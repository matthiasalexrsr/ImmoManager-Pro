"""Large synthetic inventories, coherent contexts and bounded authorized pages."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event, current_thread

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from backend import auth
from backend.db.orm_models import Base, ContractORM, TenantORM
from backend.models import ContractCreate, PortfolioCreate, PropertyCreate, PropertyPatch, TenantCreate, UnitCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import contract_workspace as router
from backend.services import contract_workspace as workspace
from backend.services.contract_workspace_types import ContractWorkspaceError, ContractWorkspaceQuery
from backend.services.portfolio_scope import AccessScope, scope_context
from backend.storage import InMemoryStore


@pytest.fixture(params=["memory", "sqlite"])
def active(request, tmp_path):
    if request.param == "memory":
        yield InMemoryStore()
        return
    engine = create_engine(
        "sqlite:///" + (tmp_path / "workspace.sqlite").as_posix(), connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield SQLAlchemyStore(db)
    engine.dispose()


def seed(store, prefix="visible"):
    portfolio = store.create_portfolio(PortfolioCreate(name=prefix))
    prop = store.create_property(
        PropertyCreate(portfolio_id=portfolio.id, name=prefix + " building", property_type="residential")
    )
    unit = store.create_unit(
        UnitCreate(property_id=prop.id, label=prefix + " apartment", unit_type="apartment", cold_rent=123.45)
    )
    tenant = store.create_tenant(
        TenantCreate(
            full_name=prefix + " person",
            email=prefix + "@example.test",
            phone="synthetic-private-field",
            notes="Unrelated private context must not be expanded",
        )
    )
    row = store.create_contract(
        ContractCreate(
            contract_number=prefix + " lease",
            property_id=prop.id,
            unit_id=unit.id,
            tenant_id=tenant.id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status="draft",
        )
    )
    return row, portfolio


def insert(store, items):
    if hasattr(store, "db"):
        store.db.execute(ContractORM.__table__.insert(), [row.model_dump() for row in items])
        store.db.commit()
    else:
        store.__dict__["contracts"].update({row.id: row for row in items})


def page(store, **values):
    return workspace.get_contract_workspace_page(store, ContractWorkspaceQuery(**values))


def pages(store, **values):
    collected, cursor = [], None
    while True:
        result = page(store, cursor=cursor, **values)
        collected.extend(result.items)
        if not result.has_more:
            assert result.next_cursor is None
            return collected
        assert result.next_cursor and result.items
        cursor = result.next_cursor


def install_actor(monkeypatch, portfolio_ids):
    user = dict(
        id="synthetic-reader", role="readonly", is_active=True, portfolio_access="selected", portfolio_ids=portfolio_ids
    )
    monkeypatch.setattr(auth, "get_user_by_id", lambda identifier: user if identifier == user["id"] else None)
    return AccessScope(user["id"], user["role"], False, tuple(sorted(portfolio_ids))), user


def test_late_matches_and_contexts_beyond_ten_thousand_use_one_bounded_read(active, monkeypatch):
    template, _ = seed(active)
    for start in range(0, 10001, 500):
        insert(
            active,
            [
                template.model_copy(
                    update={
                        "id": f"history-{index:05d}",
                        "contract_number": f"History-{index:05d}",
                        "start_date": date(2010, 1, 1),
                        "end_date": date(2010, 12, 31),
                    }
                )
                for index in range(start, min(start + 500, 10001))
            ],
        )
    # Also prove the names are not taken from the first 100 reference records.
    for index in range(101):
        active.create_property(
            PropertyCreate(
                portfolio_id=active.get_property(template.property_id).portfolio_id,
                name=f"Early reference {index:03d}",
                property_type="residential",
            )
        )
        active.create_unit(
            UnitCreate(property_id=template.property_id, label=f"Early unit {index:03d}", unit_type="apartment")
        )
        active.create_tenant(TenantCreate(full_name=f"Early tenant {index:03d}"))
    late, _ = seed(active, "Late Pruefung 100%_literal")
    # Reproduce the old workplace's real first-page limitation before checking
    # that the new API recovers both the late contract and every late label.
    assert late.id not in {row.id for row in active._list_paginated("contract", skip=0, limit=100)}
    for kind, identifier in (("property", late.property_id), ("unit", late.unit_id), ("tenant", late.tenant_id)):
        assert identifier not in {row.id for row in active._list_paginated(kind, skip=0, limit=100)}
    calls, statements = [], []
    original_item = workspace._item

    def bounded_item(value):
        calls.append(value["id"])
        return original_item(value)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Workspace pages must not collect global entity/reference lists")

    for method in ("list_contracts", "list_properties", "list_units", "list_tenants", "_list_paginated"):
        monkeypatch.setattr(active, method, forbidden)
    monkeypatch.setattr(workspace, "_item", bounded_item)
    engine = active.db.get_bind() if hasattr(active, "db") else None

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        statements.append((statement, parameters))

    if engine:
        event.listen(engine, "before_cursor_execute", capture)
    try:
        result = page(
            active,
            search="pruefung 100%_literal",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 12, 31),
            status="draft",
            property_id=late.property_id,
            tenant_id=late.tenant_id,
            page_size=1,
        )
    finally:
        if engine:
            event.remove(engine, "before_cursor_execute", capture)
    assert [row.id for row in result.items] == [late.id]
    assert result.items[0].property_name == "Late Pruefung 100%_literal building"
    assert result.items[0].tenant_name == "Late Pruefung 100%_literal person"
    assert result.items[0].unit_label == "Late Pruefung 100%_literal apartment"
    assert result.items[0].unit_cold_rent == 123.45
    assert len(calls) <= 2
    if engine:
        assert len(statements) == 1
        statement, parameters = statements[0]
        assert "LIMIT" in statement.upper() and "COUNT(" not in statement.upper()
        assert "contracts.start_date >=" in statement and "contracts.end_date <=" in statement
        # SQLAlchemy's SQLite LIMIT compiler supplies an implicit zero OFFSET.
        # No inventory-sized or cursor-dependent offset is used.
        assert parameters[-2:] == (2, 0)


@pytest.mark.parametrize(
    "sort_by", ["start_date", "end_date", "status", "property_name", "unit_label", "tenant_name", "deposit_amount"]
)
@pytest.mark.parametrize("order", ["asc", "desc"])
def test_ties_nulls_and_large_legacy_ids_are_stable_across_every_page(active, sort_by, order):
    template, _ = seed(active)
    identifiers = ["B", "a", "b", "legacy Ü id " + "x" * 120]
    rows = [
        template.model_copy(
            update={
                "id": identifier,
                "contract_number": "Tie-" + str(index),
                "end_date": None if index in (1, 3) else date(2026, 12, 31),
                "deposit_amount": None if index in (1, 3) else 10.25,
            }
        )
        for index, identifier in enumerate(identifiers)
    ]
    insert(active, rows)
    result = pages(active, page_size=2, sort_by=sort_by, sort_order=order)
    assert len({row.id for row in result}) == len(result) == 5
    original = [template, *rows]
    nullable = {"end_date", "deposit_amount"}
    known = [row for row in original if sort_by not in nullable or getattr(row, sort_by) is not None]
    unknown = [row for row in original if sort_by in nullable and getattr(row, sort_by) is None]
    expected = sorted(known, key=lambda row: row.id.encode("utf-8"), reverse=order == "desc")
    expected += sorted(unknown, key=lambda row: row.id.encode("utf-8"), reverse=order == "desc")
    assert [row.id for row in result] == [row.id for row in expected]


def test_search_uses_all_visible_contexts_and_exact_date_boundaries(active):
    first, _ = seed(active, "Visible")
    insert(
        active,
        [
            first.model_copy(update={"id": "open-ended", "contract_number": "Open", "end_date": None}),
            first.model_copy(update={"id": "late-start", "contract_number": "Later", "start_date": date(2026, 2, 1)}),
        ],
    )
    for search in ("VISIBLE LEASE", "building", "apartment", "person"):
        result = page(
            active,
            search=search,
            tenant_id=first.tenant_id,
            unit_id=first.unit_id,
            date_from=date(2026, 2, 1),
            date_to=date(2026, 12, 31),
        )
        assert [row.id for row in result.items] == (["late-start"] if search != "VISIBLE LEASE" else [])
    assert [
        row.id
        for row in page(active, search="Visible lease", date_from=date(2026, 1, 1), date_to=date(2026, 12, 31)).items
    ] == [first.id]
    assert "open-ended" in {row.id for row in page(active, date_from=date(2026, 1, 1)).items}
    assert "open-ended" not in {row.id for row in page(active, date_to=date(2026, 12, 31)).items}


@pytest.mark.parametrize(
    "stored,search",
    [
        ("ÜBER Größe ÄRGER ÖSTERREICH STRAẞE", "über grösse ärger österreich strasse"),
        ("Σίσυφος", "σίσυφοσ"),
        ("Ligature ﬃ", "ligature FFI"),
        ("İstanbul", "i\u0307stanbul"),
    ],
)
def test_unicode_casefold_matches_contract_and_all_reference_names(active, stored, search):
    row, _ = seed(active, stored)
    for suffix, field in (
        ("lease", "contract_number"),
        ("building", "property_name"),
        ("apartment", "unit_label"),
        ("person", "tenant_name"),
    ):
        result = page(active, search=search + " " + suffix)
        assert [item.id for item in result.items] == [row.id]
        assert getattr(result.items[0], field) == stored + " " + suffix


def test_search_accepts_substrings_and_configured_full_long_names_without_truncation(active, monkeypatch):
    stored = "Prefix " + "Ö" * 600 + " Übergrößenprüfung"
    row, _ = seed(active, stored)
    assert page(active, search="übergrössenprüfung").items[0].id == row.id
    first = page(active, search="Prefix", sort_by="tenant_name", page_size=1)
    assert first.items[0].tenant_name == stored + " person"
    from backend.services import contract_workspace_types

    monkeypatch.setattr(
        contract_workspace_types, "settings", type("Settings", (), {"contract_workspace_search_max_chars": 2000})()
    )
    assert page(active, search=stored).items[0].id == row.id


@pytest.mark.parametrize(
    "sort_by",
    [
        "contract_number",
        "start_date",
        "end_date",
        "status",
        "property_name",
        "unit_label",
        "tenant_name",
        "deposit_amount",
    ],
)
def test_sorting_happens_before_the_first_limited_page(active, sort_by):
    alpha, _ = seed(active, "Alpha")
    zeta, _ = seed(active, "Zeta")
    if hasattr(active, "db"):
        active.db.execute(
            ContractORM.__table__.update()
            .where(ContractORM.id == alpha.id)
            .values(start_date=date(2025, 1, 1), end_date=date(2026, 11, 30), deposit_amount=1, status="active")
        )
        active.db.execute(ContractORM.__table__.update().where(ContractORM.id == zeta.id).values(deposit_amount=2))
        active.db.commit()
    else:
        active.__dict__["contracts"][alpha.id] = alpha.model_copy(
            update={
                "start_date": date(2025, 1, 1),
                "end_date": date(2026, 11, 30),
                "deposit_amount": 1,
                "status": "active",
            }
        )
        active.__dict__["contracts"][zeta.id] = zeta.model_copy(update={"deposit_amount": 2})
    assert page(active, sort_by=sort_by, page_size=1).items[0].id == alpha.id
    assert page(active, sort_by=sort_by, sort_order="desc", page_size=1).items[0].id == zeta.id


def test_continuation_survives_deleted_boundary_and_handles_concurrent_insert_without_offset(active):
    first, _ = seed(active, "B")
    insert(
        active,
        [
            first.model_copy(update={"id": "d", "contract_number": "D"}),
            first.model_copy(update={"id": "f", "contract_number": "F"}),
        ],
    )
    initial = page(active, page_size=1)
    assert initial.items[0].id == first.id
    insert(
        active,
        [
            first.model_copy(update={"id": "a", "contract_number": "A"}),
            first.model_copy(update={"id": "c", "contract_number": "C"}),
        ],
    )
    active.delete_contract(first.id)
    continuation = page(active, page_size=1, cursor=initial.next_cursor)
    assert continuation.items[0].id == "c"
    assert page(active, page_size=1).items[0].id == "a"


def test_expired_cursor_provides_explicit_recoverable_error(active, monkeypatch):
    template, _ = seed(active)
    insert(active, [template.model_copy(update={"id": "second", "contract_number": "Second"})])
    monkeypatch.setattr(workspace, "time", lambda: 1000)
    cursor = page(active, page_size=1).next_cursor
    monkeypatch.setattr(workspace, "time", lambda: 1000 + workspace.CURSOR_SECONDS)
    with pytest.raises(ContractWorkspaceError) as expired:
        page(active, page_size=1, cursor=cursor)
    assert expired.value.code == "cursor_expired"
    assert expired.value.detail["recovery"] == "restart_page"


def test_foreign_or_broken_parents_never_expand_contexts_or_search_hits(active, monkeypatch):
    visible, portfolio = seed(active, "Visible")
    hidden, _ = seed(active, "Hidden personal")
    insert(
        active,
        [visible.model_copy(update={"id": "broken-parent", "contract_number": "Broken", "unit_id": hidden.unit_id})],
    )
    scope, _ = install_actor(monkeypatch, [portfolio.id])
    with scope_context(scope):
        result = page(active, search="VISIBLE")
        assert [row.id for row in result.items] == [visible.id]
        assert page(active, search="Hidden personal").items == []
        assert page(active, property_id=hidden.property_id).items == []
        serialized = result.model_dump(mode="json")
        assert "synthetic-private-field" not in str(serialized)
        assert "@example.test" not in str(serialized)
        assert "Hidden personal" not in str(serialized)


def test_cursor_is_signed_bound_to_filters_actor_scope_sort_size_and_current_role(active, monkeypatch):
    template, portfolio = seed(active)
    insert(active, [template.model_copy(update={"id": "second", "contract_number": "Second"})])
    scope, user = install_actor(monkeypatch, [portfolio.id])
    with scope_context(scope):
        cursor = page(active, page_size=1).next_cursor
        with pytest.raises(ContractWorkspaceError, match="geprüft"):
            page(active, page_size=1, cursor=cursor[:-1] + ("a" if cursor[-1] != "a" else "b"))
        for changed in ({"search": "other"}, {"page_size": 2}, {"sort_order": "desc"}, {"status": "draft"}):
            with pytest.raises(ContractWorkspaceError) as error:
                page(active, **{"page_size": 1, "cursor": cursor, **changed})
            assert error.value.code == "cursor_filter_mismatch"
        user["role"] = "verwalter"
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as changed_role:
            page(active, page_size=1, cursor=cursor)
        assert changed_role.value.status_code == 403
        user["role"] = "readonly"
        user["portfolio_ids"] = []
    replacement = AccessScope(user["id"], user["role"], False, ())
    with scope_context(replacement), pytest.raises(ContractWorkspaceError) as revoked:
        page(active, page_size=1, cursor=cursor)
    assert revoked.value.code == "cursor_filter_mismatch"


def test_midnight_keeps_signed_reference_date_and_new_page_uses_today(active, monkeypatch):
    row, _ = seed(active)
    insert(
        active,
        [
            row.model_copy(
                update={"id": "end-next-day", "contract_number": "A", "status": "active", "end_date": date(2026, 10, 3)}
            ),
            row.model_copy(
                update={
                    "id": "end-three-days",
                    "contract_number": "B",
                    "status": "active",
                    "end_date": date(2026, 10, 5),
                }
            ),
        ],
    )
    monkeypatch.setattr(workspace, "today", lambda: date(2026, 10, 2))
    first = page(active, view="ending_soon", page_size=1)
    assert first.reference_date == date(2026, 10, 2)
    monkeypatch.setattr(workspace, "today", lambda: date(2026, 10, 3))
    second = page(active, view="ending_soon", page_size=1, cursor=first.next_cursor)
    assert second.reference_date == first.reference_date
    assert [row.id for row in second.items] == ["end-three-days"]
    refreshed = page(active, view="ending_soon", page_size=1)
    assert refreshed.reference_date == date(2026, 10, 3) and refreshed.items[0].id == "end-three-days"


def test_page_budget_is_positive_configurable_and_not_a_total_inventory_limit(active, monkeypatch):
    template, _ = seed(active)
    monkeypatch.setattr(
        workspace,
        "settings",
        type("Settings", (), {"contract_workspace_page_max_size": 6000, "jwt_secret_key": "synthetic-cursor-key"})(),
    )
    assert [row.id for row in page(active, page_size=5500).items] == [template.id]
    with pytest.raises(ContractWorkspaceError) as exceeded:
        page(active, page_size=6001)
    assert exceeded.value.code == "page_size_exceeded"
    workspace.settings.contract_workspace_page_max_size = 0
    with pytest.raises(RuntimeError, match="positive"):
        page(active)


def test_sql_page_does_not_flush_pending_writes_and_uses_original_exact_edit_revision(active):
    row, _ = seed(active)
    if not hasattr(active, "db"):
        pytest.skip("SQL no-autoflush gate uses the SQLite variant")
    active.db.add(TenantORM(id="pending", full_name="Pending private write"))
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    engine = active.db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = page(active, search="VISIBLE")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1 and "INSERT" not in statements[0].upper()
    assert len(active.db.new) == 1
    from backend.services.concurrency import etag

    assert result.items[0].edit_etag == etag("contracts", row.id, row.updated_at)
    active.db.rollback()


def test_memory_contexts_and_selection_hold_the_same_writer_lock(monkeypatch):
    from backend.services import payments

    store = InMemoryStore()
    row, _ = seed(store)
    entered, release, attempted, acquired = Event(), Event(), Event(), Event()
    actual_lock = payments._memory_lock

    class ObservedLock:
        def __enter__(self):
            if current_thread().name.startswith("writer"):
                attempted.set()
            actual_lock.acquire()
            if current_thread().name.startswith("writer"):
                acquired.set()
            return self

        def __exit__(self, *_):
            actual_lock.release()

    original = workspace.memory_visible

    def paused(*args, **kwargs):
        if current_thread().name.startswith("reader") and not entered.is_set():
            entered.set()
            assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(payments, "_memory_lock", ObservedLock())
    monkeypatch.setattr(workspace, "memory_visible", paused)
    with (
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="reader") as readers,
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="writer") as writers,
    ):
        reading = readers.submit(page, store)
        assert entered.wait(5)
        writing = writers.submit(store._patch_entity, "property", row.property_id, PropertyPatch(name="After write"))
        try:
            assert attempted.wait(5) and not acquired.wait(0.2)
        finally:
            release.set()
        assert reading.result(5).items[0].property_name == "visible building"
        writing.result(5)
    assert page(store).items[0].property_name == "After write"


@pytest.mark.parametrize("adapter", ["memory", "sqlite"])
def test_full_http_route_auth_scope_and_page_etag_preserve_business_cas(adapter, tmp_path, monkeypatch):
    from backend.db import session as session_module
    from backend.exceptions import register_exception_handlers
    from backend.services.portfolio_scope import scope_context
    from backend.tests import form_draft_api_support as support

    # Exercise the production router registration, including the common auth
    # dependency and its order before /contracts/{identifier}.
    engine = None
    if adapter == "sqlite":
        engine = create_engine(
            "sqlite:///" + (tmp_path / "full-http.sqlite").as_posix(), connect_args={"check_same_thread": False}
        )
        monkeypatch.setattr(session_module, "engine", engine)
        session_module.create_tables()
    try:
        with support.application(monkeypatch, engine) as application:
            register_exception_handlers(application.client.app)
            application.client.app.middleware_stack = None
            monkeypatch.setattr(router, "store", application.store)
            from backend.routers import contracts

            monkeypatch.setattr(contracts, "store", application.store)
            with scope_context(None):
                # Use the selected actor's already authorized own portfolio.
                own, _ = seed(application.store, "HTTP own")
                prop = application.store.get_property(own.property_id)
                application.store._patch_entity(
                    "property", prop.id, PropertyPatch(portfolio_id=application.portfolios[0].id)
                )
            endpoint = "/api/v1/contracts/workspace/page"
            client, headers = application.client, application.headers(application.member)
            assert client.get(endpoint).status_code == 401
            response = client.get(endpoint, headers=headers, params={"page_size": 1})
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "private, no-store"
            item = response.json()["items"][0]
            assert item["id"] == own.id and item["tenant_name"] == "HTTP own person"
            changed = client.patch(
                f"/api/v1/contracts/{own.id}",
                headers={**headers, "If-Match": item["edit_etag"]},
                json={"contract_number": "Updated metadata"},
            )
            assert changed.status_code == 200, changed.text
            stale = client.patch(
                f"/api/v1/contracts/{own.id}",
                headers={**headers, "If-Match": item["edit_etag"]},
                json={"contract_number": "Stale metadata"},
            )
            assert stale.status_code == 412
            owner = application.headers(application.owner)
            assert (
                client.patch(
                    f"/api/v1/auth/users/{application.member.id}",
                    headers=owner,
                    json={"portfolio_access": "selected", "portfolio_ids": []},
                ).status_code
                == 200
            )
            assert client.get(endpoint, headers=headers).json()["items"] == []
            for query in (
                {"sort_by": "private_column"},
                {"search": "x" * 201},
                {"status": "unknown"},
                {"date_from": "20261002"},
                {"extra": "private"},
            ):
                assert client.get(endpoint, headers=headers, params=query).status_code == 422
    finally:
        if engine is not None:
            engine.dispose()
