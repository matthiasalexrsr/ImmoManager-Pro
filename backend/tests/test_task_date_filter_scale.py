"""Regression for the former 10,000-row task date-filter truncation."""

import os
from datetime import date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.db.orm_models import Base, TaskORM
from backend.models import PortfolioCreate, PropertyCreate, TaskCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.task_list import filtered_tasks
from backend.storage import InMemoryStore


@pytest.fixture(params=["memory", "sqlite", "postgres"])
def task_store(request, tmp_path):
    engine = db = admin = None
    schema = None
    if request.param == "sqlite":
        engine = create_engine(
            "sqlite:///" + (tmp_path / "tasks.db").as_posix(),
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine, "connect")
        def configure(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
        db = Session(engine)
        store = SQLAlchemyStore(db)
    elif request.param == "postgres":
        source = os.getenv("TEST_SERVER_DATABASE_URL")
        if not source:
            pytest.skip("TEST_SERVER_DATABASE_URL disposable PostgreSQL is not configured")
        url = make_url(source)
        if url.get_backend_name() != "postgresql":
            pytest.fail("TEST_SERVER_DATABASE_URL must reference PostgreSQL")
        schema = "task_filter_" + uuid4().hex
        admin = create_engine(url, hide_parameters=True, pool_pre_ping=True)
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        scoped = url.update_query_dict({"options": "-csearch_path=" + schema})
        engine = create_engine(scoped, hide_parameters=True, pool_pre_ping=True)
        Base.metadata.create_all(engine)
        db = Session(engine)
        store = SQLAlchemyStore(db)
    else:
        store = InMemoryStore()
    yield store
    if db:
        db.close()
        engine.dispose()
    if admin is not None and schema is not None:
        try:
            with admin.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        finally:
            admin.dispose()


def seed_large(store, count=10025):
    target_id = f"task-{count - 1:05d}"
    if hasattr(store, "db"):
        stamp = datetime(2026, 1, 1)
        rows = [
            {
                "id": f"task-{index:05d}",
                "title": f"Task {index:05d}",
                "description": None,
                "assignee": "late" if index == count - 1 else "old",
                "due_date": date(2030, 1, 1) if index == count - 1 else date(2020, 1, 1),
                "priority": "medium",
                "status": "open",
                "property_id": None,
                "unit_id": None,
                "recurrence_rule": None,
                "parent_task_id": None,
                "created_at": stamp,
                "updated_at": stamp,
            }
            for index in range(count)
        ]
        store.db.execute(insert(TaskORM), rows)
        store.db.commit()
    else:
        for index in range(count):
            task = TaskCreate(
                title=f"Task {index:05d}",
                assignee="late" if index == count - 1 else "old",
                due_date=date(2030, 1, 1) if index == count - 1 else date(2020, 1, 1),
            )
            created = store.create_task(task)
            if index == count - 1:
                target_id = created.id
    return target_id


def test_date_filter_finds_match_after_old_ten_thousand_cap_with_small_page(task_store):
    target_id = seed_large(task_store)
    page = filtered_tasks(
        task_store,
        skip=0,
        limit=2,
        filters={"status": "open", "assignee": "late"},
        sort_by="due_date",
        descending=False,
        date_from=date(2030, 1, 1),
        date_to=date(2030, 12, 31),
    )
    assert len(page) == 1
    assert page[0].id == target_id
    assert page[0].due_date == date(2030, 1, 1)


def test_date_filter_preserves_status_assignee_sort_and_offset(task_store):
    for title, assignee, status, due in (
        ("Charlie", "tech", "open", date(2027, 3, 1)),
        ("Alpha", "tech", "open", date(2027, 1, 1)),
        ("Bravo", "tech", "completed", date(2027, 2, 1)),
        ("Delta", "other", "open", date(2027, 4, 1)),
    ):
        task_store.create_task(
            TaskCreate(title=title, assignee=assignee, status=status, due_date=due)
        )
    page = filtered_tasks(
        task_store,
        skip=1,
        limit=1,
        filters={"status": "open", "assignee": "tech"},
        sort_by="title",
        descending=False,
        date_from=date(2027, 1, 1),
        date_to=date(2027, 12, 31),
    )
    assert [item.title for item in page] == ["Charlie"]


def test_date_filter_keeps_portfolio_scope(task_store):
    first = task_store.create_portfolio(PortfolioCreate(name="Allowed"))
    second = task_store.create_portfolio(PortfolioCreate(name="Hidden"))
    p1 = task_store.create_property(
        PropertyCreate(portfolio_id=first.id, name="A", property_type="residential")
    )
    p2 = task_store.create_property(
        PropertyCreate(portfolio_id=second.id, name="B", property_type="residential")
    )
    visible = task_store.create_task(
        TaskCreate(title="Visible", property_id=p1.id, due_date=date(2028, 1, 1))
    )
    task_store.create_task(
        TaskCreate(title="Hidden", property_id=p2.id, due_date=date(2028, 1, 1))
    )
    scope = scope_from_user(
        {
            "id": "scoped",
            "role": "verwalter",
            "portfolio_access": "selected",
            "portfolio_ids": [first.id],
        }
    )
    with scope_context(scope):
        page = filtered_tasks(
            task_store,
            skip=0,
            limit=10,
            filters={"status": None, "assignee": None},
            sort_by="title",
            descending=False,
            date_from=date(2028, 1, 1),
            date_to=date(2028, 1, 1),
        )
    assert [item.id for item in page] == [visible.id]
