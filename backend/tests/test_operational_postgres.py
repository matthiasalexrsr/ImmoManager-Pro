# ruff: noqa: F811 — imported pytest fixture is intentionally injected by name
"""Optional genuine PostgreSQL gates, each in its own generated schema."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

import pytest
from sqlalchemy import select

from backend.db.operational_models import OperationalOccurrenceORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.operational_schedule import TickRequest, generate_tasks, operational_tick, recent_ticks
from backend.services.recurrence import CatchUpLimit
from backend.tests.test_operational_schedule import rule, template
from backend.tests.test_private_server_concurrency import postgres_database  # noqa: F401


def test_pg_independent_sessions_tick_atomically(postgres_database):
    engine, factory, _, _ = postgres_database
    with factory() as db:
        active = SQLAlchemyStore(db)
        original = template(active, recurrence_rule="FREQ=MONTHLY;COUNT=2")
        rule(active)
    barrier = Barrier(2)
    def tick(_):
        with factory() as db:
            barrier.wait(timeout=10)
            return operational_tick(SQLAlchemyStore(db), TickRequest(as_of=date(2026, 3, 31), full_catch_up=True), kinds={"tasks", "escalation"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(tick, range(2)))
    assert sum(result["tasks_created"] for result in results) == 2
    assert sum(result["notifications_generated"] for result in results) == 2
    with factory() as db:
        assert len([task for task in SQLAlchemyStore(db).list_tasks() if task.parent_task_id == original.id]) == 2
        assert len(db.scalars(select(OperationalOccurrenceORM)).all()) == 2
    assert engine.pool.checkedout() == 0


def test_pg_new_session_retains_deleted_instance_identity(postgres_database):
    _, factory, _, _ = postgres_database
    with factory() as db:
        active = SQLAlchemyStore(db)
        template(active, recurrence_rule="FREQ=MONTHLY;COUNT=1")
        first, = generate_tasks(active, date(2026, 2, 28))
        active.delete_task(first.id)
    with factory() as db:
        assert generate_tasks(SQLAlchemyStore(db), date(2026, 3, 31)) == []


def test_pg_catchup_budget_rolls_back_whole_transaction(postgres_database):
    _, factory, _, _ = postgres_database
    with factory() as db:
        active = SQLAlchemyStore(db)
        template(active, recurrence_rule="FREQ=MONTHLY;COUNT=3")
        with pytest.raises(CatchUpLimit):
            operational_tick(active, TickRequest(as_of=date(2026, 4, 30), full_catch_up=True, max_items=2), kinds={"tasks"})
        assert len(active.list_tasks()) == 1
        assert not db.scalars(select(OperationalOccurrenceORM)).all()
        assert not recent_ticks(active)
