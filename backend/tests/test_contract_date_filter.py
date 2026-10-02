"""Contract date pages remain complete beyond historical prefilter caps."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event, current_thread

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from backend.db.orm_models import Base, ContractORM
from backend.models import ContractCreate, PortfolioCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import contracts
from backend.services.portfolio_scope import AccessScope, scope_context
from backend.storage import InMemoryStore
from backend.tests.test_portfolio_access_http import access_http  # noqa: F401


@pytest.fixture(params=["memory", "sqlite"])
def contract_store(request, tmp_path, monkeypatch):
    if request.param == "memory":
        active = InMemoryStore()
        monkeypatch.setattr(contracts, "store", active)
        yield active
    else:
        engine = create_engine("sqlite:///" + (tmp_path / "contracts.db").as_posix())
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            active = SQLAlchemyStore(db)
            monkeypatch.setattr(contracts, "store", active)
            yield active
        engine.dispose()


def seed(active, prefix):
    portfolio = active.create_portfolio(PortfolioCreate(name=prefix))
    prop = active.create_property(PropertyCreate(portfolio_id=portfolio.id, name=prefix, property_type="residential"))
    unit = active.create_unit(UnitCreate(property_id=prop.id, label=prefix, unit_type="apartment"))
    tenant = active.create_tenant(TenantCreate(full_name=prefix))
    item = active.create_contract(ContractCreate(
        contract_number=prefix, property_id=prop.id, unit_id=unit.id, tenant_id=tenant.id,
        status="draft", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
    ))
    return item, portfolio


def insert(active, items):
    if hasattr(active, "db"):
        active.db.execute(ContractORM.__table__.insert(), [item.model_dump() for item in items])
        active.db.commit()
    else:
        active.contracts.update({item.id: item for item in items})


def query(**options):
    values = dict(skip=0, limit=100, property_id=None, tenant_id=None, status_filter=None,
                  sort_by="contract_number", sort_order="asc", date_from=date(2026, 1, 1), date_to=date(2026, 12, 31))
    values.update(options)
    return contracts.list_contracts(**values)


def test_match_beyond_ten_thousand_is_reachable_with_a_small_single_sql_response(contract_store):
    target, _ = seed(contract_store, "Z-valid-after-history")
    # Synthetic draft records can share references. Insert in bounded native
    # batches rather than 10,001 slow HTTP mutations or one giant fixture list.
    for start in range(0, 10001, 500):
        insert(contract_store, [target.model_copy(update={
            "id": f"historical-{index:05d}", "contract_number": f"A-{index:05d}",
            "start_date": date(2010, 1, 1), "end_date": date(2010, 12, 31),
        }) for index in range(start, min(start + 500, 10001))])
    statements = []
    engine = contract_store.db.get_bind() if hasattr(contract_store, "db") else None

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        statements.append((statement, parameters))

    if engine is not None:
        event.listen(engine, "before_cursor_execute", capture)
    try:
        result = query(limit=1, property_id=target.property_id, tenant_id=target.tenant_id, status_filter="draft")
    finally:
        if engine is not None:
            event.remove(engine, "before_cursor_execute", capture)
    assert [item.id for item in result] == [target.id]
    if engine is not None:
        assert len(statements) == 1
        statement, parameters = statements[0]
        assert "contracts.start_date >=" in statement and "contracts.end_date <=" in statement
        assert "LIMIT" in statement and "OFFSET" in statement and "count(" not in statement.lower()
        assert parameters[-2:] == (1, 0)


@pytest.mark.parametrize("date_from,date_to,expected", [
    (date(2026, 1, 1), date(2026, 12, 31), ["A-boundary", "B-inside"]),
    (date(2026, 1, 1), None, ["A-boundary", "B-inside", "D-open-ended", "E-after-end"]),
    (None, date(2026, 12, 31), ["A-boundary", "B-inside", "C-before-start"]),
    (date(2027, 1, 1), date(2026, 12, 31), []),
])
def test_inclusive_start_end_boundaries_and_null_end_semantics(contract_store, date_from, date_to, expected):
    original, _ = seed(contract_store, "A-boundary")
    insert(contract_store, [original.model_copy(update={"id": name, "contract_number": name, **changes})
        for name, changes in (
            ("B-inside", {"start_date": date(2026, 2, 1), "end_date": date(2026, 11, 30)}),
            ("C-before-start", {"start_date": date(2025, 12, 31), "end_date": date(2026, 11, 30)}),
            ("D-open-ended", {"end_date": None}),
            ("E-after-end", {"end_date": date(2027, 1, 1)}),
        )])
    assert [item.contract_number for item in query(date_from=date_from, date_to=date_to)] == expected


def test_authorized_filters_and_sort_precede_offset_without_foreign_portfolio_expansion(contract_store):
    original, portfolio = seed(contract_store, "A-visible")
    hidden, _ = seed(contract_store, "AA-hidden")
    extra_tenant = contract_store.create_tenant(TenantCreate(full_name="Different visible tenant"))
    # Attach the second tenant to the visible portfolio through a real draft,
    # preserving the production tenant-reference visibility rule.
    contract_store.create_contract(ContractCreate(
        contract_number="AB-wrong-tenant", property_id=original.property_id, unit_id=original.unit_id,
        tenant_id=extra_tenant.id, status="draft", start_date=original.start_date, end_date=original.end_date,
    ))
    insert(contract_store, [original.model_copy(update={"id": name, "contract_number": name, **changes})
        for name, changes in (("B-visible", {}), ("C-visible", {}), ("D-visible", {}), ("A-wrong-status", {"status": "expired"}))])
    selected = AccessScope("synthetic-contract-reader", "readonly", False, (portfolio.id,))
    with scope_context(selected):
        assert [item.contract_number for item in query(skip=1, limit=2, tenant_id=original.tenant_id,
            property_id=original.property_id, status_filter="draft", sort_order="desc")] == ["C-visible", "B-visible"]
        assert query(property_id=hidden.property_id) == []
        assert query(tenant_id=hidden.tenant_id) == []
        assert hidden.id not in {item.id for item in query()}


def test_unknown_sort_input_is_not_sql_and_existing_no_date_paging_remains_intact(contract_store):
    original, _ = seed(contract_store, "A-visible")
    insert(contract_store, [original.model_copy(update={"id": "next", "contract_number": "B-visible"})])
    unsafe = "contract_number DESC; DROP TABLE contracts"
    assert len(query(limit=1, sort_by=unsafe)) == 1
    assert [item.contract_number for item in query(date_from=None, date_to=None, skip=1, limit=1)] == ["B-visible"]
    assert len(query()) == 2


def test_real_authenticated_http_date_page_rechecks_portfolio_scope(access_http):  # noqa: F811
    client, active, owner, headers, member, portfolios, _properties, existing, *_ = access_http
    first = existing[0]
    response = client.get("/api/v1/contracts", headers=headers, params={
        "date_from": "2026-01-01", "tenant_id": first.tenant_id, "limit": 1,
    })
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [first.id]
    assert client.get("/api/v1/contracts", headers=headers, params={
        "date_from": "not-a-date", "limit": 1,
    }).status_code == 422
    assert client.get("/api/v1/contracts", headers=headers, params={
        "date_from": "2026-01-01", "property_id": existing[1].property_id, "limit": 1,
    }).json() == []
    # Same token: fresh grant revocation must apply to the filtered SQL query.
    changed = client.patch(f"/api/v1/auth/users/{member.id}", headers=owner,
        json={"portfolio_access": "selected", "portfolio_ids": []})
    assert changed.status_code == 200
    assert client.get("/api/v1/contracts", headers=headers, params={
        "date_from": "2026-01-01", "tenant_id": first.tenant_id, "limit": 1,
    }).json() == []


@pytest.mark.parametrize("mutation", ["delete", "portfolio_move"])
def test_memory_reader_keeps_visibility_and_iteration_under_the_actual_writer_lock(monkeypatch, mutation):
    from backend.services import contract_list, payments
    active = InMemoryStore()
    first, portfolio = seed(active, "A-visible")
    second = first.model_copy(update={"id": "second", "contract_number": "B-visible"})
    insert(active, [second])
    foreign = active.create_portfolio(PortfolioCreate(name="Hidden destination"))
    scope = AccessScope("synthetic-reader", "readonly", False, (portfolio.id,))
    entered, release, writer_attempted = Event(), Event(), Event()
    writer_acquired = Event()
    actual_lock = payments._memory_lock

    class ObservedLock:
        def __enter__(self):
            if current_thread().name.startswith("writer"):
                writer_attempted.set()
            actual_lock.acquire()
            if current_thread().name.startswith("writer"):
                writer_acquired.set()
            return self

        def __exit__(self, *_):
            actual_lock.release()

    monkeypatch.setattr(payments, "_memory_lock", ObservedLock())
    original_visible = contract_list.memory_visible

    def paused_visibility(*args):
        if current_thread().name.startswith("reader") and not entered.is_set():
            entered.set()
            assert release.wait(5), "Synthetic reader was not released"
        return original_visible(*args)

    monkeypatch.setattr(contract_list, "memory_visible", paused_visibility)

    def read():
        with scope_context(scope):
            return contract_list.filtered_contracts(active, skip=0, limit=2,
                filters={}, sort_by="contract_number", descending=False,
                date_from=date(2026, 1, 1), date_to=None)

    def write():
        if mutation == "delete":
            active.delete_contract(second.id)
        else:
            property = active.get_property(first.property_id)
            active.update_property(property.id, PropertyCreate(**{
                **property.model_dump(include=set(PropertyCreate.model_fields)), "portfolio_id": foreign.id}))

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="reader") as readers, \
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="writer") as writers:
        page = readers.submit(read)
        assert entered.wait(5)
        changed = writers.submit(write)
        try:
            assert writer_attempted.wait(5)
            assert not writer_acquired.wait(0.2), "Writer acquired the lock while the reader was paused"
            assert not changed.done(), "Writer passed the paused reader's lock"
        finally:
            release.set()
        assert [row.id for row in page.result(5)] == [first.id, second.id]
        changed.result(5)
    assert [row.id for row in read()] == ([first.id] if mutation == "delete" else [])
