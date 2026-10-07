"""Task regressions on fresh memory and SQLite stores; never uses the live DB."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.db.orm_models import Base, TaskORM
from backend.models import PortfolioCreate, PropertyCreate, TaskCreate, TaskPatch, UnitCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import tasks
from backend.storage import InMemoryStore, ValidationError


@pytest.fixture(params=["memory", "sqlite"])
def task_store(request, monkeypatch):
    engine = None
    session = None
    if request.param == "memory":
        isolated = InMemoryStore()
    else:
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        session = Session(engine)
        isolated = SQLAlchemyStore(session)
    monkeypatch.setattr(tasks, "store", isolated)
    yield isolated
    if session:
        session.close()
    if engine:
        engine.dispose()


@pytest.fixture
def client(task_store):
    app = FastAPI()
    app.include_router(tasks.router)
    with TestClient(app) as client:
        yield client


def test_three_occurrences_advance_and_keep_links(task_store, client):
    pf = task_store.create_portfolio(PortfolioCreate(name="Synthetic"))
    prop = task_store.create_property(PropertyCreate(portfolio_id=pf.id, name="A", property_type="residential"))
    unit = task_store.create_unit(UnitCreate(property_id=prop.id, label="A1", unit_type="apartment"))
    template = task_store.create_task(TaskCreate(title="Monthly", due_date=date(2026, 1, 15),
        recurrence_rule="FREQ=MONTHLY", property_id=prop.id, unit_id=unit.id, assignee="Test"))
    for month in (2, 3, 4):
        response = client.post(f"/tasks/generate-recurring?as_of=2026-{month:02d}-15")
        assert response.status_code == 200, response.text
        child = response.json()[0]
        assert child["due_date"] == f"2026-{month:02d}-15"
        assert child["parent_task_id"] == template.id
        assert child["property_id"] == prop.id and child["unit_id"] == unit.id
        assert child["assignee"] == "Test"
        edit = client.patch(f"/tasks/{child['id']}", json={"title": "Edited", "status": "completed"})
        assert edit.status_code == 200
        assert edit.json()["parent_task_id"] == template.id


@pytest.mark.parametrize("rule", ["FREQ=MONTHLY;INTERVAL=abc", "FREQ=MONTHLY;INTERVAL=0",
    "FREQ=MONTHLY;INTERVAL=-1", "FREQ=HOURLY", "COUNT=2", "FREQ=DAILY;COUNT=0",
    "FREQ=DAILY;UNTIL=broken", "FREQ=DAILY;BYDAY=MO", "FREQ=DAILY;FREQ=WEEKLY"])
def test_reject_invalid_rules_on_every_write(task_store, client, rule):
    response = client.post("/tasks", json={"title": "Bad", "recurrence_rule": rule})
    assert response.status_code == 400, response.text
    valid = task_store.create_task(TaskCreate(title="Valid", recurrence_rule="FREQ=MONTHLY"))
    for method, payload in ((client.put, {"title": "Changed", "recurrence_rule": rule}),
                            (client.patch, {"recurrence_rule": rule})):
        response = method(f"/tasks/{valid.id}", json=payload)
        assert response.status_code == 400, response.text
        assert task_store.get_task(valid.id).recurrence_rule == "FREQ=MONTHLY"


def test_historic_bad_rule_report_does_not_block_valid_series(task_store, client):
    good = task_store.create_task(TaskCreate(title="Good", due_date=date(2026, 1, 15), recurrence_rule="FREQ=MONTHLY"))
    bad = task_store.create_task(TaskCreate(title="Historic", due_date=date(2026, 1, 15)))
    if isinstance(task_store, InMemoryStore):
        task_store.tasks[bad.id] = bad.model_copy(update={"recurrence_rule": "FREQ=MONTHLY;INTERVAL=abc"})
    else:
        task_store.db.get(TaskORM, bad.id).recurrence_rule = "FREQ=MONTHLY;INTERVAL=abc"
        task_store.db.commit()
    response = client.post("/tasks/generate-recurring/report?as_of=2026-02-15")
    assert response.status_code == 200, response.text
    assert [child["parent_task_id"] for child in response.json()["created"]] == [good.id]
    assert response.json()["errors"][0]["task_id"] == bad.id
    assert "INTERVAL" in response.json()["errors"][0]["error"]
    legacy = client.post("/tasks/generate-recurring?as_of=2026-02-15")
    assert legacy.status_code == 200 and legacy.json() == []
    assert legacy.headers["X-Recurring-Error-Count"] == "1"


def test_property_unit_validation_on_merged_patch_and_direct_writes(task_store, client):
    pf = task_store.create_portfolio(PortfolioCreate(name="Synthetic"))
    a, b = [task_store.create_property(PropertyCreate(portfolio_id=pf.id, name=name, property_type="residential")) for name in ("A", "B")]
    unit = task_store.create_unit(UnitCreate(property_id=b.id, label="B1", unit_type="apartment"))
    payload = {"title": "Mismatch", "property_id": a.id, "unit_id": unit.id}
    assert client.post("/tasks", json=payload).status_code == 400
    valid = task_store.create_task(TaskCreate(title="B", property_id=b.id, unit_id=unit.id))
    assert client.put(f"/tasks/{valid.id}", json=payload).status_code == 400
    for patch in ({"property_id": a.id}, {"unit_id": "missing"}, {"property_id": "missing"}):
        assert client.patch(f"/tasks/{valid.id}", json=patch).status_code == 400
        assert task_store.get_task(valid.id).property_id == b.id
    with pytest.raises(ValidationError):
        task_store._patch_entity("task", valid.id, TaskPatch(property_id=a.id))
    # Clearing both associations remains supported.
    assert client.patch(f"/tasks/{valid.id}", json={"property_id": None, "unit_id": None}).status_code == 200


def test_count_children_until_inclusive_and_month_clamp(task_store, client):
    template = task_store.create_task(TaskCreate(title="Count", due_date=date(2026, 1, 31),
        recurrence_rule="FREQ=MONTHLY;COUNT=2;UNTIL=2026-03-28"))
    first = client.post("/tasks/generate-recurring?as_of=2026-02-28").json()[0]
    assert first["due_date"] == "2026-02-28"
    task_store._patch_entity("task", first["id"], TaskPatch(status="completed"))
    second = client.post("/tasks/generate-recurring?as_of=2026-03-28").json()[0]
    assert second["due_date"] == "2026-03-28" and second["parent_task_id"] == template.id
    task_store._patch_entity("task", second["id"], TaskPatch(status="completed"))
    assert client.post("/tasks/generate-recurring?as_of=2026-04-28").json() == []


def test_same_process_concurrent_generation_creates_one_occurrence(task_store):
    task_store.create_task(TaskCreate(title="Concurrent", due_date=date(2026, 1, 15), recurrence_rule="FREQ=MONTHLY"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: tasks.generate_recurring_tasks(as_of=date(2026, 2, 15)), range(8)))
    assert sum(map(len, results)) == 1
    assert len(task_store.list_tasks()) == 2


def test_task_date_range_is_applied_before_page_beyond_10000(task_store, client):
    # Fast bulk insert into a disposable store to cover the former interim cap.
    rows = [dict(id=f"task-{i}", title="Synthetic", due_date=date(2026, 1, 1)) for i in range(10001)]
    rows += [dict(id=f"match-{i}", title="Match", due_date=date(2026, 2, 15)) for i in range(3)]
    if isinstance(task_store, InMemoryStore):
        from backend.models import Task
        task_store.tasks.update({row["id"]: Task(**row) for row in rows})
    else:
        from sqlalchemy import insert
        task_store.db.execute(insert(TaskORM), rows)
        task_store.db.commit()
    response = client.get("/tasks?date_from=2026-02-15&date_to=2026-02-15&skip=1&limit=1")
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()] == ["match-1"]
