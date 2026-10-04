"""Actual complete dashboard sources; no private installation or stock-list stand-ins."""

import os
import subprocess
from datetime import date, datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from backend.db.operational_models import OperationalDispatchORM
from backend.db.orm_models import Base, ContractORM, NotificationORM, TaskORM, UnitORM
from backend.models import NotificationCreate, TaskCreate, Unit
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.portfolio_scope import scope_context
from backend.tests.test_contract_workspace import active as active
from backend.tests.test_contract_workspace import install_actor, seed


@pytest.fixture
def sqlite_store(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "dashboard.sqlite").as_posix(),
        connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            yield SQLAlchemyStore(db)
    finally:
        engine.dispose()


@pytest.fixture
def summary():
    """Run the same target-role assertion against exact historical product bytes."""
    historical = os.environ.get("B1_DASHBOARD_BASELINE")
    if historical:
        assert historical == "79ea761", "Only the recorded untouched baseline is supported"
        root = Path(__file__).resolve().parents[2]
        source = subprocess.run(["git", "show", historical + ":backend/routers/dashboard.py"],
            cwd=root, check=True, capture_output=True).stdout
        name = "backend.routers.dashboard_b1_historical_probe"
        specification = spec_from_loader(name, loader=None)
        assert specification is not None
        module = module_from_spec(specification)
        exec(compile(source, str(root / "backend/routers/dashboard.py") + "@79ea761", "exec"), module.__dict__)

        def historical_summary(store, **_query):
            setattr(module, "store", store)
            return module.get_dashboard_stats()

        return historical_summary
    from backend.services.dashboard_summary import DashboardQuery, dashboard_summary
    return lambda store, **query: dashboard_summary(store, DashboardQuery(**query))


def insert_units(store, prop_id, amount):
    stamp = datetime.now(timezone.utc)
    rows = [Unit(id=f"dashboard-unit-{index:06d}", property_id=prop_id, label=f"Unit {index}",
                 unit_type="apartment", status=("occupied", "rented", "vacant", "reserved", "maintenance")[index % 5],
                 created_at=stamp, updated_at=stamp) for index in range(amount)]
    if hasattr(store, "db"):
        unit_table: Any = UnitORM.__table__
        store.db.execute(unit_table.insert(), [item.model_dump() for item in rows])
        store.db.commit()
    else:
        store.__dict__["units"].update({item.id: item for item in rows})
    return rows


def add_notice(store, prop_id, identifier, role):
    item = store.create_notification(NotificationCreate(title=identifier, content="Synthetic notice",
        notification_type="task_due", entity_type="property", entity_id=prop_id, status="unread"))
    if hasattr(store, "db"):
        store.db.add(OperationalDispatchORM(key=identifier, notification_id=item.id, family="task_due",
            target_role=role, entity_type="property", entity_id=prop_id))
        store.db.commit()
    else:
        from types import SimpleNamespace
        state = store.__dict__.setdefault("_operational_state", {})
        state.setdefault("dispatches", {})[identifier] = SimpleNamespace(notification_id=item.id, target_role=role)
    return item


def test_counts_apply_the_existing_notification_target_role_rule(active, monkeypatch, summary):
    contract, portfolio = seed(active)
    visible = add_notice(active, contract.property_id, "member-notice", "readonly")
    add_notice(active, contract.property_id, "foreign-role-notice", "verwalter")
    add_notice(active, contract.property_id, "unrestricted-notice", None)
    hidden, _ = seed(active, "hidden")
    add_notice(active, hidden.property_id, "foreign-portfolio-notice", "readonly")
    captured, user = install_actor(monkeypatch, [portfolio.id])
    with scope_context(captured):
        result = summary(active, as_of=date(2026, 10, 3))
    assert result["notification_count"] == result["unread_notifications"] == 2
    assert result["portfolio_count"] == result["property_count"] == result["unit_count"] == result["contract_count"] == 1
    assert visible.id in {item["id"] for item in result["work_hints"]["notifications"]["items"]}
    assert {item["title"] for item in result["work_hints"]["notifications"]["items"]} == {
        "member-notice", "unrestricted-notice"}
    assert result["work_hints"]["notifications"]["total"] == 2
    from backend.models import UserRead
    from backend.routers import notifications
    monkeypatch.setattr(notifications, "store", active)
    reader = UserRead(**user, username="reader", email="reader@example.invalid", full_name="Synthetic Reader")
    with scope_context(captured):
        listed = notifications.list_notifications(skip=0, limit=100, status_filter="unread",
            notification_type=None, severity=None, user=reader)
    assert result["unread_notifications"] == len(listed)
    assert {item["id"] for item in result["work_hints"]["notifications"]["items"]} == {item.id for item in listed}
    user["role"] = "eigentuemer"
    from backend.services.portfolio_scope import scope_from_user
    with scope_context(scope_from_user(user)):
        assert summary(active)["notification_count"] == 4


@pytest.mark.parametrize("amount", [101, 1001, 10001])
def test_full_counts_and_occupancy_reach_late_rows(active, amount, summary):
    contract, _ = seed(active)
    # Remove only the fixture's one unit status from the independent expected values.
    original_status = active.get_unit(contract.unit_id).status
    insert_units(active, contract.property_id, amount)
    result = summary(active, as_of=date(2026, 10, 3))
    groups = [amount // 5 + int(amount % 5 > index) for index in range(5)]
    occupancy = result["occupancy"]
    assert result["unit_count"] == occupancy["total"] == amount + 1
    assert occupancy["occupied"] == groups[0] + groups[1] + int(original_status in {"occupied", "rented"})
    assert occupancy["rented"] == groups[1] + int(original_status == "rented")
    assert occupancy["vacant"] == groups[2] + int(original_status == "vacant")
    assert occupancy["reserved"] == groups[3] + int(original_status == "reserved")
    assert occupancy["other"] == groups[4] + int(original_status not in {"occupied", "rented", "vacant", "reserved"})
    assert sum(occupancy[key] for key in ("occupied", "vacant", "reserved", "other")) == amount + 1
    assert result["occupied_units"] == groups[0] + int(original_status == "occupied")
    assert result["billing_presence"]["complete_preflight"] is False


def check_task_pages(active, summary):
    contract, _ = seed(active)
    first = active.create_task(TaskCreate(title="Synthetic task", property_id=contract.property_id))
    tasks = [first.model_copy(update={"id": f"dashboard-task-{index:04d}", "title": f"Task {index}",
        "due_date": date(2026, 10, 3) if index < 101 else None}) for index in range(121)]
    if hasattr(active, "db"):
        task_table: Any = TaskORM.__table__
        active.db.execute(task_table.delete())
        active.db.execute(task_table.insert(), [item.model_dump() for item in tasks])
        active.db.commit()
    else:
        active.__dict__["tasks"].clear()
        active.__dict__["tasks"].update({item.id: item for item in tasks})
    seen: list[str] = []
    after = None
    while True:
        result = summary(active, as_of=date(2026, 10, 3), preview_limit=20, tasks_after=after)
        page = result["work_hints"]["tasks"]
        assert page["total"] == result["open_tasks"] == 121
        assert len(page["items"]) <= 20
        seen.extend(item["id"] for item in page["items"])
        if not page["has_more"]:
            assert page["next_after"] is None
            break
        after = page["next_after"]
        assert after
    assert seen == [item.id for item in tasks]
    assert len(set(seen)) == 121


def test_task_keysets_visit_all_equal_and_null_dates_with_full_total(active, summary):
    check_task_pages(active, summary)


def check_contract_and_notification_pages(store, summary):
    """Independent boundary fixtures, reusable by the native PostgreSQL gate."""
    contract, _ = seed(store, "keysets")
    as_of = date(2026, 10, 3)
    ends = [as_of - timedelta(days=1), as_of, as_of + timedelta(days=90),
            as_of + timedelta(days=91), None] + [as_of + timedelta(days=30)] * 101
    contracts = [contract.model_copy(update={"id": f"dashboard-window-{index:04d}",
        "contract_number": f"Boundary {index}", "start_date": date(2026, 1, 1), "end_date": end})
        for index, end in enumerate(ends)]
    first = store.create_notification(NotificationCreate(title="Synthetic equal-time notice",
        content="Not part of the work projection", notification_type="task_due",
        entity_type="property", entity_id=contract.property_id))
    notices = [first.model_copy(update={"id": f"dashboard-notice-{index:04d}"}) for index in range(101)]
    if hasattr(store, "db"):
        contract_table: Any = ContractORM.__table__
        notice_table: Any = NotificationORM.__table__
        store.db.execute(contract_table.insert(), [row.model_dump() for row in contracts])
        store.db.execute(notice_table.insert(), [row.model_dump() for row in notices])
        store.db.commit()
    else:
        store.__dict__["contracts"].update({row.id: row for row in contracts})
        store.__dict__["notifications"].update({row.id: row for row in notices})
    expected_contracts = [row for row in [contract, *contracts]
        if row.end_date and as_of <= row.end_date <= as_of + timedelta(days=90)]
    expectations = {
        "expiring_contracts": sorted(expected_contracts, key=lambda row: (row.end_date, row.id.encode("utf-8"))),
        "notifications": sorted([first, *notices], key=lambda row: (row.created_at, row.id.encode("utf-8"))),
    }
    for family, expected in expectations.items():
        seen: list[str] = []
        after = None
        parameter = "contracts_after" if family == "expiring_contracts" else "notifications_after"
        while True:
            result = summary(store, as_of=as_of, preview_limit=20, **{parameter: after})
            page = result["work_hints"][family]
            assert page["total"] == len(expected)
            assert len(page["items"]) <= 20
            for item in page["items"]:
                if family == "expiring_contracts":
                    assert 0 <= item["days_remaining"] <= 90
                else:
                    assert "content" not in item and "created_at" not in item
            seen.extend(item["id"] for item in page["items"])
            if not page["has_more"]:
                assert page["next_after"] is None
                break
            after = page["next_after"]
            assert after
        assert seen == [row.id for row in expected]


def test_contract_window_and_notification_keysets_cover_boundaries_and_equal_times(active, summary):
    check_contract_and_notification_pages(active, summary)


def test_counts_and_hints_do_not_materialize_stock_or_autoflush(active, monkeypatch, summary):
    contract, _ = seed(active)
    active.create_task(TaskCreate(title="Small private hint", property_id=contract.property_id))
    for key in ("contracts", "invoices", "receivables", "documents", "maintenance_cases", "tasks",
                "notifications", "rent_charges", "billing_periods", "cost_items", "allocation_keys",
                "utility_statements", "escalation_rules", "units"):
        monkeypatch.setattr(active, "list_" + key, lambda *_args, **_kwargs: pytest.fail("Stock list materialized"))
    if not hasattr(active, "db"):
        assert summary(active)["open_tasks"] == 1
        return
    from backend.repositories.base import BaseRepository
    monkeypatch.setattr(BaseRepository, "list_all", lambda *_args: pytest.fail("ORM stock materialized"))
    active.db.add(NotificationORM(id="pending-notification", title="Do not flush", content="Pending",
        notification_type="task_due", status="unread"))
    statements = []

    def observe(_connection, _cursor, statement, *_args):
        statements.append(statement)

    engine = active.db.get_bind()
    event.listen(engine, "before_cursor_execute", observe)
    try:
        result = summary(active)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert result["open_tasks"] == 1 and result["notification_count"] == 0
    assert active.db.new
    assert not any(statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")) for statement in statements)
    reads = [statement for statement in statements if statement.lstrip().upper().startswith(("SELECT", "WITH"))]
    assert len(reads) == 4
    assert "count(" in reads[0].lower()
    assert all("LIMIT" in statement for statement in reads[1:])
    assert all("description" not in statement.split("FROM", 1)[0].lower() for statement in reads[1:])
    active.db.rollback()


def test_summary_cursor_and_fresh_scope_cannot_be_replayed(active, monkeypatch, summary):
    from backend.services.dashboard_summary import DashboardQuery, _binding
    from backend.services.portfolio_scope import AccessScope
    from backend.services.tenancy_workflow import decode_cursor, encode_cursor

    # A legitimate grant list must not make a generated cursor exceed its own
    # accepted HTTP size. This checks binding size, not large-scope SQL capacity.
    large = AccessScope("synthetic-reader", "readonly", False,
        tuple(f"synthetic-portfolio-{index:05d}" for index in range(10001)))
    binding = _binding(DashboardQuery(), large, "tasks")
    cursor = encode_cursor(binding, [None, "task-id"])
    assert len(cursor) < 8192 and decode_cursor(cursor, binding) == [None, "task-id"]
    different = AccessScope(large.user_id, large.role, False, large.portfolio_ids[:-1])
    with pytest.raises(HTTPException):
        decode_cursor(cursor, _binding(DashboardQuery(), different, "tasks"))
    contract, portfolio = seed(active)
    for index in range(3):
        active.create_task(TaskCreate(title=f"Scope task {index}", property_id=contract.property_id))
    captured, user = install_actor(monkeypatch, [portfolio.id])
    with scope_context(captured):
        result = summary(active, as_of=date(2026, 10, 3), preview_limit=1)
        point = result["work_hints"]["tasks"]["next_after"]
        for values in ({"preview_limit": 2}, {"as_of": date(2026, 10, 4)}, {"tasks_after": point + "x"},
                       {"notifications_after": point}):
            query = {"as_of": date(2026, 10, 3), "preview_limit": 1, "tasks_after": point} | values
            with pytest.raises(HTTPException) as failure:
                summary(active, **query)
            assert failure.value.status_code == 422
        user["portfolio_ids"] = []
        with pytest.raises(HTTPException) as denied:
            summary(active, as_of=date(2026, 10, 3))
        assert denied.value.status_code == 403


def test_native_source_error_is_not_zero_or_empty(sqlite_store, summary):
    seed(sqlite_store)
    engine = sqlite_store.db.get_bind()

    def fail(_connection, _cursor, statement, *_args):
        if "dashboard_tasks" in statement:
            raise RuntimeError("Synthetic unavailable dashboard source")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="unavailable dashboard source"):
            summary(sqlite_store)
    finally:
        event.remove(engine, "before_cursor_execute", fail)


def test_native_sqlite_refuses_schema_and_data_writes_during_summary(sqlite_store, summary):
    import sqlite3

    seed(sqlite_store)
    engine = sqlite_store.db.get_bind()
    denied = []
    actions = {getattr(sqlite3, name) for name in ("SQLITE_INSERT", "SQLITE_UPDATE", "SQLITE_DELETE",
        "SQLITE_CREATE_TABLE", "SQLITE_CREATE_INDEX", "SQLITE_CREATE_TRIGGER", "SQLITE_ALTER_TABLE",
        "SQLITE_DROP_TABLE", "SQLITE_DROP_INDEX", "SQLITE_DROP_TRIGGER")}

    def authorizer(action, *_args):
        if action in actions:
            denied.append(action)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def checkout(driver, *_args):
        driver.set_authorizer(authorizer)

    def checkin(driver, *_args):
        if driver is not None:
            driver.set_authorizer(None)

    event.listen(engine, "checkout", checkout)
    event.listen(engine, "checkin", checkin)
    try:
        assert summary(sqlite_store)["unit_count"] == 1
        assert denied == []
    finally:
        event.remove(engine, "checkout", checkout)
        event.remove(engine, "checkin", checkin)


def test_presence_stays_explicit_and_escalations_are_not_multiplied(active, summary):
    from backend.models import (
        AllocationKeyCreate,
        BillingPeriodCreate,
        ContractPatch,
        CostItemCreate,
        DocumentCreate,
        EscalationRuleCreate,
        MaintenanceCaseCreate,
    )
    contract, _ = seed(active)
    active._patch_entity("contract", contract.id, ContractPatch(status="active"))
    period = active.create_billing_period(BillingPeriodCreate(property_id=contract.property_id, label="Synthetic 2026",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)))
    key = active.create_allocation_key(AllocationKeyCreate(property_id=contract.property_id, name="Area", key_type="area_sqm"))
    active.create_cost_item(CostItemCreate(billing_period_id=period.id, allocation_key_id=key.id, description="Synthetic cost", amount=1))
    active.create_maintenance_case(MaintenanceCaseCreate(property_id=contract.property_id,
        title="Late case", due_date=date(2026, 10, 2), status="in_progress"))
    for index in range(3):
        active.create_escalation_rule(EscalationRuleCreate(name=f"Rule {index}", entity_type="maintenance",
            days_overdue=index, condition_field="due_date", action="notify", is_active=True))
    result = summary(active, as_of=date(2026, 10, 3))
    assert result["maintenance_escalation_candidates"] == 1
    assert result["overdue_maintenance"] == 1
    assert result["active_escalation_rules"] == 3
    assert result["active_contracts_missing_documents"] == 1
    assert result["billing_preflight_periods_checked"] == 1
    assert result["billing_preflight_blockers"] == 0
    assert result["billing_presence"] == {"periods_checked": 1, "blockers": 0, "warnings": 0,
        "basis": "basic_presence_checks", "complete_preflight": False}
    for index in range(2):
        active.create_document(DocumentCreate(title=f"Contract document {index}", contract_id=contract.id,
            property_id=contract.property_id, file_url="/uploads/synthetic.pdf"))
    assert summary(active)["active_contracts_missing_documents"] == 0


def test_earliest_as_of_does_not_overflow_the_memory_rule_cutoff(active, summary):
    from backend.models import EscalationRuleCreate, MaintenanceCaseCreate
    contract, _ = seed(active)
    active.create_maintenance_case(MaintenanceCaseCreate(property_id=contract.property_id,
        title="Earliest supported due date", due_date=date.min, status="open"))
    active.create_escalation_rule(EscalationRuleCreate(name="One day overdue", entity_type="maintenance",
        days_overdue=1, condition_field="due_date", action="notify"))
    result = summary(active, as_of=date.min)
    assert result["maintenance_escalation_candidates"] == result["overdue_maintenance"] == 0
    assert result["open_maintenance"] == 1
